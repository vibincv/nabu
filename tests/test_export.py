"""Export folder (config `export_dir`, M3.2 2026-10-21): the confirmed output of each saved
document is written there for another service to read.

This is the one place a document value may reach disk (AR-7 exception, owner decision
2026-10-21). It is off unless configured, written only on Save after Verify, and the folder may
not overlap the store, so templates, translations and logs stay value-free.
"""

import json
import logging
import re

import pytest
from test_templates_api import A1, client, close, layout_a, open_doc  # noqa: F401 (fixture)

from nabu.config import Config, parse_config
from nabu.errors import ConfigError
from nabu.store.paths import default_paths
from nabu.store.store import Store

NAME = re.compile(r"^a1\.pdf\.\d{8}T\d{6}Z\.[A-Za-z0-9_-]{8}\.nabu\.json$")


@pytest.fixture
def export_dir(tmp_path):
    return tmp_path / "outbox"


@pytest.fixture
def store(nabu_home, export_dir):  # used by the imported `client` fixture
    return Store(default_paths().configured(Config(export_dir=str(export_dir))))


def verified(c, name="a1.pdf"):
    doc_id, _ = open_doc(c, layout_a(*A1), name)
    assert c.post(f"/api/documents/{doc_id}/verify").status_code == 200
    return doc_id


def test_document_only_save_exports_the_output(client, export_dir):  # noqa: F811
    doc_id = verified(client)
    r = client.post(f"/api/documents/{doc_id}/save", json={"choice": "document_only"}).json()
    files = list(export_dir.iterdir())
    assert len(files) == 1 and NAME.match(files[0].name)  # no temp file left behind
    assert r["exported"] == str(files[0]) and r["export_error"] is None
    assert files[0].read_bytes() == client.get(f"/api/documents/{doc_id}/output").content
    assert {f["value"] for f in json.loads(files[0].read_bytes())["fields"]} >= {A1[0]}
    close(client, doc_id)


def test_template_save_exports_and_the_store_stays_value_free(client, export_dir, nabu_home,  # noqa: F811
                                                               caplog):
    caplog.set_level(logging.DEBUG)
    doc_id = verified(client)
    r = client.post(f"/api/documents/{doc_id}/save", json={
        "choice": "new", "document_type": "Invoice", "region": "DE", "format": "Format A"})
    assert r.status_code == 200 and r.json()["exported"]
    assert len(list(export_dir.iterdir())) == 1
    stored = "".join(p.read_text(encoding="utf-8") for p in nabu_home.rglob("*") if p.is_file())
    assert not any(v in stored for v in A1)
    # The product log (the "nabu" logger only, hardening.configure_logging) carries no value.
    nabu_log = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("nabu"))
    assert "exported output" in nabu_log and not any(v in nabu_log for v in A1)
    close(client, doc_id)


def test_nothing_written_when_off(nabu_home, tmp_path):
    store = Store(default_paths().configured(Config()))
    assert store.paths.export_dir is None
    assert store.export_output("x.nabu.json", b"{}") is None
    assert not any(tmp_path.rglob("*.nabu.json"))


def test_export_failure_keeps_the_save(client, export_dir):  # noqa: F811
    export_dir.write_text("a file where the folder should be")
    doc_id = verified(client)
    r = client.post(f"/api/documents/{doc_id}/save", json={"choice": "document_only"})
    assert r.status_code == 200
    assert r.json()["exported"] is None and "export folder" in r.json()["export_error"]
    assert client.get(f"/api/documents/{doc_id}/output").status_code == 200  # still downloadable
    close(client, doc_id)


def test_relative_folder_refused():
    with pytest.raises(ConfigError, match="export_dir"):
        parse_config({"export_dir": "outbox"})


@pytest.mark.parametrize("where", ["data", "inside_data", "templates", "holds_templates"])
def test_folder_overlapping_the_store_refused(nabu_home, tmp_path, where):
    tpl = tmp_path / "shared" / "templates"
    folder = {"data": nabu_home, "inside_data": nabu_home / "outbox",
              "templates": tpl / "outbox", "holds_templates": tmp_path / "shared"}[where]
    with pytest.raises(ConfigError, match="export_dir"):
        default_paths().configured(Config(export_dir=str(folder), templates_dir=str(tpl)))
