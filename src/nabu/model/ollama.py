"""HTTP client for the local model runtime (FR-10). The only code that opens outbound HTTP.

Rules enforced here:
- The endpoint is a loopback address (validated in Config) and the client refuses any URL that
  is not under that exact scheme://host:port (AR-3).
- Redirects are never followed (a redirect could point off the machine).
- Environment proxies are ignored (trust_env=False): HTTP_PROXY must not route page images
  through another machine.
- Request and response bodies are never logged (FR-11.5).
"""

from __future__ import annotations

import logging
import time

import httpx

from nabu.config import Config
from nabu.errors import ModelUnavailable

log = logging.getLogger("nabu.model")


class ModelClient:
    def __init__(self, cfg: Config, timeout_s: float = 300.0) -> None:
        self.cfg = cfg
        host, port = cfg.endpoint  # raises if not loopback
        self._base = cfg.model_endpoint.rstrip("/")
        self._host, self._port = host, port
        self._http = httpx.Client(
            base_url=self._base,
            timeout=httpx.Timeout(timeout_s, connect=3.0),
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str) -> httpx.Response:
        t0 = time.monotonic()
        try:
            r = self._http.get(path)
        except httpx.ConnectError:
            raise ModelUnavailable(
                f"the local model runtime is not answering at {self._host}:{self._port}"
            ) from None
        except httpx.TimeoutException:
            raise ModelUnavailable("the local model runtime timed out") from None
        log.debug("model GET %s -> %s in %.0f ms", path, r.status_code, (time.monotonic() - t0) * 1000)
        return r

    def available(self) -> bool:
        """True if the runtime answers a health call (FR-1.7)."""
        try:
            return self._get("/api/tags").status_code == 200
        except ModelUnavailable:
            return False

    def models(self) -> list[str]:
        r = self._get("/api/tags")
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]

    # M1: discover_page, reread_crop, translate (FRD 10.3, 10.4). Each must validate the JSON
    # response against a schema, make one repair attempt, and never log the raw body.
