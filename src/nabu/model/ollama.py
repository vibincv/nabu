"""Ollama runtime adapter (FR-10). API: /api/tags, /api/chat, /api/pull."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import httpx

from nabu.config import Config
from nabu.errors import ModelNotFound, ModelUnavailable
from nabu.model.http import LoopbackHttp, error_text
from nabu.model.runtime import ChatRequest, PullProgress


def raise_for_model_error(r: httpx.Response, model: str) -> None:
    """Distinct message with the fix for each failure (FR-10.4). The runtime's own error text
    is only matched against, never shown or logged: it could echo part of a prompt."""
    if r.status_code < 300:
        return
    err = error_text(r)
    if r.status_code == 404 or "not found" in err:
        raise ModelNotFound(f"the model {model} is not installed. Run: nabu models pull {model}")
    if "memory" in err:
        raise ModelUnavailable(
            f"the model {model} ran out of memory. Close other programs, or use a smaller model: "
            "run `nabu models list` to see the options."
        )
    raise ModelUnavailable(f"the local model runtime returned an error (HTTP {r.status_code})")


class OllamaRuntime:
    name = "ollama"

    def __init__(self, cfg: Config, timeout_s: float) -> None:
        self._http = LoopbackHttp(cfg, timeout_s)

    def close(self) -> None:
        self._http.close()

    def available(self) -> bool:
        try:
            return self._http.request("GET", "/api/tags").status_code == 200
        except ModelUnavailable:
            return False

    def models(self) -> list[str]:
        r = self._http.request("GET", "/api/tags")
        if r.status_code != 200:
            raise ModelUnavailable(f"the local model runtime returned an error (HTTP {r.status_code})")
        return [m.get("name", "") for m in r.json().get("models", [])]

    def chat(self, req: ChatRequest) -> str:
        user: dict = {"role": "user", "content": req.user}
        if req.images:
            user["images"] = [base64.b64encode(i).decode("ascii") for i in req.images]
        body: dict = {
            "model": req.model,
            "stream": False,
            "messages": [{"role": "system", "content": req.system}, user],
            "options": {"temperature": req.temperature},
        }
        if req.schema is not None:
            body["format"] = req.schema
        if req.disable_thinking:
            body["think"] = False
        r = self._http.request("POST", "/api/chat", body)
        raise_for_model_error(r, req.model)
        content = (r.json().get("message") or {}).get("content")
        return content if isinstance(content, str) else ""

    def pull(self, model: str) -> Iterator[PullProgress]:
        for line in self._http.stream_json_lines("POST", "/api/pull", {"model": model, "stream": True}):
            if "_status" in line or "error" in line:
                if "not found" in str(line.get("_error") or line.get("error") or "").lower():
                    raise ModelNotFound(f"the model {model} does not exist in the model library")
                raise ModelUnavailable(f"downloading {model} failed")
            yield PullProgress(status=str(line.get("status", "")),
                               completed=line.get("completed"), total=line.get("total"))
