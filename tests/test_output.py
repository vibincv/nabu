"""FR-8 output JSON (DD-3): kept fields in list order, verified English value, original when it
differs, not-found nulls, untranslated terms, deterministic bytes, schema-valid."""

import json
from datetime import UTC, datetime
from importlib.resources import files

import jsonschema

from nabu.fields.types import Field, PageInfo, WorkingResult
from nabu.output import json_out

AT = datetime(2026, 10, 14, 9, 30, 5, tzinfo=UTC)


def schema():
    return json.loads(files("nabu.schemas").joinpath("output.schema.json").read_text())


def result(*fields):
    return WorkingResult(source_file="synthetic_invoice.pdf", pages=[PageInfo(1, 1000, 1414, "de")],
                         fields=list(fields))


def f(id, name, value, value_en=None, lang="de", **kw):
    return Field(id=id, name=name, printed_label=name, value=value, value_en=value_en,
                 value_type="text", page=1, source="discovery_rules", lang=lang, **kw)


def header(**over):
    h = {"document_type": "Invoice", "region": "DE", "format": None}
    h.update(over)
    return h


def test_fields_order_values_originals_and_not_found():
    wr = result(f("f1", "Invoice number", "RE-1", "RE-1"),
                f("f2", "Invoice date", "01.10.2026", "2026-10-01"),
                f("f3", "Due date", None, None, status=["not_found"]),
                f("f4", "Note", "Hinweis", "Note", removed=True))
    out = json_out.build(wr, header(), AT)
    assert out["fields"] == [{"name": "Invoice number", "value": "RE-1"},
                             {"name": "Invoice date", "value": "2026-10-01", "original": "01.10.2026"},
                             {"name": "Due date", "value": None}]
    assert out["not_found"] == ["Due date"]  # FR-8.3; the removed field is absent
    assert out["template_id"] is None and out["template_version"] is None
    assert out["verified_at"] == "2026-10-14T09:30:05Z"
    jsonschema.validate(out, schema())


def test_untranslated_terms_listed_once_with_language():
    a = f("f1", "Steuerschuldnerschaft", "x", "x", translation={"name": "untranslated"})
    b = f("f2", "Steuerschuldnerschaft (2)", "y", "y", translation={"name": "untranslated"})
    b.printed_label = "Steuerschuldnerschaft"
    c = f("f3", "Hinweis", "Lieferung frei Haus", "Lieferung frei Haus",
          translation={"name": "translated", "value": "untranslated"})
    out = json_out.build(result(a, b, c), header(), AT)
    assert out["untranslated_terms"] == [{"term": "Steuerschuldnerschaft", "lang": "de"},
                                         {"term": "Lieferung frei Haus", "lang": "de"}]
    jsonschema.validate(out, schema())


def test_document_only_with_empty_header_is_null():
    out = json_out.build(result(f("f1", "Name", "Kim", "Kim", lang="en")),
                         header(document_type=None, region=None), AT)
    assert out["document_type"] is None and out["region"] is None and out["format"] is None
    jsonschema.validate(out, schema())


def test_bytes_are_deterministic_apart_from_time():  # FR-8.6
    wr = result(f("f1", "Invoice number", "RE-1", "RE-1"), f("f2", "Total", "1,00 €", "1.00 EUR"))
    a = json_out.dumps(json_out.build(wr, header(), AT))
    b = json_out.dumps(json_out.build(wr, header(), AT))
    later = json_out.dumps(json_out.build(wr, header(), datetime(2027, 1, 1, tzinfo=UTC)))
    assert a == b
    assert a.replace(b"2026-10-14T09:30:05Z", b"T") == later.replace(b"2027-01-01T00:00:00Z", b"T")
    assert a.decode("utf-8").endswith("\n")


def test_download_name():  # FR-8.5
    assert json_out.file_name("scan.pdf") == "scan.pdf.nabu.json"
    assert json_out.file_name("front.jpg (+1 images)") == "front.jpg.nabu.json"
    assert json_out.file_name('a"b\\c.pdf') == "a_b_c.pdf.nabu.json"
