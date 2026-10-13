import socket

import httpx
import pytest

from nabu.errors import EgressBlocked


def test_connect_to_public_ip_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(EgressBlocked):
            s.connect(("1.1.1.1", 443))
    finally:
        s.close()


def test_connect_ex_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(EgressBlocked):
            s.connect_ex(("8.8.8.8", 53))
    finally:
        s.close()


def test_dns_lookup_blocked_so_hostname_never_leaks():
    with pytest.raises(EgressBlocked):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(EgressBlocked):
        socket.gethostbyname("example.com")


def test_httpx_to_internet_blocked():
    with pytest.raises(EgressBlocked):
        httpx.get("https://example.com", timeout=2)


def test_loopback_allowed():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        c.connect(("127.0.0.1", port))
        assert socket.getaddrinfo("localhost", port)
    finally:
        c.close()
        srv.close()


def test_socketpair_works():  # asyncio needs this; on Windows it is a loopback connect
    a, b = socket.socketpair()
    a.sendall(b"x")
    assert b.recv(1) == b"x"
    a.close()
    b.close()


def test_proxy_env_removed_at_install():
    import os

    standard = {"http_proxy", "https_proxy", "all_proxy"}
    assert not [v for v in os.environ if v.lower() in standard]
