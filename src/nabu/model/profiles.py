"""Model profiles: what differs between model families, kept as data (AD-3, FR-10.6).

Adding a model is a profile entry, not code. A profile is picked by model name (the longest
matching prefix wins) or named in config (`model_profile`). Users add or override profiles in
config.json under `model_profiles`. A model no profile matches gets GENERIC, which works with
any local vision model: boxes come from OCR words (AD-2), so ignoring the model's own boxes
loses only the fallback highlight.

`coords` says how the model writes boxes:
- "pixels": pixel coordinates of the image it received, top-left origin
- "grid_1000": 0-1000 relative grid
- "unit": 0-1 fractions
- "none": the model's boxes are ignored

Every built-in profile uses "none" until the M0 spike confirms the convention on real pages.
Model cards do not state it reliably, and some models count pixels of an image they resized
internally. `python -m nabu.model.evaluate` reports which convention fits a model's boxes;
set it with a profile override once it is measured.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nabu.errors import ConfigError

Coords = Literal["pixels", "grid_1000", "unit", "none"]


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    match: tuple[str, ...] = ()  # model-name prefixes, lower case
    coords: Coords = "none"
    disable_thinking: bool = False  # the model thinks by default; turn it off for JSON tasks
    structured_output: bool = True  # send the JSON schema to the runtime (Ollama `format`)
    max_image_edge_px: int | None = Field(default=None, ge=256, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    note: str = ""


GENERIC = ModelProfile(name="generic", note="Any local vision model. Model boxes ignored.")

BUILTIN: tuple[ModelProfile, ...] = (
    # Default family (Apache-2.0). Thinking is on by default per the model card; it slows
    # every call and adds text around the JSON, so it is turned off.
    ModelProfile(name="qwen3.5", match=("qwen3.5",), disable_thinking=True,
                 note="Default family. Apache-2.0, 201 languages."),
    ModelProfile(name="qwen3-vl", match=("qwen3-vl",), note="Apache-2.0."),
    ModelProfile(name="qwen2.5vl", match=("qwen2.5vl", "qwen2.5-vl"),
                 note="3b is Qwen Research License (non-commercial); 7b is Apache-2.0."),
    ModelProfile(name="gemma4", match=("gemma4", "gemma-4"), note="Apache-2.0."),
    ModelProfile(name="granite-vision", match=("granite-vision", "granite3.2-vision"),
                 note="Apache-2.0. Trained on English only."),
    GENERIC,
)


def _base_name(model: str) -> str:
    """'Qwen/Qwen3.5-4B' -> 'qwen3.5-4b'; 'qwen3.5:4b' stays as it is."""
    return model.strip().lower().rsplit("/", 1)[-1]


def resolve_profile(model: str, name: str = "auto",
                    custom: Sequence[ModelProfile] = ()) -> ModelProfile:
    """Pick the profile for a model. User profiles win over built-in ones with the same name
    or an equally long prefix."""
    profiles = [*custom, *BUILTIN]
    if name != "auto":
        for p in profiles:
            if p.name == name:
                return p
        known = ", ".join(sorted({p.name for p in profiles}))
        raise ConfigError(f"unknown model_profile {name!r}; known profiles: {known}")
    base = _base_name(model)
    best, best_len = GENERIC, 0
    for p in profiles:
        for prefix in p.match:
            if base.startswith(prefix) and len(prefix) > best_len:
                best, best_len = p, len(prefix)
    return best
