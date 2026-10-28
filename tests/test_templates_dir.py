"""Templates in a folder the owner chooses (config `templates_dir`, M3.2 2026-10-21).

Found in the owner's retest: the server ran with NABU_HOME in a temp folder, so the template went
there. A configured folder keeps templates in one known place, also one shared by several
machines; it may hold other files, so Nabu touches only its own template files there.
"""

import json

import pytest
from test_store import template

from nabu.cli import main
from nabu.config import parse_config
from nabu.errors import ConfigError
from nabu.store.paths import default_paths
from nabu.store.store import Store


def configured(nabu_home, folder):
    nabu_home.mkdir(parents=True, exist_ok=True)
    (nabu_home / "config.json").write_text(json.dumps({"templates_dir": str(folder),
                                                       "model_endpoint": "http://127.0.0.1:1"}))
    return default_paths().configured(parse_config({"templates_dir": str(folder)}))


def test_relative_folder_refused():
    with pytest.raises(ConfigError, match="templates_dir"):
        parse_config({"templates_dir": "templates"})


def test_default_is_the_data_folder(nabu_home):
    paths = default_paths().configured(parse_config({}))
    assert paths.templates_dir == nabu_home / "templates"


def test_templates_saved_and_listed_in_the_folder(nabu_home, tmp_path):
    folder = tmp_path / "shared-templates"
    store = Store(configured(nabu_home, folder))
    p = store._save_template(template(), [])
    assert folder in p.parents
    assert not (nabu_home / "templates").exists()
    assert [t["template"]["id"] for t in store.templates()] == ["tpl_vendor_invoice_DE_acme-2025"]


@pytest.mark.parametrize("where", ["data", "parent"])
def test_data_folder_or_its_parent_refused(nabu_home, where):
    folder = nabu_home if where == "data" else nabu_home.parent
    with pytest.raises(ConfigError, match="templates_dir"):
        default_paths().configured(parse_config({"templates_dir": str(folder)}))


def test_forget_removes_only_template_files(nabu_home, tmp_path):
    folder = tmp_path / "shared-templates"
    store = Store(configured(nabu_home, folder))
    store._save_template(template(), [])
    store._save_template(template(version=2), [])  # leaves a file under versions/
    (folder / "README.txt").parent.mkdir(parents=True, exist_ok=True)
    (folder / "README.txt").write_text("not Nabu's")
    removed = store.forget("templates")
    assert len(removed) == 2 and store.templates() == []
    assert (folder / "README.txt").exists()  # the folder and unrelated files stay
    assert sorted(p.name for p in folder.rglob("*")) == ["README.txt"]


def test_cli_and_doctor_use_the_folder(nabu_home, tmp_path, capsys):
    folder = tmp_path / "shared-templates"
    Store(configured(nabu_home, folder))._save_template(template(), [])
    assert main(["templates", "list"]) == 0
    assert "tpl_vendor_invoice_DE_acme-2025" in capsys.readouterr().out
    assert main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["store"]["templates"] == str(folder)
