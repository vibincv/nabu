"""Model tier table (FRD 12.1, MH-1): the one place the recommended model per machine lives.

Default family: Qwen3.5 (Apache-2.0, commercial use allowed). Sizes are Ollama download sizes
(ollama.com/library/qwen3.5, checked 2026-10-13). The installer and `doctor` pick from this
table; the user can always choose another model (`nabu models use`).

doctor passes the largest NVIDIA GPU's VRAM; other GPUs are not detected and count as none.
qwen3.5:9b confirmed by the owner for >= 16 GB RAM with a >= 6 GB GPU (2026-10-14).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    hardware: str
    model: str | None
    download_gb: float | None
    behaviour: str
    offered: str | None = None  # the alternative offered to the user


TIERS: tuple[Tier, ...] = (
    Tier("< 8 GB RAM, no GPU", None, None, "No-model mode; the smallest model is offered",
         offered="qwen3.5:0.8b"),
    Tier("8-15 GB RAM, no GPU", "qwen3.5:2b", 3.1, "One page at a time"),
    Tier("16 GB RAM, no GPU (reference)", "qwen3.5:4b", 4.0,
         "CPU inference, one page at a time; templates make repeat documents fast",
         offered="qwen3.5:9b (slower, more accurate)"),
    Tier(">= 32 GB RAM, or >= 16 GB RAM with >= 6 GB VRAM", "qwen3.5:9b", 7.6,
         "GPU inference, or CPU with room to spare"),
    # The FRD put >= 32 GB RAM here too. A 27b model on CPU takes minutes per page, so this
    # tier needs a GPU (decided 2026-10-13).
    Tier(">= 16 GB VRAM", "qwen3.5:27b", 20.0, "Best accuracy"),
)


def recommend(ram_gb: float | None, vram_gb: float | None = None) -> Tier:
    if (vram_gb or 0) >= 16:
        return TIERS[4]
    if (ram_gb or 0) >= 32 or ((vram_gb or 0) >= 6 and (ram_gb or 0) >= 15.5):
        return TIERS[3]
    if ram_gb is None or ram_gb >= 15.5:  # "16 GB" machines report slightly less; unknown -> reference
        return TIERS[2]
    if ram_gb >= 7.5:
        return TIERS[1]
    return TIERS[0]
