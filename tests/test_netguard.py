import asyncio
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


TEST_NET = ("192.0.2.1", 9)  # RFC 5737 documentation range: never routed


@pytest.mark.parametrize("args", [(TEST_NET,), (0, TEST_NET)])  # sendto(data, [flags,] address)
def test_udp_sendto_blocked(args):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(EgressBlocked):
            s.sendto(b"x", *args)
    finally:
        s.close()


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="sendmsg is POSIX only")
def test_udp_sendmsg_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(EgressBlocked):
            s.sendmsg([b"x"], [], 0, TEST_NET)
        with pytest.raises(EgressBlocked):
            s.sendmsg([b"x"], address=TEST_NET)
    finally:
        s.close()


def test_udp_sendto_loopback_allowed():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        rx.bind(("127.0.0.1", 0))
        tx.sendto(b"x", rx.getsockname())
        assert rx.recv(1) == b"x"
    finally:
        rx.close()
        tx.close()


def test_reverse_lookup_blocked():
    with pytest.raises(EgressBlocked):
        socket.gethostbyaddr("8.8.8.8")
    with pytest.raises(EgressBlocked):
        socket.getnameinfo(("8.8.8.8", 53), 0)


def test_reverse_lookup_loopback_allowed():
    flags = socket.NI_NUMERICHOST | socket.NI_NUMERICSERV  # no resolver involved
    assert socket.getnameinfo(("127.0.0.1", 80), flags) == ("127.0.0.1", "80")


def test_asyncio_tcp_blocked():  # on Windows the Proactor loop connects through IOCP
    async def go():
        await asyncio.open_connection(*TEST_NET)

    with pytest.raises(EgressBlocked):
        asyncio.run(go())


def test_asyncio_udp_blocked():
    async def go():
        await asyncio.get_running_loop().create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=TEST_NET)

    with pytest.raises(EgressBlocked):
        asyncio.run(go())


def test_asyncio_unconnected_udp_send_blocked():
    errors: list[BaseException] = []

    async def go():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, ctx: errors.append(ctx.get("exception")))
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
        transport.sendto(b"x", TEST_NET)
        await asyncio.sleep(0.1)
        transport.close()

    asyncio.run(go())
    assert any(isinstance(e, EgressBlocked) for e in errors)


def test_asyncio_loopback_allowed():
    async def go():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        server.close()
        await server.wait_closed()

    asyncio.run(go())
