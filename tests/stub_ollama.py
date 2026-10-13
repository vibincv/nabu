"""A stub that mimics the Ollama HTTP API on 127.0.0.1 (NFR-6). Used by every test that needs
a model. Responses are canned; tests set them through `StubOllama.responses`."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *args) -> None:  # silence
        pass

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        self.server.calls.append(("GET", self.path, None))
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": m} for m in self.server.models]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.calls.append(("POST", self.path, body))
        if self.path in ("/api/chat", "/api/generate"):
            content = self.server.responses.pop(0) if self.server.responses else "{}"
            self._send(200, {"model": body.get("model"), "message": {"role": "assistant",
                                                                     "content": content},
                             "done": True})
        else:
            self._send(404, {"error": "not found"})


class _Server(ThreadingHTTPServer):
    calls: list
    models: list[str]
    responses: list[str]


class StubOllama:
    def __init__(self, models: list[str] | None = None) -> None:
        self._srv = _Server(("127.0.0.1", 0), _Handler)
        self._srv.calls = []
        self._srv.models = models or ["stub-vl:test"]
        self._srv.responses = []
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    @property
    def calls(self) -> list:
        return self._srv.calls

    @property
    def responses(self) -> list[str]:
        return self._srv.responses

    def __enter__(self) -> StubOllama:
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._srv.shutdown()
        self._srv.server_close()
