"""Linking and template reading on scans (FR-5.1, FR-5.2, FR-5.5, FR-5.9), with a fake OCR and the
stub model so model calls can be counted."""

import json

import docgen
import pytest
from stub_ollama import StubOllama

from nabu import pipeline
from nabu.config import Config
from nabu.lang.memory import TranslationMemory
from nabu.model.client import ModelClient
from nabu.ocr.engine import OcrResult
from nabu.ocr.words import Line, Page, Reading, Word
from nabu.router import Upload
from nabu.session import Session
from nabu.templates import fold, label_matches
from nabu.templates.link import link, score

pytest.importorskip("PIL")

CFG = Config()


class FakeOcr:
    """'Ref no:' and 'Amount:' with values, on every page; `drop_amount` leaves the amount out."""

    def __init__(self, ref="R-1001", amount="40.00 EUR", drop_amount=False, shift=0):
        self.ref, self.amount, self.drop, self.shift = ref, amount, drop_amount, shift

    def read(self, page):
        s = self.shift
        lines = [Line(words=(Word("Ref", (80, 100 + s, 130, 115 + s)),
                             Word("no:", (135, 100 + s, 170, 115 + s)),
                             Word(self.ref, (450, 100 + s, 560, 115 + s))))]
        if not self.drop:
            lines.append(Line(words=(Word("Amount:", (80, 140 + s, 170, 155 + s)),
                                     Word(self.amount, (450, 140 + s, 560, 155 + s)))))
        return OcrResult(lines=lines, notes=[])


def template(pages=1, aspect=0.71):
    def tf(order, name, key, label, box, offset, vt):
        return {"order": order, "name": name, "key": key, "value_type": vt,
                "anchor": {"printed_label": label, "page": 1, "box": box,
                           "value_offset": offset, "tolerance": 0.03}}
    return {"schema_version": "1.0",
            "template": {"id": "tpl_receipt_none_format-a", "document_type": "Receipt",
                         "document_type_key": "receipt", "region": None,
                         "format": {"id": "format-a", "name": "Format A"}, "version": 1,
                         "pages": [{"aspect": aspect}] * pages},
            "fields": [tf(1, "Reference", "reference", "Ref no", [80, 100, 170, 115],
                          [370, 0, 480, 15], "id"),
                       tf(2, "Amount Paid", "amount_paid", "Amount", [80, 140, 170, 155],
                          [370, 0, 480, 15], "amount")],
            "removed_labels": []}


def scan(n=1):
    return [Upload(f"p{i}.png", docgen.page_image([("x", "y")])) for i in range(n)]


def readers(ocr, stub=None):
    model = ModelClient(Config(model="stub-vl:test", model_endpoint=stub.url)) if stub else None
    return pipeline.Readers(ocr=ocr, model=model, memory=TranslationMemory())


def posts(stub):
    return [c for c in stub.calls if c[0] == "POST"]


def test_linked_scan_makes_no_model_call():  # FR-5 (e), FR-5.5
    with StubOllama() as stub:
        r = pipeline.run(scan(), CFG, Session(), readers(FakeOcr(), stub), templates=[template()])
        assert posts(stub) == []
    assert r.link["outcome"] == "linked" and r.link["score"] == 1.0
    assert [(f.name, f.value, f.value_en, f.box_source) for f in r.fields] == [
        ("Reference", "R-1001", "R-1001", "ocr"), ("Amount Paid", "40.00 EUR", "40.00 EUR", "ocr")]


def test_shifted_scan_still_links_and_reads():  # DD-2.3: offsets are relative to the label
    r = pipeline.run(scan(), CFG, Session(), readers(FakeOcr(shift=20)), templates=[template()])
    assert r.link["outcome"] == "linked"  # 20 grid units is inside the 0.03 tolerance
    assert [f.value for f in r.fields] == ["R-1001", "40.00 EUR"]


def test_failed_field_crop_reread_once():  # FR-5.9, AD-6
    with StubOllama() as stub:
        stub.responses.append(json.dumps({"value": "40.00 EUR", "bbox": None, "confidence": 0.9}))
        cfg = Config(link_threshold=0.5)  # 1 of 2 anchors found: linked for this test
        r = pipeline.run(scan(), cfg, Session(), readers(FakeOcr(drop_amount=True), stub),
                         templates=[template()])
        assert r.link["outcome"] == "linked" and len(posts(stub)) == 1  # one crop, not a page discovery
    amount = r.fields[1]
    assert amount.source == "model_reread" and amount.value == "40.00 EUR"
    assert "not_found" not in amount.status and r.model_used


def test_failed_field_without_model_needs_review():  # FR-5.9 "otherwise"
    r = pipeline.run(scan(), CFG, Session(), readers(FakeOcr(drop_amount=True)),
                     templates=[template()])
    assert r.link["outcome"] == "similar"  # 1 of 2 anchors: below the link threshold
    t = template()
    t["fields"].append({**t["fields"][0], "order": 3, "key": "ref2", "name": "Ref copy"})
    r = pipeline.relink(_held(), CFG, readers(FakeOcr(drop_amount=True)), t)
    assert {"not_found", "needs_review"} <= set(r.fields[1].status)


def _held():
    s = Session()
    pipeline.run(scan(), CFG, s, readers(FakeOcr(drop_amount=True)))
    return s


def test_page_rules():  # FR-5.2
    two = template(pages=2)
    r = pipeline.read_document(scan(), CFG, FakeOcr())
    s = score(r, two, CFG)
    assert s.value == 1.0 and s.missing_pages == [2]  # front only: scored on pages present
    out = pipeline.run(scan(), CFG, Session(), readers(FakeOcr()), templates=[two])
    assert out.link["outcome"] == "linked" and out.link["missing_pages"] == [2]
    assert "page 2 is missing" in out.messages[0]
    assert score(pipeline.read_document(scan(2), CFG, FakeOcr()), template(), CFG).value == 0
    assert score(r, template(aspect=1.41), CFG).value == 0  # landscape template, portrait page


def test_ocr_confusions_and_outcomes():  # FR-5.2 tolerance, FR-5.4 outcomes
    assert fold("INV0ICE N0.") == fold("Invoice No") and label_matches("Tota1", "Total")
    page = Page(n=1, source="ocr", width_px=1240, height_px=1754,
                lines=[Line(words=(Word("Ref", (80, 100, 130, 115)), Word("n0:", (135, 100, 170, 115)),
                                   Word("Amount:", (80, 140, 170, 155))))])
    reading = Reading("x.png", "raster", [page])
    assert link(reading, [template()], CFG).outcome == "linked"
    assert link(reading, [], CFG).outcome == "none"
    b = template()
    b["template"]["id"] = "tpl_b"
    lk = link(reading, [template(), b], CFG)
    assert lk.outcome == "ambiguous" and len(lk.candidates) == 2
