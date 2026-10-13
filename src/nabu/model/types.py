"""Data passed to and from the model client (FRD 10.4).

Boxes are [x0, y0, x1, y1] on the 0-1000 page grid, top-left origin (DD-1.1). Fields that hold
document text are left out of repr, so a stray log line or traceback cannot print a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, get_args

Box = tuple[int, int, int, int]
ValueType = Literal["name", "id", "number", "date", "amount", "address", "text"]
VALUE_TYPES: frozenset[str] = frozenset(get_args(ValueType))
TranslationStatus = Literal["translated", "low_confidence", "untranslated"]


@dataclass(frozen=True)
class PageImage:
    """An encoded page image (PNG or JPEG) held in memory only (FR-3.6)."""

    data: bytes = field(repr=False)
    width_px: int
    height_px: int
    page: int = 1


@dataclass(frozen=True)
class DiscoveredField:
    label: str = field(repr=False)
    value: str | None = field(repr=False)
    value_type: ValueType
    box: Box | None  # converted per profile; None when the profile ignores model boxes
    raw_box: tuple[float, float, float, float] | None  # as the model wrote it (evaluation only)
    confidence: float


@dataclass(frozen=True)
class PageDiscovery:
    fields: list[DiscoveredField]
    type_guess: str | None = field(default=None, repr=False)
    country_guess: str | None = None  # ISO 3166-1 alpha-2 or None


@dataclass(frozen=True)
class CropField:
    """What the crop re-read needs to know about a template field (AD-6)."""

    name: str
    printed_label: str
    value_type: ValueType


@dataclass(frozen=True)
class FieldReading:
    value: str | None = field(repr=False)
    box: Box | None
    confidence: float


@dataclass(frozen=True)
class TranslateItem:
    id: str
    text: str = field(repr=False)


@dataclass(frozen=True)
class Translation:
    id: str
    english: str = field(repr=False)
    status: TranslationStatus
