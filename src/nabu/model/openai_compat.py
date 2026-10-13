"""OpenAI-compatible runtime adapter: llama.cpp server, LM Studio, vLLM, LocalAI.

Uses /v1/models and /v1/chat/completions. The endpoint may be given with or without a trailing
/v1. Still loopback only (AR-3): this is the local server's API shape, not a cloud service.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator

from nabu.config import Config
from nabu.errors import ModelUnavailable, NabuError
from nabu.model.http import LoopbackHttp
from nabu.model.ollama import raise_for_model_error
from nabu.model.runtime import ChatRequest, PullProgress


def _mime(data: bytes) -> str:
    return "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"


class OpenAICompatRuntime:
    name = "openai_compat"

    def __init__(self, cfg: Config, timeout_s: float) -> None:
        self._http = LoopbackHttp(cfg, timeout_s)
        self._prefix = "" if self._http.base.endswith("/v1") else "/v1"

    def close(self) -> None:
        self._http.close()

    def available(self) -> bool:
        try:
            return self._http.request("GET", f"{self._prefix}/models").status_code == 200
        except ModelUnavailable:
            return False

    def models(self) -> list[str]:
        r = self._http.request("GET", f"{self._prefix}/models")
        if r.status_code != 200:
            raise ModelUnavailable(f"the local model runtime returned an error (HTTP {r.status_code})")
        return [m.get("id", "") for m in r.json().get("data", [])]

    def chat(self, req: ChatRequest) -> str:
        content: list[dict] = [{"type": "text", "text": req.user}]
        for img in req.images:
            url = f"data:{_mime(img)};base64,{base64.b64encode(img).decode('ascii')}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        body: dict = {
            "model": req.model,
            "stream": False,
            "temperature": req.temperature,
            "messages": [{"role": "system", "content": req.system},
                         {"role": "user", "content": content}],
        }
        if req.schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "nabu", "schema": req.schema}}
        if req.disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        r = self._http.request("POST", f"{self._prefix}/chat/completions", body)
        raise_for_model_error(r, req.model)
        choices = r.json().get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content")
        return text if isinstance(text, str) else ""

    def pull(self, model: str) -> Iterator[PullProgress]:
        raise NabuError("this runtime does not download models through Nabu; "
                        "load the model with the runtime's own tool")
