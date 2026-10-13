"""Run-time egress guard (AR-3, FR-11.2).

Installed once at process start, before any other Nabu import does network work. It patches
the Python socket layer so that:

1. `connect()` / `connect_ex()` to any non-loopback address raises EgressBlocked.
2. Datagrams sent with an explicit address (`sendto()`, `sendmsg()`) to any non-loopback
   address raise EgressBlocked. UDP never calls `connect()`, so (1) alone does not cover it.
3. Name lookups, forward (`getaddrinfo`, `gethostbyname`, ...) and reverse (`gethostbyaddr`,
   `getnameinfo`), for anything other than a loopback literal or "localhost" raise
   EgressBlocked. This matters because a DNS query leaks the name or address even when no
   connection follows.
4. On Windows, asyncio's default Proactor loop connects and sends datagrams through IOCP
   (`ConnectEx`, `WSASendTo`) and never calls the socket methods above. Its `connect` and
   `sendto` are guarded too.

Loopback connects are allowed to any port, not only the model endpoint. Reason: on Windows,
`socket.socketpair()` (used by asyncio) is implemented as a loopback connect to an ephemeral
port. The model endpoint's exact host:port is enforced separately by the model client
(nabu.model.ollama), which is the only code that opens outbound HTTP.

5. Proxy environment variables are removed for this process: a proxy listening on loopback
   would otherwise be an allowed hop to the internet.

Residual risk, documented: code that bypasses the Python `socket.socket` class is not covered:
native extensions opening their own sockets, subprocesses, and direct use of the C-level
`_socket.socket` class. Nabu runs no subprocesses during reading; native dependencies are
reviewed when added. The CI egress test (FR-11.2) covers every path.
"""

from __future__ import annotations

import os
import socket
import sys
import threading

from nabu.config import is_loopback_host
from nabu.errors import EgressBlocked

_lock = threading.Lock()
_installed = False
_orig: dict[str, object] = {}
_PROXY_VARS = frozenset({"http_proxy", "https_proxy", "all_proxy", "ftp_proxy", "ws_proxy",
                         "wss_proxy", "socks_proxy"})


def _check_host(host: object, what: str) -> None:
    if host is None:
        return
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return
    if host == "" or is_loopback_host(host):
        return
    raise EgressBlocked(f"blocked {what} to {host}: Nabu only talks to this machine")


def _check_address(address: object, family: int, what: str = "connection") -> None:
    if family == getattr(socket, "AF_UNIX", object()):
        return  # local IPC only
    if isinstance(address, tuple) and address:
        _check_host(address[0], what)


def _guard_socket_class(sock_cls: type) -> None:
    _orig["connect"] = sock_cls.connect
    _orig["connect_ex"] = sock_cls.connect_ex
    _orig["sendto"] = sock_cls.sendto

    def connect(self, address):  # type: ignore[no-untyped-def]
        _check_address(address, self.family)
        return _orig["connect"](self, address)  # type: ignore[operator]

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        _check_address(address, self.family)
        return _orig["connect_ex"](self, address)  # type: ignore[operator]

    def sendto(self, data, *args):  # type: ignore[no-untyped-def]
        # sendto(data, address) or sendto(data, flags, address)
        if args:
            _check_address(args[-1], self.family, "datagram")
        return _orig["sendto"](self, data, *args)  # type: ignore[operator]

    sock_cls.connect = connect  # type: ignore[method-assign]
    sock_cls.connect_ex = connect_ex  # type: ignore[method-assign]
    sock_cls.sendto = sendto  # type: ignore[method-assign]

    if hasattr(sock_cls, "sendmsg"):  # POSIX only
        _orig["sendmsg"] = sock_cls.sendmsg

        def sendmsg(self, buffers, *args, **kwargs):  # type: ignore[no-untyped-def]
            # sendmsg(buffers, ancdata=(), flags=0, address=None)
            address = kwargs.get("address", args[2] if len(args) > 2 else None)
            _check_address(address, self.family, "datagram")
            return _orig["sendmsg"](self, buffers, *args, **kwargs)  # type: ignore[operator]

        sock_cls.sendmsg = sendmsg  # type: ignore[attr-defined]


def _guard_lookups() -> None:
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
                 "create_connection"):
        _orig[name] = getattr(socket, name)

    def getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        _check_host(host, "name lookup")
        return _orig["getaddrinfo"](host, *args, **kwargs)  # type: ignore[operator]

    def gethostbyname(host):  # type: ignore[no-untyped-def]
        _check_host(host, "name lookup")
        return _orig["gethostbyname"](host)  # type: ignore[operator]

    def gethostbyname_ex(host):  # type: ignore[no-untyped-def]
        _check_host(host, "name lookup")
        return _orig["gethostbyname_ex"](host)  # type: ignore[operator]

    def gethostbyaddr(host):  # type: ignore[no-untyped-def]
        _check_host(host, "reverse lookup")
        return _orig["gethostbyaddr"](host)  # type: ignore[operator]

    def create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        _check_host(address[0] if address else None, "connection")
        return _orig["create_connection"](address, *args, **kwargs)  # type: ignore[operator]

    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    socket.gethostbyname_ex = gethostbyname_ex
    socket.gethostbyaddr = gethostbyaddr
    socket.create_connection = create_connection

    # getnameinfo is a C builtin with positional-only arguments.
    _orig["getnameinfo"] = socket.getnameinfo

    def getnameinfo(sockaddr, flags, /):  # type: ignore[no-untyped-def]
        if isinstance(sockaddr, tuple) and sockaddr:
            _check_host(sockaddr[0], "reverse lookup")
        return _orig["getnameinfo"](sockaddr, flags)  # type: ignore[operator]

    socket.getnameinfo = getnameinfo


def _guard_proactor() -> None:
    """asyncio on Windows: the Proactor loop goes through IOCP, not socket.connect/sendto."""
    from asyncio import windows_events

    proactor = windows_events.IocpProactor
    _orig["proactor_connect"] = proactor.connect
    _orig["proactor_sendto"] = proactor.sendto

    def connect(self, conn, address):  # type: ignore[no-untyped-def]
        _check_address(address, conn.family)
        return _orig["proactor_connect"](self, conn, address)  # type: ignore[operator]

    def sendto(self, conn, buf, flags=0, addr=None):  # type: ignore[no-untyped-def]
        _check_address(addr, conn.family, "datagram")
        return _orig["proactor_sendto"](self, conn, buf, flags, addr)  # type: ignore[operator]

    proactor.connect = connect  # type: ignore[method-assign]
    proactor.sendto = sendto  # type: ignore[method-assign]


def install() -> None:
    """Install the guard. Idempotent."""
    global _installed
    with _lock:
        if _installed:
            return
        # A proxy on loopback (a corporate agent, a dev tool) is an egress path the socket
        # check would allow. Remove proxy settings for this process so no library uses one.
        for var in list(os.environ):
            if var.lower() in _PROXY_VARS:
                del os.environ[var]
        _guard_socket_class(socket.socket)
        _guard_lookups()
        if sys.platform == "win32":
            _guard_proactor()
        _installed = True


def installed() -> bool:
    return _installed
