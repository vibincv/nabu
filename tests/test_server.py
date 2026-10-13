import pytest
from starlette.testclient import TestClient

from nabu.server.app import SECURITY_HEADERS, create_app

PORT = 8765


@pytest.fixture
def app_and_token(tmp_path):
    dist = tmp_path / "ui_dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<!doctype html><html><head><meta name="nabu-token" content=""></head><body></body></html>'
    )
    return create_app(PORT, token="t" * 43, ui_dist=dist)


@pytest.fixture
def client(app_and_token):
    app, _ = app_and_token
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    c.get("/")  # open the window, as the browser does; this claims it
    return c


def test_index_embeds_token_and_security_headers(client, app_and_token):
    _, token = app_and_token
    r = client.get("/")
    assert r.status_code == 200
    assert f'content="{token}"' in r.text
    for k, v in SECURITY_HEADERS.items():
        assert r.headers[k] == v
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_api_requires_token_header(client, app_and_token):
    _, token = app_and_token
    assert client.get("/api/health").status_code == 401  # cookie alone is not enough
    assert client.get("/api/health", headers={"x-nabu-token": "wrong"}).status_code == 401
    r = client.get("/api/health", headers={"x-nabu-token": token})
    assert r.status_code == 200 and r.json()["ok"]


def test_token_in_query_string_is_ignored(client, app_and_token):
    _, token = app_and_token
    assert client.get(f"/api/health?token={token}").status_code == 401


@pytest.mark.parametrize("host", ["evil.example:8765", "127.0.0.1:9999", "192.168.1.4:8765"])
def test_wrong_host_refused(app_and_token, host):  # DNS rebinding defence (API-1)
    app, token = app_and_token
    c = TestClient(app, base_url=f"http://{host}")
    r = c.get("/api/health", headers={"x-nabu-token": token})
    assert r.status_code == 421
    assert c.get("/").status_code == 421  # the page and its token are refused too
    assert r.headers["cache-control"] == "no-store"


def test_cross_origin_refused(client, app_and_token):
    _, token = app_and_token
    r = client.get("/api/health", headers={"x-nabu-token": token, "origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_allowed(client, app_and_token):
    _, token = app_and_token
    r = client.get("/api/health", headers={"x-nabu-token": token,
                                           "origin": f"http://127.0.0.1:{PORT}"})
    assert r.status_code == 200


def test_ui_not_built_message(tmp_path):
    app, _ = create_app(PORT, ui_dist=tmp_path / "missing")
    r = TestClient(app, base_url=f"http://localhost:{PORT}").get("/")
    assert "not built" in r.text


def test_first_browser_claims_the_window(app_and_token):
    app, token = app_and_token
    first = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    r = first.get("/")
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    assert first.get("/").status_code == 200  # a reload keeps working
    other = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")  # another program or user
    r = other.get("/")
    assert r.status_code == 409 and token not in r.text


def test_api_needs_the_cookie_as_well_as_the_token(app_and_token):
    app, token = app_and_token
    TestClient(app, base_url=f"http://127.0.0.1:{PORT}").get("/")  # the window is claimed
    stranger = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    assert stranger.get("/api/health", headers={"x-nabu-token": token}).status_code == 401


def test_non_ascii_token_is_refused_not_crashed(client):
    client.get("/")
    r = client.get("/api/health", headers={"x-nabu-token": "tök".encode("latin-1")})
    assert r.status_code == 401


def test_websocket_refused(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/ws"):
        pass
