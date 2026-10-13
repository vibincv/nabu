import json
import os
import stat

import pytest

from nabu.errors import NabuError, ValueWriteRefused
from nabu.store.paths import default_paths
from nabu.store.store import Store


def template(name="Invoice Number", label="Rechnungsnr.", version=1, region="DE"):
    return {
        "schema_version": "1.0",
        "template": {
            "id": "tpl_vendor_invoice_DE_acme-2025", "document_type": "Vendor invoice",
            "document_type_key": "vendor_invoice", "region": region,
            "format": {"id": "acme-2025", "name": "Acme 2025 format"}, "version": version,
        },
        "fields": [{"order": 1, "name": name, "key": "invoice_number", "value_type": "id",
                    "anchor": {"printed_label": label, "page": 1, "box": [590, 88, 650, 110],
                               "value_offset": [70, 0, 252, 22], "tolerance": 0.03}}],
        "removed_labels": [],
    }


@pytest.fixture
def store(nabu_home):
    return Store(default_paths())


@pytest.fixture
def session(store):
    s = store.new_session()
    for v in ["RE-2026-0412", "Beispiel Bürobedarf GmbH", "01.10.2026", "DE"]:
        s.register_value(v)
    return s


def test_clean_template_saves(store, session):
    p = store.save_template(template(), session)
    assert p.exists()
    assert json.loads(p.read_text())["fields"][0]["name"] == "Invoice Number"


@pytest.mark.parametrize("name,label", [
    ("RE-2026-0412", "Rechnungsnr."),             # value as a field name
    ("Invoice Number", "re-2026-0412"),            # value as a label, different case
    ("Invoice Number", "Lieferant Beispiel  Bürobedarf GmbH"),  # value inside a label
])
def test_value_in_template_refused(store, session, name, label):
    with pytest.raises(ValueWriteRefused) as e:
        store.save_template(template(name, label), session)
    # the refusal message must not contain the value
    assert "re-2026-0412" not in e.value.message.lower()
    assert not store.paths.templates_dir.exists() or not any(store.paths.templates_dir.rglob("*.json"))


def test_short_values_do_not_block_ordinary_labels(store, session):
    # "DE" is a session value but is also the region code; short values only match exactly
    store.save_template(template(label="Datum der Lieferung"), session)


def test_template_without_session_refused(store):
    with pytest.raises(NabuError):
        store.save_template(template(), None)


def test_versions_kept_and_history(store, session):
    store.save_template(template(version=1), session)
    store.save_template(template(name="Invoice No.", version=2), session)
    assert store.history("tpl_vendor_invoice_DE_acme-2025") == [1, 2]


def test_path_traversal_rejected(store, session):
    t = template()
    t["template"]["document_type_key"] = "../../etc"
    with pytest.raises(NabuError):
        store.save_template(t, session)


def test_no_region_stored_under_none(store, session):
    p = store.save_template(template(region=None), session)
    assert p.parent.name == "_none"


def test_translation_memory_refuses_values(store, session):
    store.remember_translation({"id": "t1", "lang": "de", "term": "Rechnungsnr.",
                                "english": "Invoice number"}, session)
    with pytest.raises(ValueWriteRefused):
        store.remember_translation({"id": "t2", "lang": "de", "term": "Beispiel Bürobedarf GmbH",
                                    "english": "Example Office Supplies Ltd"}, session)
    assert len(store.translations()["entries"]) == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_permissions_user_only(store, session):
    p = store.save_template(template(), session)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700


def test_forget_reports_what_was_removed(store, session):
    store.save_template(template(), session)
    removed = store.forget("all")
    assert any(r.endswith("acme-2025.json") for r in removed)
    assert store.templates() == []


def test_session_close_releases_data(store):
    s = store.new_session()
    s.upload = b"%PDF-1.7 ..."
    s.page_images[1] = b"\x89PNG..."
    s.register_value("RE-2026-0412")
    store.end_session(s)
    assert s.upload is None and not s.page_images and not s.values()
    assert "PDF" not in repr(s)


@pytest.mark.parametrize("label", [
    "Ref. RE 2026 0412",        # punctuation replaced by spaces
    "RE20260412",               # punctuation dropped
    "Datum 01/10/2026",         # date separators changed
    "beispiel burobedarf gmbh",  # accents dropped
])
def test_value_with_changed_punctuation_or_accents_refused(store, session, label):
    with pytest.raises(ValueWriteRefused):
        store.save_template(template(label=label), session)


def test_value_in_format_slug_refused(store, session):
    t = template()
    t["template"]["format"]["id"] = "beispiel-burobedarf-gmbh"
    with pytest.raises(ValueWriteRefused) as e:
        store.save_template(t, session)
    assert "id" in e.value.message


def test_value_in_field_key_refused(store, session):
    t = template()
    t["fields"][0]["key"] = "re_2026_0412"
    with pytest.raises(ValueWriteRefused):
        store.save_template(t, session)


@pytest.mark.parametrize("key,text", [
    ("lang", "Beispiel Bürobedarf GmbH"),
    ("status", "RE-2026-0412"),
    ("created_at", "RE-2026-0412"),
])
def test_fixed_shape_key_with_free_text_is_checked(store, session, key, text):
    with pytest.raises(ValueWriteRefused):
        store.remember_translation({"id": "t1", "lang": "de", "term": "Rechnungsnr.",
                                    "english": "Invoice number", key: text}, session)


def test_timestamp_containing_a_date_value_is_allowed(store, session):
    # A timestamp has a fixed shape; a document dated the same day must not block the save.
    session.register_value("2026-10-01")
    t = template()
    t["template"]["created_at"] = "2026-10-01T09:00:00Z"
    store.save_template(t, session)


def test_other_template_on_same_path_refused(store, session):
    store.save_template(template(version=1), session)
    other = template(version=2)
    other["template"]["id"] = "tpl_someone_else"
    with pytest.raises(NabuError, match="already uses"):
        store.save_template(other, session)


@pytest.mark.parametrize("version", [1, 0, "2"])
def test_version_must_increase(store, session, version):
    store.save_template(template(version=1), session)
    with pytest.raises(NabuError, match="version"):
        store.save_template(template(version=version), session)


def test_damaged_template_is_named_not_shown(store, session):
    p = store.save_template(template(), session)
    p.write_text("{ RE-2026-0412 broken", encoding="utf-8")
    with pytest.raises(NabuError) as e:
        store.templates()
    assert p.name in e.value.message and "RE-2026" not in e.value.message


def test_damaged_translation_memory_is_named(store, session):
    store.paths.translations_file.parent.mkdir(parents=True, exist_ok=True)
    store.paths.translations_file.write_text("[1, 2", encoding="utf-8")
    with pytest.raises(NabuError, match="translation memory is damaged"):
        store.translations()


def test_config_saved_only_when_valid(store):
    store.save_config({"model": "qwen3.5:4b"})
    assert store.config_data() == {"model": "qwen3.5:4b"}
    with pytest.raises(NabuError):
        store.save_config({"model_endpoint": "http://10.0.0.5:11434"})
    assert store.config_data() == {"model": "qwen3.5:4b"}
