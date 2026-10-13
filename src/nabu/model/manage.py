"""Choosing and downloading models (FR-10.2, FR-10.5). Library code; the CLI only prints."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from nabu.config import Config, parse_config
from nabu.errors import ModelUnavailable
from nabu.model.profiles import resolve_profile
from nabu.model.runtime import PullProgress, make_runtime, same_model
from nabu.model.tiers import Tier, recommend
from nabu.store.store import Store


@dataclass(frozen=True)
class ModelListing:
    runtime: str
    runtime_present: bool
    installed: list[str]
    active: str | None
    active_profile: str | None
    recommended: Tier


def listing(cfg: Config, ram_gb: float | None) -> ModelListing:
    runtime = make_runtime(cfg, timeout_s=5.0)
    try:
        present = runtime.available()
        try:
            installed = runtime.models() if present else []
        except ModelUnavailable:
            installed = []
    finally:
        runtime.close()
    profile = (resolve_profile(cfg.model, cfg.model_profile, cfg.model_profiles).name
               if cfg.model else None)
    return ModelListing(runtime=cfg.model_runtime, runtime_present=present, installed=installed,
                        active=cfg.model, active_profile=profile, recommended=recommend(ram_gb))


def use(store: Store, name: str, runtime: str | None = None, profile: str | None = None,
        endpoint: str | None = None) -> tuple[Config, bool | None]:
    """Make `name` the active model. Other config keys are kept. Returns the new config and
    whether the runtime has the model (None if the runtime is not answering)."""
    data = store.config_data()
    data["model"] = name
    for key, value in (("model_runtime", runtime), ("model_profile", profile),
                       ("model_endpoint", endpoint)):
        if value is not None:
            data[key] = value
    cfg = parse_config(data)
    resolve_profile(cfg.model or "", cfg.model_profile, cfg.model_profiles)  # unknown name fails
    store.save_config(data)
    rt = make_runtime(cfg, timeout_s=5.0)
    try:
        if not rt.available():
            return cfg, None
        return cfg, any(same_model(m, name) for m in rt.models())
    finally:
        rt.close()


def pull(cfg: Config, name: str) -> Iterator[PullProgress]:
    runtime = make_runtime(cfg)
    try:
        yield from runtime.pull(name)
    finally:
        runtime.close()
