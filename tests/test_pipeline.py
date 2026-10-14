"""End-to-end reading (M1): FR-3.4 no-model mode, FR-3.5 invalid answers, FR-4.3 one discovery call
per scanned page, AD-2 boxes from OCR, AR-7 values registered, NFR-5 determinism, cancel."""

import json
import logging

import docgen
import pytest
from stub_ollama import StubOllama

from nabu import pipeline
from nabu.config import Config
from nabu.errors import ValueWriteRefused
from nabu.lang.memory import TranslationMemory
from nabu.model.client import ModelClient
from nabu.ocr.engine import OcrResult
from nabu.ocr.words import Line, Word
from nabu.router import Upload
from nabu.session import Session
from nabu.store.store import Store

pytest.importorskip("PIL")

SECRET = "INV-0042"


class FakeOcr:
    """Returns the same two lines for every page; counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def read(self, page):
        self.calls += 1
        return OcrResult(lines=[
            Line(words=(Word("Invoice", (80, 100, 160, 115)), Word("no:", (165, 100, 200, 115)),
                        Word(SECRET, (450, 100, 560, 115)))),
            Line(words=(Word("Total:", (80, 140, 150, 155)), Word("12.50", (450, 140, 510, 155)),
                        Word("EUR", (515, 140, 560, 155))))], notes=[])


def discovery_answer(**over):
    body = {"type_guess": "Invoice", "country_guess": "IE", "fields": [
        {"label": "Invoice no:", "value": SECRET, "value_type": "id", "bbox": None, "confidence": 0.95},
        {"label": "Total", "value": "12.50 EUR", "value_type": "amount", "bbox": None, "confidence": 0.9},
        {"label": "Due", "value": "2099-01-01", "value_type": "date", "bbox": None, "confidence": 0.9},
        {"label": "INVOICE", "value": "INVOICE", "value_type": "text", "bbox": None, "confidence": 0.9},
    ]}
    body.update(over)
    return json.dumps(body)


def readers(stub=None, ocr=None):
    model = ModelClient(Config(model="stub-vl:test", model_endpoint=stub.url)) if stub else None
    return pipeline.Readers(ocr=ocr, model=model, memory=TranslationMemory())


def scan_uploads(n=1):
    return [Upload(f"p{i}.png", docgen.page_image([("Invoice no:", SECRET)])) for i in range(n)]


def posts(stub):
    return [c for c in stub.calls if c[0] == "POST"]


def test_scan_one_discovery_call_per_page_and_ocr_boxes():
    ocr = FakeOcr()
    with StubOllama() as stub:
        stub.responses.extend([discovery_answer(), discovery_answer()])
        r = pipeline.run(scan_uploads(2), Config(), Session(), readers(stub, ocr))
        assert len(posts(stub)) == 2  # English page: no translation call needed
    assert ocr.calls == 2 and r.model_used and r.route == "raster"
    d = r.to_dict()
    assert d["header"] == {"document_type": "Invoice", "region": "IE", "format": None}
    by_name = {f["name"]: f for f in d["fields"]}
    assert set(by_name) == {"Invoice no", "Total", "Due"}  # the echoed title is dropped
    inv = by_name["Invoice no"]
    assert (inv["box"], inv["box_source"], inv["source"]) == ((450, 100, 560, 115), "ocr", "model")
    assert "needs_review" not in inv["status"]
    assert by_name["Total"]["value_en"] == "12.50 EUR"
    due = by_name["Due"]  # not printed on the page: never trusted silently (FR-4.5)
    assert due["box"] is None and "needs_review" in due["status"]
    assert [f["id"] for f in d["fields"]] == ["f1", "f2", "f3"]  # page 2 duplicates merged


def test_scan_without_model_shows_text_and_says_why():  # FR-3.4
    r = pipeline.run(scan_uploads(), Config(), Session(), readers(None, FakeOcr()))
    assert r.fields == [] and not r.model_used
    assert r.pages[0].messages == [pipeline.NEEDS_MODEL]
    assert SECRET in r.pages[0].text


def test_invalid_answer_marks_the_page_and_keeps_text():  # FR-3.5
    with StubOllama() as stub:
        stub.responses.extend(["not json", "still not json"])
        r = pipeline.run(scan_uploads(), Config(), Session(), readers(stub, FakeOcr()))
        assert len(posts(stub)) == 2  # one repair
    assert r.fields == [] and "could not read fields" in r.pages[0].messages[0]
    assert SECRET in r.pages[0].text


def test_model_down_falls_back_with_the_fix():
    with StubOllama() as stub:
        url = stub.url
    rd = pipeline.Readers(ocr=FakeOcr(), memory=TranslationMemory(),
                          model=ModelClient(Config(model="stub-vl:test", model_endpoint=url,
                                                   model_timeout_s=2)))
    r = pipeline.run(scan_uploads(2), Config(), Session(), rd)
    assert r.fields == [] and r.messages and "ollama" in r.messages[0].lower()
    assert [p.messages for p in r.pages] == [[pipeline.NEEDS_MODEL], [pipeline.NEEDS_MODEL]]


def test_digital_file_needs_no_model():
    pytest.importorskip("pdfplumber")
    pdf = docgen.pdf([[(60, 80, "Invoice no: INV-0042"), (60, 110, "Total: 12.50 EUR")]])
    with StubOllama() as stub:
        r = pipeline.run([Upload("a.pdf", pdf)], Config(), Session(), readers(stub, None))
        assert posts(stub) == []
    assert [(f.name, f.value, f.box_source, f.source) for f in r.fields] == [
        ("Invoice no", SECRET, "text_layer", "discovery_rules"),
        ("Total", "12.50 EUR", "text_layer", "discovery_rules")]
    assert not r.model_used


def test_values_are_registered_so_the_store_refuses_them(nabu_home):
    session = Session()
    pipeline.run([Upload("a.txt", f"Invoice no: {SECRET}\n".encode())], Config(), session,
                 readers())
    assert session.working_result["fields"][0]["value"] == SECRET
    with pytest.raises(ValueWriteRefused):
        Store().save_template({"template": {"id": "t", "version": 1, "document_type": "x",
                                            "region": None, "format": {"name": SECRET}},
                               "fields": []}, session)


def test_no_values_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    with StubOllama() as stub:
        stub.responses.extend(["bad", "bad"])
        pipeline.run(scan_uploads(), Config(), Session(), readers(stub, FakeOcr()))
    assert SECRET not in caplog.text


def test_repr_never_shows_values():
    r = pipeline.run([Upload("a.txt", f"Invoice no: {SECRET}\n".encode())], Config(), Session(),
                     readers())
    assert SECRET not in repr(r) and SECRET not in repr(r.fields) and SECRET not in repr(r.pages)


def test_deterministic():  # NFR-5
    data = f"Invoice no: {SECRET}\nItem: Pen\nItem: Ink\n".encode()
    a = pipeline.run([Upload("a.txt", data)], Config(), Session(), readers()).to_dict()
    b = pipeline.run([Upload("a.txt", data)], Config(), Session(), readers()).to_dict()
    assert a == b and [f["name"] for f in a["fields"]] == ["Invoice no", "Item 1", "Item 2"]


def test_progress_and_cancel():
    seen = []
    pipeline.run(scan_uploads(2), Config(), Session(), readers(None, FakeOcr()),
                 progress=lambda done, total, stage: seen.append((done, total, stage)))
    assert seen == [(1, 2, "reading"), (2, 2, "reading"), (0, 1, "translating"), (1, 1, "translating")]
    with pytest.raises(pipeline.Cancelled):
        pipeline.run(scan_uploads(2), Config(), Session(), readers(None, FakeOcr()),
                     cancelled=lambda: True)


def test_session_keeps_page_images_in_memory():
    s = Session()
    pipeline.run(scan_uploads(2), Config(), s, readers(None, FakeOcr()))
    assert sorted(s.page_images) == [1, 2] and all(v.startswith(b"\x89PNG") for v in s.page_images.values())
