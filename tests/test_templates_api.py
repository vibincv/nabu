"""M3 templates through the review API (FR-5, FR-7, FR-9.8, UX-4), with the real store in a
temporary NABU_HOME and no model.

Covers FR-5 acceptance (a)-(f) and FR-7 acceptance (a)-(f), plus: no value ever reaches the
store, the template manager routes, and remembered translations.
"""

import json
import time

import docgen
import pytest
from starlette.testclient import TestClient

from nabu.config import Config
from nabu.lang.memory import TranslationMemory
from nabu.pipeline import Readers
from nabu.server.app import FILES_HEADER, create_app
from nabu.server.documents import DocumentService
from nabu.store.paths import default_paths
from nabu.store.store import Store

pytest.importorskip("PIL")
pytest.importorskip("pypdfium2")

PORT = 8765
TOKEN = "t" * 43


def layout_a(inv, date, total, cust=None):
    lines = [(60, 80, f"Invoice no: {inv}"), (60, 110, f"Date: {date}"),
             (60, 140, f"Total: {total}")]
    if cust is not None:
        lines.append((60, 170, f"Customer: {cust}"))
    return docgen.pdf([lines])


def layout_b(inv, date, total, cust):  # same labels, another place on the page
    return docgen.pdf([[(330, 420, f"Invoice no: {inv}"), (330, 450, f"Date: {date}"),
                        (330, 480, f"Total: {total}"), (330, 510, f"Customer: {cust}")]])


def layout_half(inv, date, total, cust):  # two labels where A has them, two moved
    return docgen.pdf([[(60, 80, f"Invoice no: {inv}"), (60, 110, f"Date: {date}"),
                        (330, 600, f"Total: {total}"), (330, 630, f"Customer: {cust}")]])


A1 = ("INV-0042", "2026-01-05", "12.50 EUR", "Kim Example")
A2 = ("INV-7781", "2026-02-11", "99.00 EUR", "Lee Sample")
VALUES = [v for row in (A1, A2) for v in row]


@pytest.fixture
def store(nabu_home):
    return Store(default_paths())


@pytest.fixture
def client(tmp_path, store):
    dist = tmp_path / "ui_dist"
    dist.mkdir()
    (dist / "index.html").write_text('<html><head><meta name="nabu-token" content=""></head></html>')

    def readers():  # the translation memory is read fresh for each document, as in serve
        return Readers(ocr=None, model=None, memory=TranslationMemory(store.translations()))

    service = DocumentService(Config(), readers, store)
    app, _ = create_app(PORT, token=TOKEN, ui_dist=dist, documents=service)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    c.get("/")
    c.headers["x-nabu-token"] = TOKEN
    return c


def wait_ready(c, doc_id, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        d = c.get(f"/api/documents/{doc_id}").json()
        if d["state"] != "reading":
            assert d["state"] == "ready", d
            return d
        time.sleep(0.05)
    raise AssertionError("reading did not finish")


def open_doc(c, data, name="invoice.pdf"):
    r = c.post("/api/documents", content=data,
               headers={FILES_HEADER: json.dumps([{"name": name, "size": len(data)}])})
    assert r.status_code == 202, r.text
    doc_id = r.json()["document_id"]
    return doc_id, wait_ready(c, doc_id)


def close(c, doc_id):
    assert c.delete(f"/api/documents/{doc_id}").status_code == 200


def field(d, label):
    return next(f for f in d["fields"] if label in (f["printed_label"] or ""))


def save_new(c, doc_id, fmt="Format A", doc_type="Vendor invoice", region="SG"):
    s = c.post(f"/api/documents/{doc_id}/verify").json()
    assert s["can_confirm"] and s["save_dialog_needed"]
    r = c.post(f"/api/documents/{doc_id}/save",
               json={"choice": "new", "document_type": doc_type, "region": region, "format": fmt})
    assert r.status_code == 200, r.text
    return s


def learn_a(c, fmt="Format A"):
    """FR-7 (a): an unlinked document, two names edited, saved as a new template."""
    doc_id, d = open_doc(c, layout_a(*A1))
    base = f"/api/documents/{doc_id}"
    if d["link"]["outcome"] != "none":  # a second template of this layout: read without one
        c.put(f"{base}/link", json={"template_id": None})
        d = wait_ready(c, doc_id)
    assert d["link"]["outcome"] == "none"
    c.patch(f"{base}/fields/{field(d, 'Invoice')['id']}", json={"name": "Invoice Number"})
    c.patch(f"{base}/fields/{field(d, 'Customer')['id']}", json={"name": "Buyer"})
    s = save_new(c, doc_id, fmt)
    assert s["suggested"] == "new"
    assert s["changes"]["renamed"] == [["Invoice no", "Invoice Number"], ["Customer", "Buyer"]]
    assert "Invoice no" in s["labels"]  # what goes to disk is shown first (FR-7.1)
    out = json.loads(c.get(f"{base}/output").content)
    assert out["template_id"].startswith("tpl_vendor_invoice_SG_format")
    close(c, doc_id)
    return out["template_id"]


def store_bytes(nabu_home):
    return b"".join(p.read_bytes() for p in sorted(nabu_home.rglob("*")) if p.is_file())


def assert_no_values(nabu_home):
    blob = store_bytes(nabu_home).decode("utf-8")
    for v in VALUES:
        assert v not in blob, f"a value reached the store: {v!r}"


def test_removed_field_labelled_by_a_value_is_left_out(client, store, nabu_home):  # AR-7
    # A label-less card: discovery takes a printed value as a label. Removing that field must
    # not write the value as a removed label or name, nor refuse the save.
    data = docgen.pdf([[(60, 80, "Invoice no: INV-0042"), (60, 110, "Date: 2026-01-05"),
                        (60, 140, "INV-0042 copy: yes")]])
    doc_id, d = open_doc(client, data)
    junk = field(d, "INV-0042 copy")
    client.patch(f"/api/documents/{doc_id}/fields/{junk['id']}", json={"removed": True})
    save_new(client, doc_id)
    tid = json.loads(client.get(f"/api/documents/{doc_id}/output").content)["template_id"]
    close(client, doc_id)
    t = store.load_template(tid)
    assert t["removed_labels"] == [] and t["template"]["change"]["removed"] == []
    assert "INV-0042" not in store_bytes(nabu_home).decode("utf-8")


def test_save_new_then_link_with_edited_names(client, store, nabu_home):  # FR-7 (a)(b), FR-5 (a)(e)
    tid = learn_a(client)
    t = store.load_template(tid)
    assert [f["name"] for f in t["fields"]] == ["Invoice Number", "Date", "Total", "Buyer"]
    assert t["template"]["region"] == "SG" and t["template"]["format"]["name"] == "Format A"
    assert t["template"]["pages"] == [{"aspect": 0.71}]
    assert all(f["anchor"]["box"] and f["anchor"]["value_offset"] for f in t["fields"])
    assert_no_values(nabu_home)

    doc_id, d = open_doc(client, layout_a(*A2))
    assert d["link"]["outcome"] == "linked" and d["link"]["template_id"] == tid
    assert d["link"]["score"] == 1.0
    assert d["header"] == {"document_type": "Vendor invoice", "region": "SG", "format": "Format A"}
    got = [(f["name"], f["value"], f["source"], f["status"]) for f in d["fields"]]
    assert got == [("Invoice Number", "INV-7781", "template", ["from_template"]),
                   ("Date", "2026-02-11", "template", ["from_template"]),
                   ("Total", "99.00 EUR", "template", ["from_template"]),
                   ("Buyer", "Lee Sample", "template", ["from_template"])]
    assert not d["document"]["model_used"]  # linking needs no model (FR-5.1)
    s = client.post(f"/api/documents/{doc_id}/verify").json()
    assert not s["save_dialog_needed"]  # FR-6.12: template used as it is
    out = json.loads(client.get(f"/api/documents/{doc_id}/output").content)
    assert (out["template_id"], out["template_version"]) == (tid, 1)
    assert [f["name"] for f in out["fields"]] == ["Invoice Number", "Date", "Total", "Buyer"]
    close(client, doc_id)
    assert_no_values(nabu_home)


def test_second_format_of_same_type_and_region(client, store):  # FR-7 (c), FR-5 (b)
    tid_a = learn_a(client)
    doc_id, d = open_doc(client, layout_b(*A1))
    assert d["link"]["outcome"] in ("similar", "none")
    client.patch(f"/api/documents/{doc_id}/header",
                 json={"document_type": "Vendor invoice", "region": "SG"})
    s = save_new(client, doc_id, fmt="Format B")
    assert s["format_suggestion"] == "Format B" and s["document_types"] == ["Vendor invoice"]
    close(client, doc_id)
    doc_id, d = open_doc(client, layout_b(*A2))
    tid_b = d["link"]["template_id"]
    assert d["link"]["outcome"] == "linked" and tid_b not in (None, tid_a)
    assert store.load_template(tid_b)["template"]["format"]["name"] == "Format B"
    close(client, doc_id)
    doc_id, d = open_doc(client, layout_a(*A2))
    assert d["link"]["template_id"] == tid_a  # A documents still go to A
    close(client, doc_id)


def test_similar_suggests_names_and_prefills(client):  # FR-5 (c), FR-5.6
    learn_a(client)
    doc_id, d = open_doc(client, layout_half(*A2))
    assert d["link"]["outcome"] == "similar" and d["link"]["score"] == 0.5
    assert d["link"]["candidates"][0]["format"] == "Format A"
    assert d["header"]["document_type"] == "Vendor invoice" and d["header"]["region"] == "SG"
    inv = field(d, "Invoice")
    assert inv["name"] == "Invoice no" and inv["name_suggestion"] == "Invoice Number"
    assert "suggested" in inv["status"]
    f = client.patch(f"/api/documents/{doc_id}/fields/{inv['id']}", json={"accept": True}).json()
    assert f["name"] == "Invoice Number" and f["name_suggestion"] is None  # one click
    s = client.post(f"/api/documents/{doc_id}/verify").json()
    assert s["suggested"] == "new" and s["save_dialog_needed"]
    close(client, doc_id)


def test_ambiguous_then_user_picks(client):  # FR-5 (d), FR-5.8
    tid_a = learn_a(client)
    tid_a2 = learn_a(client, fmt="Format A2")  # a near-identical template
    doc_id, d = open_doc(client, layout_a(*A2))
    assert d["link"]["outcome"] == "ambiguous"
    assert {c["template_id"] for c in d["link"]["candidates"]} == {tid_a, tid_a2}
    r = client.put(f"/api/documents/{doc_id}/link", json={"template_id": tid_a2})
    assert r.status_code == 202
    d = wait_ready(client, doc_id)
    assert d["link"]["outcome"] == "linked" and d["link"]["chosen"]
    assert d["link"]["template_id"] == tid_a2 and d["header"]["format"] == "Format A2"
    client.put(f"/api/documents/{doc_id}/link", json={"template_id": None})
    d = wait_ready(client, doc_id)
    assert d["link"]["outcome"] == "none" and d["fields"][0]["source"] == "discovery_rules"
    assert client.put(f"/api/documents/{doc_id}/link",
                      json={"template_id": "tpl_nope"}).status_code == 404
    close(client, doc_id)


def test_missing_field_is_not_found(client):  # FR-5 (f), FR-5.9 without a model
    learn_a(client)
    doc_id, d = open_doc(client, layout_a(*A2[:3]))  # no Customer line
    assert d["link"]["outcome"] == "linked"  # 3 of 4 anchors = 0.75
    buyer = next(f for f in d["fields"] if f["name"] == "Buyer")
    assert buyer["value"] is None and {"not_found", "needs_review"} <= set(buyer["status"])
    close(client, doc_id)


def test_update_removes_field_history_and_rollback(client, store, nabu_home):  # FR-7 (d)(f)
    tid = learn_a(client)
    doc_id, d = open_doc(client, layout_a(*A2))
    base = f"/api/documents/{doc_id}"
    total = next(f for f in d["fields"] if f["name"] == "Total")
    client.patch(f"{base}/fields/{total['id']}", json={"removed": True})
    s = client.post(f"{base}/verify").json()
    assert s["save_dialog_needed"] and s["suggested"] == "update"
    assert s["changes"]["removed"] == ["Total"]
    assert [t["template_id"] for t in s["update_targets"]] == [tid]
    assert client.post(f"{base}/save", json={"choice": "update"}).status_code == 200
    out = json.loads(client.get(f"{base}/output").content)
    assert (out["template_id"], out["template_version"]) == (tid, 2)
    close(client, doc_id)
    t = store.load_template(tid)
    assert [f["name"] for f in t["fields"]] == ["Invoice Number", "Date", "Buyer"]
    assert t["removed_labels"] == ["Total"]

    doc_id, d = open_doc(client, layout_a(*A1))
    assert [f["name"] for f in d["fields"]] == ["Invoice Number", "Date", "Buyer"]
    close(client, doc_id)

    h = client.get(f"/api/templates/{tid}/history").json()["versions"]
    assert [(v["version"], v["change"]["kind"]) for v in h] == [(1, "created"), (2, "updated")]
    assert h[1]["change"]["removed"] == ["Total"]
    r = client.post(f"/api/templates/{tid}/rollback", json={"version": 1})
    assert r.status_code == 200 and r.json()["template"]["version"] == 3
    assert [f["name"] for f in store.load_template(tid)["fields"]] == \
        ["Invoice Number", "Date", "Total", "Buyer"]
    assert client.post(f"/api/templates/{tid}/rollback", json={"version": 9}).status_code == 409
    assert_no_values(nabu_home)


def test_document_only_and_cancel_change_no_template(client, store):  # FR-7 (e)
    tid = learn_a(client)
    path = store.find_template(tid)
    before = path.read_bytes()
    doc_id, d = open_doc(client, layout_a(*A2))
    base = f"/api/documents/{doc_id}"
    client.patch(f"{base}/fields/{d['fields'][1]['id']}", json={"name": "Invoice Date"})
    assert client.post(f"{base}/verify").json()["save_dialog_needed"]
    # Cancel: no save call. Nothing changed, and the output is still refused (API-4).
    assert client.get(f"{base}/output").status_code == 409
    assert path.read_bytes() == before
    assert client.post(f"{base}/save", json={"choice": "document_only"}).status_code == 200
    assert client.get(f"{base}/output").status_code == 200
    assert path.read_bytes() == before and store.history(tid) == [1]
    close(client, doc_id)


def test_a_value_used_as_a_name_is_refused(client, store):  # AR-7, DD-2.7
    doc_id, d = open_doc(client, layout_a(*A1))
    client.patch(f"/api/documents/{doc_id}/fields/{field(d, 'Date')['id']}",
                 json={"name": "Kim Example"})
    client.post(f"/api/documents/{doc_id}/verify")
    r = client.post(f"/api/documents/{doc_id}/save", json={
        "choice": "new", "document_type": "Vendor invoice", "region": "SG", "format": "Format A"})
    assert r.status_code == 409 and "Kim Example" not in r.text
    assert store.templates() == []
    close(client, doc_id)


def test_save_needs_type_and_format(client):  # FR-7.3, UX-3
    doc_id, _ = open_doc(client, layout_a(*A1))
    base = f"/api/documents/{doc_id}"
    client.post(f"{base}/verify")
    for body in ({"choice": "new", "format": "Format A"},
                 {"choice": "new", "document_type": "X", "format": ""},
                 {"choice": "new", "document_type": "X", "format": "F", "region": "sg"},
                 {"choice": "update", "template_id": "tpl_nope"}):
        assert client.post(f"{base}/save", json=body).status_code == 400, body
    close(client, doc_id)


def test_template_manager_routes(client, store):  # FR-7.9 to FR-7.11, UX-4
    tid_a = learn_a(client)
    tid_b = learn_a(client, fmt="Format B")
    groups = client.get("/api/templates").json()["groups"]
    assert groups[0]["document_type"] == "Vendor invoice"
    formats = groups[0]["regions"][0]["formats"]
    assert groups[0]["regions"][0]["region"] == "SG"
    assert [(f["format"], f["version"], f["fields"]) for f in formats] == \
        [("Format A", 1, 4), ("Format B", 1, 4)]
    shown = client.get(f"/api/templates/{tid_a}").json()
    assert shown["fields"][0]["anchor"]["printed_label"] == "Invoice no"

    r = client.patch(f"/api/templates/{tid_a}", json={"format": "Format B"})
    assert r.status_code == 409  # taken by the other template
    r = client.patch(f"/api/templates/{tid_a}", json={"format": "Acme 2025"})
    assert r.status_code == 200 and r.json()["template"]["format"]["id"] == "acme-2025"
    r = client.patch(f"/api/templates/{tid_b}", json={"document_type": "Supplier invoice"})
    assert r.status_code == 200
    names = {(t["template"]["document_type"], t["template"]["format"]["name"])
             for t in store.templates()}
    assert names == {("Supplier invoice", "Acme 2025"), ("Supplier invoice", "Format B")}
    assert [v["version"] for v in client.get(f"/api/templates/{tid_a}/history").json()
            ["versions"]] == [1, 2, 3]  # created, format renamed, type renamed
    assert client.delete(f"/api/templates/{tid_b}").status_code == 200
    assert client.get(f"/api/templates/{tid_b}").status_code == 404
    assert [t["template"]["id"] for t in store.templates()] == [tid_a]


GERMAN = docgen.pdf([[(60, 80, "Rechnungsnummer: RE-2026-0412"),
                      (60, 110, "Lieferant: Beispiel Bürobedarf GmbH"),
                      (60, 140, "Zahlungsbedingungen: sofort ohne Abzug")]])


def test_remember_translation_labels_only(client, store, nabu_home):  # FR-9.8, DD-4
    doc_id, d = open_doc(client, GERMAN, "rechnung.pdf")
    base = f"/api/documents/{doc_id}"
    sup = field(d, "Lieferant")
    assert sup["lang"] == "de" and sup["translation"]["name"] == "untranslated"
    r = client.patch(f"{base}/translations/{sup['id']}.value",
                     json={"english": "Sample Office Supplies Ltd", "remember": True})
    assert r.status_code == 400  # values are never remembered
    r = client.patch(f"{base}/translations/{sup['id']}.name",
                     json={"english": "Supplier", "remember": True})
    assert r.status_code == 200 and r.json()["name"] == "Supplier"
    entries = client.get("/api/translations").json()["entries"]
    assert [(e["term"], e["english"], e["lang"]) for e in entries] == [("Lieferant", "Supplier", "de")]
    assert "Beispiel" not in store_bytes(nabu_home).decode("utf-8")
    close(client, doc_id)

    doc_id, d = open_doc(client, GERMAN, "rechnung.pdf")
    sup = field(d, "Lieferant")
    assert sup["name"] == "Supplier" and sup["translation"]["name"] == "memory"
    close(client, doc_id)
    assert client.delete(f"/api/translations/{entries[0]['id']}").status_code == 200
    assert client.get("/api/translations").json()["entries"] == []
    assert client.delete("/api/translations/nope").status_code == 404


def test_text_files_link_on_labels_only(client, store):  # AD-15, DD-2.4
    def txt(inv, cust):
        return f"Invoice no: {inv}\nCustomer: {cust}\nTotal: 5.00 EUR\n".encode()

    doc_id, _ = open_doc(client, txt("INV-0042", "Kim Example"), "a.txt")
    save_new(client, doc_id, doc_type="Note", region="")
    close(client, doc_id)
    t = store.templates()[0]
    assert t["template"]["pages"] is None and t["template"]["region"] is None
    assert all(f["anchor"]["page"] is None and f["anchor"]["box"] is None for f in t["fields"])
    doc_id, d = open_doc(client, txt("INV-7781", "Lee Sample"), "b.txt")
    assert d["link"]["outcome"] == "linked"
    assert [f["value"] for f in d["fields"]] == ["INV-7781", "Lee Sample", "5.00 EUR"]
    close(client, doc_id)
    doc_id, d = open_doc(client, layout_a(*A1))  # a paginated file never links to it
    assert d["link"]["outcome"] == "none"
    close(client, doc_id)


def test_template_routes_need_the_token(client):  # API-1, API-6
    tid = learn_a(client)
    del client.headers["x-nabu-token"]
    for method, path in (("get", "/api/templates"), ("get", f"/api/templates/{tid}"),
                         ("delete", f"/api/templates/{tid}"),
                         ("get", f"/api/templates/{tid}/history"),
                         ("get", "/api/translations")):
        assert getattr(client, method)(path).status_code in (401, 403), path
