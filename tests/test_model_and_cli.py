import json

import pytest
from stub_ollama import StubOllama

from nabu.cli import main
from nabu.config import Config
from nabu.model.runtime import make_runtime


@pytest.mark.parametrize("runtime", ["ollama", "openai_compat"])
def test_runtime_talks_to_stub(runtime):
    with StubOllama(models=["stub-vl:test"]) as stub:
        rt = make_runtime(Config(model_endpoint=stub.url, model_runtime=runtime))
        assert rt.available()
        assert rt.models() == ["stub-vl:test"]
        rt.close()


def test_runtime_unavailable_is_false_not_crash():
    rt = make_runtime(Config(model_endpoint="http://127.0.0.1:1"), timeout_s=1)
    assert rt.available() is False
    rt.close()


def test_runtime_ignores_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example:3128")
    with StubOllama() as stub:
        rt = make_runtime(Config(model_endpoint=stub.url))
        assert rt.available()
        rt.close()


def test_cli_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip()


def test_cli_usage_error_exit_code():
    assert main(["no-such-command"]) == 2


def test_cli_doctor_json(nabu_home, capsys):
    with StubOllama() as stub:
        (nabu_home).mkdir(parents=True, exist_ok=True)
        (nabu_home / "config.json").write_text(json.dumps({"model_endpoint": stub.url}))
        assert main(["doctor", "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["runtime"]["present"] is True
    assert r["cpu_cores"]


def test_cli_doctor_no_runtime(nabu_home, capsys):
    nabu_home.mkdir(parents=True, exist_ok=True)
    (nabu_home / "config.json").write_text(json.dumps({"model_endpoint": "http://127.0.0.1:1"}))
    assert main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["runtime"]["present"] is False


def test_cli_refuses_remote_endpoint(nabu_home, capsys):
    nabu_home.mkdir(parents=True, exist_ok=True)
    (nabu_home / "config.json").write_text(json.dumps({"model_endpoint": "http://10.1.1.1:11434"}))
    assert main(["doctor"]) == 1
    assert "must be on this machine" in capsys.readouterr().err


def test_cli_has_no_read_command():  # FR-12.2
    for cmd in ("read", "scan", "extract"):
        assert main([cmd, "file.pdf"]) == 2


def write_config(home, data):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(data))


def test_doctor_reports_model_status(nabu_home, capsys):
    with StubOllama(models=["qwen3.5:4b"]) as stub:
        write_config(nabu_home, {"model_endpoint": stub.url, "model": "qwen3.5:4b"})
        assert main(["doctor", "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["model_installed"] is True and r["model_profile"] == "qwen3.5"
    assert r["recommended_model"].startswith("qwen3.5:")


def test_model_flag_beats_config(nabu_home, capsys):
    with StubOllama(models=["qwen3.5:2b"]) as stub:
        write_config(nabu_home, {"model_endpoint": stub.url, "model": "qwen3.5:4b"})
        assert main(["doctor", "--json", "--model", "qwen3.5:2b"]) == 0
    assert json.loads(capsys.readouterr().out)["configured_model"] == "qwen3.5:2b"


def test_models_use_switches_model_and_keeps_other_keys(nabu_home, capsys):
    with StubOllama(models=["gemma4:e4b"]) as stub:
        write_config(nabu_home, {"model_endpoint": stub.url, "model": "qwen3.5:4b", "dpi": 300})
        assert main(["models", "use", "gemma4:e4b"]) == 0
    saved = json.loads((nabu_home / "config.json").read_text())
    assert saved == {"model_endpoint": stub.url, "model": "gemma4:e4b", "dpi": 300}
    assert "not installed" not in capsys.readouterr().out


def test_models_use_warns_when_not_installed(nabu_home, capsys):
    with StubOllama(models=[]) as stub:
        write_config(nabu_home, {"model_endpoint": stub.url})
        assert main(["models", "use", "qwen3.5:4b"]) == 0
    assert "nabu models pull qwen3.5:4b" in capsys.readouterr().out


def test_models_use_bad_value_writes_nothing(nabu_home, capsys):
    write_config(nabu_home, {"model": "qwen3.5:4b"})
    before = (nabu_home / "config.json").read_text()
    assert main(["models", "use", "x", "--profile", "no-such-profile"]) == 1
    assert main(["models", "use", "x", "--endpoint", "http://10.0.0.5:11434"]) == 1
    assert (nabu_home / "config.json").read_text() == before


def test_models_list_marks_active_and_recommends(nabu_home, capsys):
    with StubOllama(models=["qwen3.5:4b", "gemma4:e4b"]) as stub:
        write_config(nabu_home, {"model_endpoint": stub.url, "model": "qwen3.5:4b"})
        assert main(["models", "list"]) == 0
    out = capsys.readouterr().out
    assert "* qwen3.5:4b" in out and "  gemma4:e4b" in out and "recommended" in out


def test_models_pull_streams_progress(nabu_home, capsys):
    with StubOllama() as stub:
        write_config(nabu_home, {"model_endpoint": stub.url})
        assert main(["models", "pull", "qwen3.5:4b"]) == 0
    out = capsys.readouterr().out
    assert "downloading 50%" in out and "qwen3.5:4b is ready" in out


def test_unexpected_error_prints_type_only(nabu_home, capsys, monkeypatch):
    from nabu.store.store import Store

    def boom(self):
        raise RuntimeError("Beispiel GmbH RE-2026-0412")

    monkeypatch.setattr(Store, "templates", boom)
    assert main(["templates", "list"]) == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "RE-2026-0412" not in err and "Traceback" not in err
