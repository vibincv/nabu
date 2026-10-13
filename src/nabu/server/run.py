"""Start the review window on 127.0.0.1 only (FR-6.1). No LAN binding exists in this phase."""

from __future__ import annotations

import errno
import logging
import socket
import threading
import webbrowser

import uvicorn

from nabu.server.app import create_app

log = logging.getLogger("nabu.server")
HOST = "127.0.0.1"


def find_free_port(preferred: int, tries: int = 20) -> int:
    """Preferred port, else the next free one (FR-6.1)."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError as e:
                if e.errno not in (errno.EADDRINUSE, errno.EACCES, 10048, 10013):
                    raise
    raise OSError(f"no free port between {preferred} and {preferred + tries - 1}")


def serve(preferred_port: int, open_browser: bool = True) -> None:
    port = find_free_port(preferred_port)
    holder: dict[str, uvicorn.Server] = {}

    def quit_server() -> None:
        holder["server"].should_exit = True

    app, _token = create_app(port, on_quit=quit_server)
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False,
                            server_header=False, date_header=False, proxy_headers=False)
    server = uvicorn.Server(config)
    holder["server"] = server

    url = f"http://{HOST}:{port}/"
    log.info("review window at %s", url)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    server.run()
