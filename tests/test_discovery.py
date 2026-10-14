"""FR-4 discovery rules (digital, no model), grounding on OCR words (AD-2), duplicates (FR-4.6)."""

from nabu import discovery
from nabu.discovery import rules
from nabu.extract.text import row_line, text_line
from nabu.fields.grounding import find_run, ground
from nabu.fields.types import Field
from nabu.ocr.words import FormField, Line, Page, Word


def words(*items):  # (text, x0, x1) on one line at y 100-110
    return tuple(Word(text=t, box=(a, 100, b, 110)) for t, a, b in items)


def pairs(lines, form=()):
    return [(p.label, p.value) for p in rules.discover([Page(n=1, source="document", lines=lines)],
                                                       list(form))]


def test_label_colon_value_lines():
    assert pairs([text_line("Invoice no: INV-1"), text_line("Date: 01.10.2026"),
                  text_line("Meeting at 12:30 today"), text_line("Note:")]) == [
        ("Invoice no", "INV-1"), ("Date", "01.10.2026"), ("Note", None)]  # FR-4.5 empty kept


def test_glued_colon_and_fullwidth_colon():
    assert pairs([text_line("Ref:A-77"), text_line("성명： 홍길동")]) == [("Ref", "A-77"), ("성명", "홍길동")]


def test_two_column_layout_by_gap():
    line = Line(words=words(("Invoice", 50, 110), ("no", 115, 135), ("INV-1", 400, 460)))
    p = rules.discover([Page(n=1, source="text_layer", lines=[line])], [])
    assert [(x.label, x.value, x.box) for x in p] == [("Invoice no", "INV-1", (400, 100, 460, 110))]


def test_several_pairs_on_one_line():
    line = Line(words=words(("Date:", 50, 100), ("01.10.2026", 110, 200),
                            ("Customer:", 500, 590), ("KD-1", 600, 650)))
    assert [(x.label, x.value) for x in rules.discover(
        [Page(n=1, source="text_layer", lines=[line])], [])] == [("Date", "01.10.2026"), ("Customer", "KD-1")]


def test_label_then_value_segment():
    line = Line(words=words(("Total:", 50, 110), ("1.428,00", 400, 470), ("EUR", 475, 500)))
    assert [(x.label, x.value) for x in rules.discover(
        [Page(n=1, source="text_layer", lines=[line])], [])] == [("Total", "1.428,00 EUR")]


def test_tables():
    lines = [row_line(["Customer", "ACME"]), row_line(["Total", "5 EUR"]),
             row_line(["Item", "Qty", "Price"]), row_line(["Pen", "2", "1.00"]),
             row_line(["Ink", "1", "9.00"])]
    assert pairs(lines) == [("Customer", "ACME"), ("Total", "5 EUR"), ("Item", "Pen"), ("Qty", "2"),
                            ("Price", "1.00"), ("Item", "Ink"), ("Qty", "1"), ("Price", "9.00")]


def test_numbers_and_sentences_are_not_labels():
    sentence = text_line("This is a long sentence that goes on and on: yes")
    assert pairs([row_line(["2026", "5"]), sentence]) == []


def test_form_fields():
    assert pairs([], [FormField(label="Customer", value="ACME"), FormField(label="Signed", value=None)]) \
        == [("Customer", "ACME"), ("Signed", None)]


def f(label, value, page=1):
    return Field(id="", name=label, printed_label=label, value=value, value_type="text", page=page,
                 source="model")


def test_duplicates_merged_and_repeats_numbered():
    fields = discovery.merge([f("Item", "Pen"), f("Item", "Pen"), f("Item", "Ink"),
                              f("RECHNUNG", "RECHNUNG"), f("Total", "5")])
    assert [(x.name, x.value) for x in fields] == [("Item", "Pen"), ("Item", "Ink"), ("Total", "5")]
    assert [x.name for x in discovery.number(fields)] == ["Item 1", "Item 2", "Total"]


def test_grounding_uses_ocr_words():
    page = Page(n=1, source="ocr", lines=[Line(words=(
        Word("Total:", (50, 100, 100, 110)), Word("1.428,00", (400, 100, 470, 110)),
        Word("EUR", (475, 100, 500, 110))))])
    g = ground("1.428,00 EUR", page, model_box=None)
    assert (g.box, g.box_source, g.exact) == ((400, 100, 500, 110), "ocr", True)
    g = ground("1.428,06 EUR", page, model_box=None)  # one character off: near match, not exact
    assert g.box_source == "ocr" and not g.exact
    g = ground("missing", page, model_box=(1, 2, 3, 4))
    assert (g.box, g.box_source) == ((1, 2, 3, 4), "model")
    assert ground("missing", page, None).box is None


def test_grounding_prefers_the_run_near_the_model_box():
    page = Page(n=1, source="ocr", lines=[Line(words=(Word("5", (10, 10, 20, 20)),)),
                                          Line(words=(Word("5", (10, 800, 20, 810)),))])
    assert find_run("5", page.words, near=(0, 790, 30, 820))[0] == (10, 800, 20, 810)
