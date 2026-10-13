import json

from stub_ollama import StubOllama

from nabu.cli import main
from nabu.config import Config
from nabu.model.ollama import ModelClient


def test_model_client_talks_to_stub():
    with StubOllama(models=["stub-vl:test"]) as stub:
        c = ModelClient(Config(model_endpoint=stub.url))
        assert c.available()
        assert c.models() == ["stub-vl:test"]
        c.close()


def test_model_client_unavailable_is_false_not_crash():
    c = ModelClient(Config(model_endpoint="http://127.0.0.1:1"), timeout_s=1)
    assert c.available() is False
    c.close()


def test_model_client_ignores_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example:3128")
    with StubOllama() as stub:
        c = ModelClient(Config(model_endpoint=stub.url))
        assert c.available()
        c.close()


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
