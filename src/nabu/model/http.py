"""Loopback-only HTTP for model runtimes (AR-3, FR-10). The only code that opens outbound HTTP.

Rules enforced here, for every runtime adapter:
- The endpoint is a loopback address (validated in Config). Requests take a relative path only,
  so no call can name another host or port.
- Redirects are never followed (a redirect could point off the machine).
- Environment proxies are ignored (trust_env=False): HTTP_PROXY must not route page images
  through another machine.
- The egress guard is installed before the first connection, whoever the caller is.
- Request and response bodies are never logged (FR-11.5).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator

import httpx

from nabu import netguard
from nabu.config import Config
from nabu.errors import ModelUnavailable, NabuError

log = logging.getLogger("nabu.model")


class LoopbackHttp:
    def __init__(self, cfg: Config, timeout_s: float) -> None:
        netguard.install()
        self.host, self.port = cfg.endpoint  # raises if not loopback
        self.base = cfg.model_endpoint.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base,
            timeout=httpx.Timeout(timeout_s, connect=3.0),
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        self._http.close()

    @staticmethod
    def _check_path(path: str) -> None:
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise NabuError("model request path must be relative to the configured endpoint")

    def _unavailable(self) -> ModelUnavailable:
        return ModelUnavailable(
            f"the local model runtime is not answering at {self.host}:{self.port}. "
            "Start it (for Ollama: run `ollama serve`), then try again."
        )

    def request(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        self._check_path(path)
        t0 = time.monotonic()
        try:
            r = self._http.request(method, path, json=body)
        except httpx.ConnectError:
            raise self._unavailable() from None
        except httpx.TimeoutException:
            raise ModelUnavailable(
                "the local model runtime timed out. A smaller model is faster: "
                "run `nabu models list` to see the options."
            ) from None
        log.debug("model %s %s -> %s in %.0f ms", method, path, r.status_code,
                  (time.monotonic() - t0) * 1000)
        return r

    def stream_json_lines(self, method: str, path: str, body: dict) -> Iterator[dict]:
        """NDJSON streaming (Ollama pull progress)."""
        self._check_path(path)
        try:
            # Downloads take minutes: no read timeout, but a short connect timeout.
            with self._http.stream(method, path, json=body,
                                   timeout=httpx.Timeout(None, connect=3.0)) as r:
                if r.status_code >= 300:
                    r.read()
                    yield {"_status": r.status_code, "_error": error_text(r)}
                    return
                for line in r.iter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.ConnectError:
            raise self._unavailable() from None


def error_text(r: httpx.Response) -> str:
    """The runtime's short error string, for matching only. Never logged or shown as-is."""
    try:
        data = r.json()
    except ValueError:
        return ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            err = err.get("message")
        if isinstance(err, str):
            return err.lower()
    return ""
