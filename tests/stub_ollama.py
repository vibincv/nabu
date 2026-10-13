"""A stub model runtime on 127.0.0.1 (NFR-6). Speaks the Ollama API (/api/tags, /api/chat,
/api/pull) and the OpenAI-compatible API (/v1/models, /v1/chat/completions), so both runtime
adapters are tested against the same stub. Replies are canned: tests push them onto
`StubOllama.responses`, and can make the next call fail with `StubOllama.fail_next`."""

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

    def _failed(self) -> bool:
        if self.server.fail_next is None:
            return False
        code, body = self.server.fail_next
        self.server.fail_next = None
        self._send(code, body)
        return True

    def do_GET(self) -> None:  # noqa: N802
        self.server.calls.append(("GET", self.path, None))
        if self._failed():
            return
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": m} for m in self.server.models]})
        elif self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": m} for m in self.server.models]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.calls.append(("POST", self.path, body))
        if self._failed():
            return
        content = self.server.responses.pop(0) if self.server.responses else "{}"
        if self.path == "/api/chat":
            self._send(200, {"model": body.get("model"), "done": True,
                             "message": {"role": "assistant", "content": content}})
        elif self.path == "/v1/chat/completions":
            self._send(200, {"choices": [{"index": 0, "message": {"role": "assistant",
                                                                  "content": content}}]})
        elif self.path == "/api/pull":
            lines = [{"status": "pulling manifest"},
                     {"status": "downloading", "total": 100, "completed": 50},
                     {"status": "downloading", "total": 100, "completed": 100},
                     {"status": "success"}]
            data = b"".join(json.dumps(x).encode() + b"\n" for x in lines)
            self.send_response(200)
            self.send_header("content-type", "application/x-ndjson")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._send(404, {"error": "not found"})


class _Server(ThreadingHTTPServer):
    calls: list
    models: list[str]
    responses: list[str]
    fail_next: tuple[int, dict] | None


class StubOllama:
    def __init__(self, models: list[str] | None = None) -> None:
        self._srv = _Server(("127.0.0.1", 0), _Handler)
        self._srv.calls = []
        self._srv.models = models or ["stub-vl:test"]
        self._srv.responses = []
        self._srv.fail_next = None
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

    def fail_next(self, code: int, body: dict) -> None:
        self._srv.fail_next = (code, body)

    def __enter__(self) -> StubOllama:
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._srv.shutdown()
        self._srv.server_close()
