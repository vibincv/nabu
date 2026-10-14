"""FR-12.1 commands added in M1: langs list|pull, translations list|delete; doctor OCR report."""

import json

from nabu import cli
from nabu.cli import main
from nabu.ocr import packs
from nabu.session import Session
from nabu.store.store import Store


def test_langs_list(nabu_home, capsys):
    assert main(["langs", "list"]) == 0
    out = capsys.readouterr().out
    assert "built in: en" in out and "ko  Korean: not installed" in out


def test_langs_pull_unknown_language(nabu_home, capsys):
    assert main(["langs", "pull", "xx"]) == 1
    assert "no OCR language pack for 'xx'" in capsys.readouterr().err


def test_langs_pull_is_refused_inside_a_guarded_process(nabu_home, capsys):
    # The test run has the egress guard installed, like the review server: no download from here.
    assert main(["langs", "pull", "ko"]) == 1
    assert "cannot be downloaded while Nabu is reading" in capsys.readouterr().err


def test_only_langs_pull_skips_the_guard():
    p = cli.build_parser()
    assert cli._needs_internet(p.parse_args(["langs", "pull", "ko"]))
    for argv in (["langs", "list"], ["serve"], ["doctor"], ["models", "pull"]):
        assert not cli._needs_internet(p.parse_args(argv))


def test_store_installs_a_verified_pack(nabu_home, monkeypatch):
    model, keys = b"model-bytes", b"keys"
    ko = packs.PACKS["ko"]
    monkeypatch.setitem(packs.PACKS, "ko", packs.Pack(
        lang="ko", language="Korean", script="Hangul",
        model=packs.PackFile(ko.model.name, ko.model.url, packs.sha256(model), len(model)),
        keys=packs.PackFile(ko.keys.name, ko.keys.url, packs.sha256(keys), len(keys))))
    store = Store()
    d = store.install_ocr_pack("ko", {"rec.onnx": model, "keys.txt": keys})
    assert packs.installed(store.paths.ocr_langs_dir) == {"ko": d}


def test_translations_list_and_delete(nabu_home, capsys):
    Store().remember_translation({"id": "t1", "lang": "de", "term": "Rechnungsnr.",
                                  "english": "Invoice number"}, Session())
    assert main(["translations", "list"]) == 0
    assert "t1  [de] Rechnungsnr. -> Invoice number" in capsys.readouterr().out
    assert main(["translations", "delete", "t1"]) == 0
    assert main(["translations", "delete", "t1"]) == 1
    assert Store().translations()["entries"] == []


def test_doctor_reports_ocr(nabu_home, capsys):
    assert main(["doctor", "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert set(r["ocr"]) == {"engine", "present", "languages", "packs_available"}
    assert r["ocr"]["packs_available"]["ko"]["installed"] is False
    assert "ram_free_gb" in r and isinstance(r["gpus"], list)


def test_templates_history_and_rollback(nabu_home, capsys):  # FR-7.12, FR-7.13
    from test_store import template

    store = Store()
    s = Session()
    store.save_template(template(name="Invoice Number"), s)
    t2 = template(name="Invoice No", version=2)
    t2["template"]["change"] = {"kind": "updated", "renamed": [["Invoice Number", "Invoice No"]],
                                "added": [], "removed": [], "type_changed": [], "reordered": False}
    store.save_template(t2, s)
    tid = t2["template"]["id"]
    assert main(["templates", "history", tid]) == 0
    out = capsys.readouterr().out
    assert "v2" in out and "renamed Invoice Number -> Invoice No" in out and "(current)" in out
    assert main(["templates", "rollback", tid, "1"]) == 0
    assert store.load_template(tid)["fields"][0]["name"] == "Invoice Number"
    assert store.history(tid) == [1, 2, 3]
    assert main(["templates", "rollback", tid, "7"]) == 1
