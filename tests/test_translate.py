"""FR-9 acceptance (b), (c), (d read path), plus FR-9.7 statuses and FR-9.10 no-model mode."""

import json

from stub_ollama import StubOllama

from nabu.config import Config
from nabu.fields.types import Field
from nabu.lang.memory import TranslationMemory
from nabu.lang.translate import translate_fields
from nabu.model.client import ModelClient


def field(label, value, vtype, lang="de"):
    return Field(id="", name=label, printed_label=label, value=value, value_type=vtype, page=1,
                 source="model", lang=lang)


def answers(*items):
    return json.dumps({"items": [{"id": str(i), "english": e, "status": s}
                                 for i, (e, s) in enumerate(items)]})


def test_value_rules_without_model():  # FR-9.6 + FR-9.10
    fs = [field("Name", "Jürgen Beispiel", "name"), field("Kundennr.", "KD-55821", "id"),
          field("Datum", "01.10.2026", "date"), field("Betrag", "1.428,00 €", "amount"),
          field("Hinweis", "Steuerschuldnerschaft", "text")]
    out = translate_fields(fs, TranslationMemory(), None, region="DE")
    assert out.model_calls == 0
    assert [x.value_en for x in fs] == ["Jürgen Beispiel", "KD-55821", "2026-10-01", "1428.00 EUR",
                                        "Steuerschuldnerschaft"]
    assert [x.translation["value"] for x in fs] == ["not_needed"] * 4 + ["untranslated"]
    assert all(x.translation["name"] == "untranslated" and "not_translated" in x.status for x in fs)
    assert [x.name for x in fs] == [x.printed_label for x in fs]  # originals kept (FR-9.4)


def test_ambiguous_date_keeps_printed_form():
    fs = [field("Date", "01/02/2026", "date", lang="en")]
    translate_fields(fs, TranslationMemory(), None, region=None)
    assert fs[0].value_en == "01/02/2026" and "needs_review" in fs[0].status


def test_no_region_day_first_language_resolves_date():
    fs = [field("Datum", "01/02/2026", "date")]
    translate_fields(fs, TranslationMemory(), None, region=None)
    assert fs[0].value_en == "2026-02-01" and "needs_review" not in fs[0].status


def test_memory_first_then_model_and_unchanged_is_untranslated():
    memory = TranslationMemory({"entries": [{"id": "t1", "lang": "de", "term": "Rechnungsnr.",
                                             "english": "Invoice number"}]})
    fs = [field("Rechnungsnr.", "RE-1", "id"), field("Hinweis", "Bitte zahlen", "text"),
          field("Lieferant", "Beispiel GmbH", "text"), field("Fällig am", "15.10.2026", "date")]
    with StubOllama() as stub:
        # items in order: Hinweis(name), Hinweis(value), Lieferant(name), Lieferant(value), Fällig am(name)
        stub.responses.append(answers(("Note", "translated"), ("Please pay", "translated"),
                                      ("Supplier", "low_confidence"), ("Example Ltd", "not_needed"),
                                      ("Fällig am", "translated")))
        client = ModelClient(Config(model="stub-vl:test", model_endpoint=stub.url))
        out = translate_fields(fs, memory, client, region="DE")
        sent = [c for c in stub.calls if c[0] == "POST"]
    assert out.model_calls == 1 and len(sent) == 1  # one call per page and language
    assert "Rechnungsnr." not in sent[0][2]["messages"][1]["content"]  # memory, no model (FR-9 d)
    assert (fs[0].name, fs[0].translation["name"]) == ("Invoice number", "memory")
    assert (fs[1].name, fs[1].value_en) == ("Note", "Please pay")
    assert fs[2].name == "Supplier" and "needs_review" in fs[2].status  # low confidence
    assert fs[2].value_en == "Beispiel GmbH"  # a name is never rewritten, whatever the model says
    assert fs[2].translation["value"] == "not_needed"
    # returned unchanged -> untranslated, original kept, flagged (FR-9 c)
    assert (fs[3].name, fs[3].translation["name"]) == ("Fällig am", "untranslated")
    assert "not_translated" in fs[3].status
    assert fs[3].value_en == "2026-10-15"


def test_english_needs_nothing():
    fs = [field("Total", "Paid in full", "text", lang="en")]
    with StubOllama() as stub:
        client = ModelClient(Config(model="stub-vl:test", model_endpoint=stub.url))
        out = translate_fields(fs, TranslationMemory(), client, region=None)
        assert not [c for c in stub.calls if c[0] == "POST"]
    assert out.model_calls == 0 and fs[0].translation == {"name": "not_needed", "value": "not_needed"}
