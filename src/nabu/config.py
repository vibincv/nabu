"""Configuration (DD-5). Loaded from config.json; flags and env vars override (FR-10.1).

The model endpoint must be a loopback address (AR-3). Nabu refuses to start otherwise.
"""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nabu.errors import ConfigError
from nabu.model.profiles import ModelProfile

LOOPBACK_NAMES = frozenset({"localhost"})


def is_loopback_host(host: str) -> bool:
    """True for 'localhost' and any 127.0.0.0/8 or ::1 literal. No DNS lookup is made."""
    host = host.strip("[]").lower()
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_endpoint(url: str) -> tuple[str, int]:
    """Return (host, port) for a model endpoint URL, or raise ConfigError if it is not loopback."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ConfigError(f"model_endpoint is not a valid http URL: {url}")
    if not is_loopback_host(parts.hostname):
        raise ConfigError(
            f"model_endpoint must be on this machine (localhost or 127.0.0.1); got {parts.hostname}. "
            "Nabu never sends documents to another machine."
        )
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.hostname, port


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())  # model_* keys are ours

    model: str | None = None  # set by the installer or `nabu models use`; never hard-coded (FR-10.2)
    model_endpoint: str = "http://127.0.0.1:11434"
    model_runtime: Literal["ollama", "openai_compat"] = "ollama"
    model_profile: str = "auto"  # "auto" picks by model name (nabu.model.profiles)
    model_profiles: list[ModelProfile] = Field(default_factory=list)  # user-added profiles
    model_timeout_s: float = Field(default=300.0, gt=0, le=3600)
    dpi: int = 200
    max_image_edge_px: int = 1500
    link_threshold: float = 0.75  # provisional, FR-5.3
    similar_threshold: float = 0.40  # provisional
    ambiguity_margin: float = 0.05  # provisional
    anchor_tolerance: float = 0.03  # provisional
    review_confidence: float = 0.6  # provisional
    template_reread: bool = True  # pending Q6
    ocr_engine: str = Field(default="auto", pattern="^(auto|rapidocr|tesseract)$")
    ocr_languages: list[str] = Field(default_factory=lambda: ["en"])
    ui_port: int = 8765
    upload_limit_mb: int = 100
    telemetry: bool = False  # always false; present for transparency
    first_run_done: bool = False  # UX-2.14 screen seen (FRD addition, M4)
    model_seconds_per_page: float | None = None  # measured by the installer (MH-6; FRD addition)

    @field_validator("model_endpoint")
    @classmethod
    def _endpoint_is_loopback(cls, v: str) -> str:
        parse_endpoint(v)
        return v

    @field_validator("telemetry")
    @classmethod
    def _telemetry_off(cls, v: bool) -> bool:
        if v:
            raise ConfigError("telemetry cannot be enabled; Nabu has none.")
        return v

    @property
    def endpoint(self) -> tuple[str, int]:
        return parse_endpoint(self.model_endpoint)


def load_config(path: Path | None, overrides: dict | None = None) -> Config:
    """Order of precedence: overrides (CLI flags) > NABU_* env vars > config file > defaults."""
    data: dict = {}
    if path is not None and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"config file is not valid JSON: {path.name} (line {e.lineno})") from None
    env_map = {"NABU_MODEL": "model", "NABU_MODEL_ENDPOINT": "model_endpoint",
               "NABU_MODEL_RUNTIME": "model_runtime"}
    for env, key in env_map.items():
        if os.environ.get(env):
            data[key] = os.environ[env]
    data.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return parse_config(data)


def parse_config(data: dict) -> Config:
    """Validate config data; every failure is a ConfigError with a one-line message."""
    if not isinstance(data, dict):
        raise ConfigError("config file must hold a JSON object")
    try:
        return Config(**data)
    except ConfigError:
        raise
    except Exception as e:  # pydantic ValidationError wraps our ConfigError
        cause = getattr(e, "errors", None)
        if cause:
            first = e.errors()[0]  # type: ignore[attr-defined]
            ctx_err = first.get("ctx", {}).get("error")
            if isinstance(ctx_err, ConfigError):
                raise ctx_err from None
            where = ".".join(map(str, first["loc"]))
            raise ConfigError(f"config value invalid: {where}: {first['msg']}") from None
        raise
