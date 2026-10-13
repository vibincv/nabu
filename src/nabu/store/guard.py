"""The no-values guard (AR-7, FR-11.6, DD-2.7).

Before the store writes a template or a translation-memory entry, every string in the payload is
compared with every document value registered in the session. A match refuses the write.

Matching rules:
- Strings are normalised: Unicode NFKC, case-folded, whitespace collapsed.
- A payload string equal to a value is refused.
- A payload string that *contains* a value is refused when the value is at least
  MIN_SUBSTRING_LEN characters, so short values ("1", "DE") do not block ordinary labels.

Known limit (FRD Q22): this only catches values Nabu identified as field values in this session.
Identifying text that was never a field value (a letterhead, an employer name used as a printed
label) passes. The save dialog shows every stored label so the user can see it (FR-7.1).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator

from nabu.errors import ValueWriteRefused

MIN_SUBSTRING_LEN = 4
_ws = re.compile(r"\s+")

# Keys whose string values are structural, not document content. Never compared.
STRUCTURAL_KEYS = frozenset(
    {"schema_version", "id", "key", "document_type_key", "value_type", "created_at", "updated_at",
     "added_at", "changed_at", "lang", "status", "source", "box_source",
     # region is validated as two capital letters and cannot carry identifying text
     "region"}
)


def normalise(s: str) -> str:
    return _ws.sub(" ", unicodedata.normalize("NFKC", s)).strip().casefold()


def _strings(obj: object, key: str | None = None) -> Iterator[tuple[str, str]]:
    if isinstance(obj, str):
        if key not in STRUCTURAL_KEYS:
            yield (key or "", obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, str(k))
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _strings(v, key)


def find_values(payload: object, values: Iterable[str]) -> list[str]:
    """Return the payload keys whose strings contain a session value. Values themselves are
    never returned, so the result is safe to log or show."""
    vals = [v for v in values if v]
    if not vals:
        return []
    hits: list[str] = []
    for key, s in _strings(payload):
        ns = normalise(s)
        if not ns:
            continue
        for v in vals:
            if ns == v or (len(v) >= MIN_SUBSTRING_LEN and v in ns):
                hits.append(key)
                break
    return hits


def assert_no_values(payload: object, values: Iterable[str], what: str) -> None:
    hits = find_values(payload, values)
    if hits:
        fields = ", ".join(sorted(set(hits)))
        raise ValueWriteRefused(
            f"refused to save {what}: it would store a document value (in: {fields}). "
            "Templates and translation memory never hold values."
        )
