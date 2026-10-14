"""Discovery: all label-value pairs without a template (FR-4)."""

from __future__ import annotations

from collections import Counter

from nabu.fields.types import Field
from nabu.store.guard import compact, normalise


def _label_key(f: Field) -> str:
    return normalise(f.printed_label or f.name)


def merge(fields: list[Field]) -> list[Field]:
    """FR-4.6, before translation: the same printed label with the same value is one field (the
    first is kept). A field whose label equals its value (a heading echoed back) is dropped."""
    seen: set[tuple[str, str]] = set()
    kept: list[Field] = []
    for f in fields:
        if f.value is not None and compact(f.value) == compact(f.printed_label or ""):
            continue
        key = (_label_key(f), compact(f.value or ""))
        if key in seen:
            continue
        seen.add(key)
        kept.append(f)
    return kept


def number(fields: list[Field]) -> list[Field]:
    """FR-4.6, after translation: the same label with different values is named "Name 1",
    "Name 2", ... in reading order, so the user can keep or remove each one."""
    counts = Counter(_label_key(f) for f in fields)
    ordinal: Counter[str] = Counter()
    for f in fields:
        key = _label_key(f)
        if counts[key] > 1:
            ordinal[key] += 1
            f.name = f"{f.name} {ordinal[key]}"
    return fields
