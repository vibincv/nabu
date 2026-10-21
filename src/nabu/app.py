"""What the Nabu shortcut runs (FR-1.11): open the review window, starting Nabu if needed.

If a Nabu review window server already answers on the usual ports, the browser is pointed at
it instead of starting a second one. "Quit Nabu" in the window stops the server.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import webbrowser


def running_port(preferred: int, tries: int = 20) -> int | None:
    """The port of a Nabu server already running on this machine, if any.

    Every /api call needs the window's token, which this process does not have, so a running
    Nabu answers 401 with its own error text. That reply is the signature looked for.
    """
    for port in range(preferred, preferred + tries):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3) as s:
                s.sendall(f"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
                chunks: list[bytes] = []
                while sum(map(len, chunks)) < 8192 and (chunk := s.recv(4096)):
                    chunks.append(chunk)
                reply = b"".join(chunks).decode("latin-1")
        except OSError:
            continue
        head, _, body = reply.partition("\r\n\r\n")
        try:
            data = json.loads(body)
        except ValueError:
            continue
        if head.startswith("HTTP/1.1 401") and data == {"error": "missing or wrong token"}:
            return port
    return None


def _windowless_stdio() -> None:
    """pythonw (the Windows shortcut) has no console: sys.stdout and sys.stderr are None, and
    uvicorn's log setup fails on that. Messages still reach the log file."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def main() -> int:
    _windowless_stdio()
    from nabu.cli import main as cli_main
    from nabu.config import load_config
    from nabu.store.paths import default_paths

    try:
        port = running_port(load_config(default_paths().config_file).ui_port)
    except Exception:  # a bad config is reported by `serve` below
        port = None
    if port is not None:
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return 0
    return cli_main(["serve"])


if __name__ == "__main__":
    raise SystemExit(main())
