"""FR-3.1 reading of digital files without the model; FR-2.3 page by page; FR-2.6 named errors."""

import docgen
import pytest

from nabu.config import Config
from nabu.errors import UnreadableInput
from nabu.extract import text as text_files
from nabu.pipeline import read_document
from nabu.router import Upload

CFG = Config()


def read(name, data, ocr=None):
    return read_document([Upload(name, data)], CFG, ocr)


def test_text_formats():
    assert read("a.txt", b"Invoice no: A-1\n\nTotal: 5 EUR\n").pages[0].text == \
        "Invoice no: A-1\nTotal: 5 EUR"
    r = read("a.csv", b"Name,Qty\nPen,2\n")
    assert [line.cells for line in r.pages[0].lines] == [("Name", "Qty"), ("Pen", "2")]
    assert read("a.tsv", b"Name\tPen\n").pages[0].lines[0].cells == ("Name", "Pen")
    r = read("a.json", b'{"customer": {"name": "ACME"}, "items": [1, true], "x": null}')
    assert [line.cells for line in r.pages[0].lines] == [
        ("customer name", "ACME"), ("items 1", "1"), ("items 2", "true"), ("x", "")]
    assert read("a.md", b"# Title\nOwner: Kim").route == "text"


def test_utf16_and_bom():
    assert read("a.txt", "﻿Name: Jürgen".encode()).pages[0].text == "Name: Jürgen"
    assert read("a.txt", "Name: 홍길동".encode("utf-16")).pages[0].text == "Name: 홍길동"


def test_not_utf8_is_named_not_garbled():
    with pytest.raises(UnreadableInput, match="not UTF-8"):
        read("a.txt", "Name: Jürgen".encode("cp1252"))


def test_invalid_json_named():
    with pytest.raises(UnreadableInput, match="not valid JSON"):
        read("a.json", b"{nope")


def test_html_and_rtf_best_effort():
    r = read("a.html", b"<html><head><script>x=1</script></head><body><p>Owner: Kim</p>"
                       b"<table><tr><td>Total</td><td>5</td></tr></table></body></html>")
    assert r.pages[0].text == "Owner: Kim\nTotal\t5"
    rtf = (b"{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}{\\*\\generator x;}"
           b"Owner: J\\'fcrgen\\par Name: \\u-10675?\\u44600?\\par}")  # 홍 above 32767 is negative
    assert text_files._rtf_text(rtf.decode()).split("\n")[:2] == ["Owner: Jürgen", "Name: 홍길"]


def test_docx_xlsx_pptx():
    pytest.importorskip("docx")
    r = read("a.docx", docgen.docx(["Invoice no: INV-1"], [["Customer", "ACME"]]))
    assert r.route == "office" and r.pages[0].text == "Invoice no: INV-1\nCustomer\tACME"
    assert all(w.box is None for w in r.pages[0].words)  # no positions (AD-15)
    r = read("a.xlsx", docgen.xlsx({"One": [["Name", "Qty"], ["Pen", 2]], "Two": [["A", 1.5]]}))
    assert [p.text for p in r.pages] == ["Name\tQty\nPen\t2", "A\t1.5"]
    r = read("a.pptx", docgen.pptx([["Title", "Owner: Kim"], ["Second"]]))
    assert [p.text for p in r.pages] == ["Title\nOwner: Kim", "Second"]


def test_corrupt_docx_named():
    pytest.importorskip("docx")
    data = bytearray(docgen.docx(["x"]))
    data[len(data) // 2: len(data) // 2 + 200] = b"\0" * 200
    with pytest.raises(UnreadableInput, match="a.docx is damaged"):
        read("a.docx", bytes(data))


def test_pdf_text_layer_with_boxes_and_form_fields():
    pytest.importorskip("pdfplumber")
    pdf = docgen.pdf([[(60, 140, "Invoice no:"), (220, 140, "INV-0042")]],
                     form=[("Customer", "ACME", 0, (300, 600, 450, 620))])
    r = read("a.pdf", pdf)
    page = r.pages[0]
    assert r.route == "digital_pdf" and page.source == "text_layer"
    assert page.text == "Invoice no: INV-0042"
    assert all(w.box is not None for w in page.words)
    assert page.image is not None  # rendered for the review window, in memory
    f = r.form_fields[0]
    assert (f.label, f.value, f.page) == ("Customer", "ACME", 1)
    assert f.box == (504, 264, 756, 287)


def test_pdf_mixed_pages_and_no_ocr_message():
    pytest.importorskip("pdfplumber")
    scan = docgen.page_image([("Owner:", "Kim")], fmt="JPEG")
    r = read("a.pdf", docgen.pdf([[(60, 80, "A page with a real text layer")], scan]))
    assert [p.source for p in r.pages] == ["text_layer", "ocr"]  # FR-2.3
    assert "no OCR engine" in r.pages[1].notes[0]


def test_encrypted_and_corrupt_pdf_named():
    pytest.importorskip("pypdfium2")
    with pytest.raises(UnreadableInput) as e:
        read("locked.pdf", docgen.pdf([[(60, 80, "x")]], encrypted=True))
    assert e.value.message == "locked.pdf is password-protected; remove the password and upload it again"
    with pytest.raises(UnreadableInput, match="broken.pdf is damaged"):
        read("broken.pdf", b"%PDF-1.4\nthis is not a pdf")


def test_images_combine_in_upload_order():
    pytest.importorskip("PIL")
    front = docgen.page_image([("Front:", "A")])
    back = docgen.page_image([("Back:", "B")], fmt="JPEG")
    r = read_document([Upload("front.png", front), Upload("back.jpg", back)], CFG, None)
    assert r.route == "raster" and [p.n for p in r.pages] == [1, 2]
    assert [p.image.page for p in r.pages] == [1, 2]


def test_corrupt_image_named():
    pytest.importorskip("PIL")
    with pytest.raises(UnreadableInput, match="bad.png is damaged"):
        read("bad.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
