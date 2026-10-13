import json

import pytest

from nabu.config import Config, is_loopback_host, load_config
from nabu.errors import ConfigError


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.8.9.1", "::1", "[::1]"])
def test_loopback_hosts(host):
    assert is_loopback_host(host)


@pytest.mark.parametrize("host", ["192.168.1.5", "10.0.0.2", "example.com", "0.0.0.0", "my-mac"])
def test_non_loopback_hosts(host):
    assert not is_loopback_host(host)


def test_default_endpoint_is_loopback():
    assert Config().endpoint == ("127.0.0.1", 11434)


@pytest.mark.parametrize("url", ["http://192.168.1.20:11434", "http://gpu-box.local:11434",
                                 "https://api.example.com"])
def test_remote_endpoint_refused(url):
    with pytest.raises(ConfigError, match="must be on this machine"):
        Config(model_endpoint=url)


def test_remote_endpoint_refused_from_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model_endpoint": "http://10.0.0.5:11434"}))
    with pytest.raises(ConfigError, match="must be on this machine"):
        load_config(p)


def test_remote_endpoint_refused_from_env(monkeypatch):
    monkeypatch.setenv("NABU_MODEL_ENDPOINT", "http://10.0.0.5:11434")
    with pytest.raises(ConfigError):
        load_config(None)


def test_telemetry_cannot_be_enabled():
    with pytest.raises(ConfigError):
        Config(telemetry=True)


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"upload_to_cloud": True}))
    with pytest.raises(ConfigError):
        load_config(p)
