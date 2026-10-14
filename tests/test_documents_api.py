"""M2 review API (Section 10.2, FR-6, FR-8, FR-11.3), fixture-driven and with no model.

Journey: upload -> events -> working result -> page image -> edits -> Verify -> save choice ->
output, then close. Plus the state rules (API-4, FR-6.16), security on every new route (API-1,
API-6) and "nothing on disk" (FR-11.3, API-2).
"""

import builtins
import json
import logging
import os
import tempfile
import threading
import time
from importlib.resources import files

import docgen
import jsonschema
import pytest
from starlette.testclient import TestClient

from nabu.config import Config
from nabu.hardening import configure_logging
from nabu.lang.memory import TranslationMemory
from nabu.ocr.engine import OcrResult
from nabu.ocr.words import Line, Word
from nabu.pipeline import Readers
from nabu.server.app import FILES_HEADER, create_app
from nabu.server.documents import DocumentService

pytest.importorskip("PIL")
pytest.importorskip("pypdfium2")

PORT = 8765
TOKEN = "t" * 43
SECRET = "INV-0042"
PDF = docgen.pdf([[(60, 80, f"Invoice no: {SECRET}"), (60, 110, "Total: 12.50 EUR"),
                   (60, 140, "Customer: Kim Example")]])


class FakeOcr:
    """Two words per page; `gate` (when set) blocks reading until released."""

    def __init__(self, gate: threading.Event | None = None) -> None:
        self.gate = gate

    def read(self, page):
        if self.gate is not None:
            self.gate.wait(10)
        return OcrResult(lines=[Line(words=(Word("Ref", (100, 100, 160, 120)),
                                            Word(f"P{page.page}-77", (400, 100, 520, 120))))],
                         notes=[])


def make_client(tmp_path, ocr=None, limit_mb=100):
    dist = tmp_path / "ui_dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text('<html><head><meta name="nabu-token" content=""></head></html>')
    readers = Readers(ocr=ocr, model=None, memory=TranslationMemory())
    service = DocumentService(Config(), lambda: readers)
    app, _ = create_app(PORT, token=TOKEN, ui_dist=dist, documents=service, upload_limit_mb=limit_mb)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    c.get("/")  # claim the window, as the browser does
    c.headers["x-nabu-token"] = TOKEN
    return c, service


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)[0]


def upload(c, *files_):
    meta = [{"name": n, "size": len(d)} for n, d in files_]
    return c.post("/api/documents", content=b"".join(d for _, d in files_),
                  headers={FILES_HEADER: json.dumps(meta)})


def wait_ready(c, doc_id, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        d = c.get(f"/api/documents/{doc_id}").json()
        if d["state"] != "reading":
            return d
        time.sleep(0.05)
    raise AssertionError("reading did not finish")


def open_pdf(c):
    r = upload(c, ("invoice.pdf", PDF))
    assert r.status_code == 202
    doc_id = r.json()["document_id"]
    return doc_id, wait_ready(c, doc_id)


def by_label(d, word):
    return next(f for f in d["fields"] if word in (f["printed_label"] or ""))


def schema():
    return json.loads(files("nabu.schemas").joinpath("output.schema.json").read_text())


def test_full_journey_without_model(client):
    doc_id, d = open_pdf(client)
    assert d["state"] == "ready" and d["link"]["outcome"] == "none" and not d["verified"]
    base = f"/api/documents/{doc_id}"

    ev = client.get(base + "/events")  # finished jobs replay their events and end
    assert ev.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in ev.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done" and any(e["type"] == "progress" for e in events)

    img = client.get(base + "/pages/1.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.headers["cache-control"] == "no-store"  # API-5
    assert client.get(base + "/pages/9.png").status_code == 404

    inv, total, cust = by_label(d, "Invoice"), by_label(d, "Total"), by_label(d, "Customer")
    assert client.patch(f"{base}/fields/{inv['id']}", json={"name": "Invoice Number"}).status_code == 200
    r = client.patch(f"{base}/fields/{total['id']}", json={"value": "12.60 EUR", "value_type": "amount"})
    assert r.json()["value_en"] == "12.60 EUR" and "edited_by_user" in r.json()["status"]
    client.patch(f"{base}/fields/{cust['id']}", json={"removed": True})
    client.patch(f"{base}/fields/{cust['id']}", json={"removed": False})  # restored (FR-6.8)
    client.patch(f"{base}/fields/{cust['id']}", json={"removed": True})

    assert client.get(base + "/output").status_code == 409  # API-4: nothing before Verify
    s = client.post(base + "/verify").json()
    assert s["fields"] == len(d["fields"]) - 1 and s["can_confirm"] and s["save_dialog_needed"]
    assert s["save_choices"] == {"document_only": True, "new": False, "update": False}
    assert client.get(base + "/output").status_code == 409  # Verify alone is not the save choice
    assert client.post(base + "/save", json={"choice": "new"}).status_code == 409  # M3
    assert client.post(base + "/save", json={"choice": "document_only"}).status_code == 200

    out = client.get(base + "/output")
    assert out.status_code == 200
    assert out.headers["content-disposition"] == 'attachment; filename="invoice.pdf.nabu.json"'
    doc = out.json()
    jsonschema.validate(doc, schema())
    names = [f["name"] for f in doc["fields"]]
    assert "Invoice Number" in names and not any("Customer" in n for n in names)
    assert {"name": "Invoice Number", "value": SECRET} in doc["fields"]
    assert client.get(base).json()["verified"] is True

    assert client.delete(base).status_code == 200
    assert client.get(base).status_code == 404
    assert upload(client, ("again.pdf", PDF)).status_code == 202  # a new document can open


def test_edit_after_save_needs_a_new_verify(client):
    doc_id, d = open_pdf(client)
    base = f"/api/documents/{doc_id}"
    client.post(base + "/verify")
    client.post(base + "/save", json={"choice": "document_only"})
    assert client.get(base + "/output").status_code == 200
    client.patch(f"{base}/fields/{d['fields'][0]['id']}", json={"name": "Changed"})
    assert client.get(base + "/output").status_code == 409
    assert client.post(base + "/save", json={"choice": "document_only"}).status_code == 409


def test_duplicate_names_block_verify(client):  # FR-6.16
    doc_id, d = open_pdf(client)
    base = f"/api/documents/{doc_id}"
    a, b = d["fields"][0]["id"], d["fields"][1]["id"]
    client.patch(f"{base}/fields/{a}", json={"name": "Same"})
    client.patch(f"{base}/fields/{b}", json={"name": "same"})
    s = client.post(base + "/verify").json()
    assert s["duplicates"] == ["Same"] and not s["can_confirm"]
    assert client.post(base + "/save", json={"choice": "document_only"}).status_code == 409
    client.patch(f"{base}/fields/{b}", json={"removed": True})  # removing one resolves it
    assert client.post(base + "/verify").json()["can_confirm"]


def test_one_document_at_a_time(client):
    assert client.get("/api/documents").json() == {"document_id": None, "state": None}
    doc_id, _ = open_pdf(client)
    assert client.get("/api/documents").json() == {"document_id": doc_id, "state": "ready"}
    r = upload(client, ("second.pdf", PDF))
    assert r.status_code == 409 and "close it first" in r.json()["error"]


@pytest.mark.parametrize("files_, headers, status", [
    ([("notes.exe", b"MZ\x90\x00")], None, 415),
    ([("a.pdf", PDF), ("b.png", docgen.page_image([("A:", "1")]))], None, 415),  # FR-2.8
    ([("a.pdf", PDF)], {FILES_HEADER: json.dumps([{"name": "a.pdf", "size": 5}])}, 400),
    ([("a.pdf", PDF)], {FILES_HEADER: "not json"}, 400),
])
def test_upload_errors_are_named(client, files_, headers, status):
    if headers is None:
        r = upload(client, *files_)
    else:
        r = client.post("/api/documents", content=b"".join(d for _, d in files_), headers=headers)
    assert r.status_code == status and r.json()["error"]


def test_upload_limit(tmp_path):
    c, _ = make_client(tmp_path, limit_mb=1)
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024)
    r = upload(c, ("big.pdf", big))
    assert r.status_code == 413 and "1 MB" in r.json()["error"]


ROUTES = [("GET", ""), ("DELETE", ""), ("GET", "/events"), ("GET", "/pages/1.png"),
          ("PUT", "/pages/order"), ("POST", "/fields"), ("PATCH", "/fields/f1"),
          ("PATCH", "/translations/f1.name"), ("PATCH", "/header"), ("POST", "/verify"),
          ("POST", "/save"), ("GET", "/output")]


@pytest.mark.parametrize("method, suffix", ROUTES)
def test_every_document_route_needs_the_token(client, method, suffix):  # API-1, API-6
    doc_id, _ = open_pdf(client)
    url = f"/api/documents/{doc_id}{suffix}"
    assert client.request(method, url, headers={"x-nabu-token": ""}).status_code == 401
    assert client.request(method, f"{url}?token={TOKEN}", headers={"x-nabu-token": ""}).status_code == 401


def test_upload_needs_the_token(client):
    assert client.get("/api/documents", headers={"x-nabu-token": ""}).status_code == 401
    r = client.post("/api/documents", content=PDF, headers={"x-nabu-token": "",
                    FILES_HEADER: json.dumps([{"name": "a.pdf", "size": len(PDF)}])})
    assert r.status_code == 401


def test_unknown_document_id(client):
    open_pdf(client)
    assert client.get("/api/documents/not-it").status_code == 404


def test_drawn_box_takes_the_words_inside(tmp_path):  # FR-6.9
    c, _ = make_client(tmp_path, ocr=FakeOcr())
    r = upload(c, ("scan.png", docgen.page_image([("Ref", "x")])))
    doc_id = r.json()["document_id"]
    wait_ready(c, doc_id)
    base = f"/api/documents/{doc_id}"
    r = c.post(base + "/fields", json={"name": "Reference", "page": 1, "box": [380, 90, 540, 130]})
    assert r.status_code == 201
    f = r.json()
    assert f["value"] == "P1-77" and f["source"] == "user" and f["box_source"] == "ocr"
    empty = c.post(base + "/fields", json={"name": "Empty", "page": 1, "box": [10, 900, 50, 950]}).json()
    assert empty["value"] is None and "not_found" in empty["status"]
    assert c.post(base + "/fields", json={"name": "X", "page": 4, "box": [0, 0, 9, 9]}).status_code == 404
    assert c.post(base + "/fields", json={"name": "X", "page": 1, "box": [5, 5, 5, 9]}).status_code == 400


def test_reorder_images_before_verify(tmp_path):  # FR-6.2
    c, service = make_client(tmp_path, ocr=FakeOcr())
    front = docgen.page_image([("Front", "1")])
    back = docgen.page_image([("Back", "2")], size=(1000, 700))
    doc_id = upload(c, ("front.png", front), ("back.png", back)).json()["document_id"]
    d = wait_ready(c, doc_id)
    base = f"/api/documents/{doc_id}"
    p1, p2 = c.get(base + "/pages/1.png").content, c.get(base + "/pages/2.png").content
    widths = [p["width_px"] for p in d["document"]["pages"]]
    r = c.put(base + "/pages/order", json={"order": [2, 1]})
    assert r.status_code == 200
    assert [p["width_px"] for p in r.json()["document"]["pages"]] == widths[::-1]
    assert c.get(base + "/pages/1.png").content == p2 and c.get(base + "/pages/2.png").content == p1
    assert c.put(base + "/pages/order", json={"order": [1, 1]}).status_code == 400


def test_translation_and_header(client):
    doc_id, d = open_pdf(client)
    base = f"/api/documents/{doc_id}"
    fid = d["fields"][0]["id"]
    r = client.patch(f"{base}/translations/{fid}.name", json={"english": "Invoice", "remember": True})
    assert r.status_code == 409  # remembering is M3
    r = client.patch(f"{base}/translations/{fid}.name", json={"english": "Invoice"})
    assert r.json()["name"] == "Invoice" and "not_translated" not in r.json()["status"]
    assert client.patch(f"{base}/translations/{fid}.other", json={"english": "x"}).status_code == 404
    assert client.patch(f"{base}/header", json={"region": "Germany"}).status_code == 400
    h = client.patch(f"{base}/header", json={"document_type": "Invoice", "region": "DE"}).json()
    assert h == {"document_type": "Invoice", "region": "DE", "format": None}
    client.post(base + "/verify")
    client.post(base + "/save", json={"choice": "document_only"})
    out = client.get(base + "/output").json()
    assert out["document_type"] == "Invoice" and out["region"] == "DE"


def test_cancel_while_reading(tmp_path):  # FR-6.15
    gate = threading.Event()
    c, service = make_client(tmp_path, ocr=FakeOcr(gate))
    doc_id = upload(c, ("a.png", docgen.page_image([("A", "1")])),
                    ("b.png", docgen.page_image([("B", "2")]))).json()["document_id"]
    doc = service.current
    assert c.get(f"/api/documents/{doc_id}").json()["state"] == "reading"
    assert c.delete(f"/api/documents/{doc_id}").status_code == 200
    gate.set()
    end = time.monotonic() + 10
    while doc.state == "reading" and time.monotonic() < end:
        time.sleep(0.02)
    assert doc.state == "cancelled" and doc.result is None and doc.session.closed
    assert service.current is None


@pytest.fixture
def product_logging(tmp_path):
    """The logging `nabu serve` configures (verbose), restored afterwards for other tests."""
    names = ["nabu", "httpx", "httpcore", "uvicorn.access", "multipart", "PIL", "pdfminer"]
    saved = {n: (logging.getLogger(n).level, logging.getLogger(n).propagate,
                 list(logging.getLogger(n).handlers), logging.getLogger(n).disabled) for n in names}
    configure_logging(tmp_path / "logs", verbose=True)
    yield tmp_path / "logs" / "nabu.log"
    for n, (level, propagate, handlers, disabled) in saved.items():
        lg = logging.getLogger(n)
        for h in lg.handlers:
            if h not in handlers:
                h.close()
        lg.setLevel(level)
        lg.propagate, lg.handlers, lg.disabled = propagate, handlers, disabled


def test_nothing_written_to_disk_and_no_values_in_logs(tmp_path, monkeypatch, nabu_home,
                                                       product_logging):
    """FR-11.3 / API-2: no file is opened for writing and no temp file is made during a session;
    FR-11.5: the log file (same handlers and formatter as the console) carries no value."""
    c, _ = make_client(tmp_path)
    writes: list[str] = []
    real_open, real_os_open = builtins.open, os.open

    def guarded_open(file, mode="r", *a, **kw):
        if any(m in mode for m in "wax+"):
            writes.append(str(file))
        return real_open(file, mode, *a, **kw)

    def guarded_os_open(path, flags, *a, **kw):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            writes.append(str(path))
        return real_os_open(path, flags, *a, **kw)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    for name in ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"):
        monkeypatch.setattr(tempfile, name, lambda *a, _n=name, **kw: writes.append(_n))

    doc_id, d = open_pdf(c)
    base = f"/api/documents/{doc_id}"
    c.patch(f"{base}/fields/{d['fields'][0]['id']}", json={"value": "TYPED-SECRET-9"})
    c.post(base + "/verify")
    c.post(base + "/save", json={"choice": "document_only"})
    assert c.get(base + "/output").status_code == 200
    c.delete(base)

    monkeypatch.undo()
    assert writes == []
    assert not nabu_home.exists() or not any(nabu_home.rglob("*"))
    for h in logging.getLogger("nabu").handlers:
        h.flush()
    logged = product_logging.read_text(encoding="utf-8")
    assert SECRET not in logged and "TYPED-SECRET-9" not in logged
