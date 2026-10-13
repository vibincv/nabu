"""Run-time egress guard (AR-3, FR-11.2).

Installed once at process start, before any other Nabu import does network work. It patches
the Python socket layer so that:

1. `connect()` / `connect_ex()` to any non-loopback address raises EgressBlocked.
2. Name lookups (`getaddrinfo`, `gethostbyname`, ...) for any name other than a loopback
   literal or "localhost" raise EgressBlocked. This matters because a DNS query leaks the
   hostname even when the later connect would be blocked.

Loopback connects are allowed to any port, not only the model endpoint. Reason: on Windows,
`socket.socketpair()` (used by asyncio) is implemented as a loopback connect to an ephemeral
port. The model endpoint's exact host:port is enforced separately by the model client
(nabu.model.ollama), which is the only code that opens outbound HTTP.

3. Proxy environment variables are removed for this process: a proxy listening on loopback
   would otherwise be an allowed hop to the internet.

Residual risk, documented: code that bypasses Python sockets (native extensions opening
their own sockets, subprocesses) is not covered. Nabu runs no subprocesses during reading;
native dependencies are reviewed when added. The CI egress test (FR-11.2) covers every path.
"""

from __future__ import annotations

import os
import socket
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


def _check_address(address: object, family: int) -> None:
    if family == getattr(socket, "AF_UNIX", object()):
        return  # local IPC only
    if isinstance(address, tuple) and address:
        _check_host(address[0], "connection")


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
        sock_cls = socket.socket
        _orig["connect"] = sock_cls.connect
        _orig["connect_ex"] = sock_cls.connect_ex
        _orig["getaddrinfo"] = socket.getaddrinfo
        _orig["gethostbyname"] = socket.gethostbyname
        _orig["gethostbyname_ex"] = socket.gethostbyname_ex
        _orig["create_connection"] = socket.create_connection

        def connect(self, address):  # type: ignore[no-untyped-def]
            _check_address(address, self.family)
            return _orig["connect"](self, address)  # type: ignore[operator]

        def connect_ex(self, address):  # type: ignore[no-untyped-def]
            _check_address(address, self.family)
            return _orig["connect_ex"](self, address)  # type: ignore[operator]

        def getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
            _check_host(host, "name lookup")
            return _orig["getaddrinfo"](host, *args, **kwargs)  # type: ignore[operator]

        def gethostbyname(host):  # type: ignore[no-untyped-def]
            _check_host(host, "name lookup")
            return _orig["gethostbyname"](host)  # type: ignore[operator]

        def gethostbyname_ex(host):  # type: ignore[no-untyped-def]
            _check_host(host, "name lookup")
            return _orig["gethostbyname_ex"](host)  # type: ignore[operator]

        def create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
            _check_host(address[0] if address else None, "connection")
            return _orig["create_connection"](address, *args, **kwargs)  # type: ignore[operator]

        sock_cls.connect = connect  # type: ignore[method-assign]
        sock_cls.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = getaddrinfo
        socket.gethostbyname = gethostbyname
        socket.gethostbyname_ex = gethostbyname_ex
        socket.create_connection = create_connection
        _installed = True


def installed() -> bool:
    return _installed
