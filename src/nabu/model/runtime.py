"""Runtime adapters: how Nabu talks to a local model server.

A runtime does one thing: send a system prompt, a user prompt and images, and return the reply
text. Prompts, validation and coordinates live in the client, so a new runtime is one small
class plus an entry in RUNTIMES.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from nabu.config import Config


@dataclass(frozen=True)
class ChatRequest:
    model: str
    system: str = field(repr=False)
    user: str = field(repr=False)
    images: tuple[bytes, ...] = field(default=(), repr=False)
    schema: dict | None = field(default=None, repr=False)  # JSON schema for structured output
    disable_thinking: bool = False
    temperature: float = 0.0


@dataclass(frozen=True)
class PullProgress:
    status: str
    completed: int | None = None
    total: int | None = None


class ModelRuntime(Protocol):
    name: str

    def available(self) -> bool:
        """True if the runtime answers."""
        ...

    def models(self) -> list[str]:
        """Installed model names."""
        ...

    def chat(self, req: ChatRequest) -> str:
        """The reply text. Raises ModelUnavailable / ModelNotFound with a fix in the message."""
        ...

    def pull(self, model: str) -> Iterator[PullProgress]:
        """Download a model through the runtime (FR-10.5). NabuError if the runtime can't."""
        ...

    def close(self) -> None: ...


def _ollama(cfg: Config, timeout_s: float) -> ModelRuntime:
    from nabu.model.ollama import OllamaRuntime

    return OllamaRuntime(cfg, timeout_s)


def _openai_compat(cfg: Config, timeout_s: float) -> ModelRuntime:
    from nabu.model.openai_compat import OpenAICompatRuntime

    return OpenAICompatRuntime(cfg, timeout_s)


RUNTIMES: dict[str, Callable[[Config, float], ModelRuntime]] = {
    "ollama": _ollama,
    "openai_compat": _openai_compat,  # llama.cpp server, LM Studio, vLLM, LocalAI
}


def make_runtime(cfg: Config, timeout_s: float | None = None) -> ModelRuntime:
    return RUNTIMES[cfg.model_runtime](cfg, cfg.model_timeout_s if timeout_s is None else timeout_s)


def same_model(a: str, b: str) -> bool:
    """Ollama lists 'qwen3.5:latest' for a model pulled as 'qwen3.5'."""
    def norm(s: str) -> str:
        s = s.strip().lower()
        return s if ":" in s else f"{s}:latest"

    return norm(a) == norm(b)
