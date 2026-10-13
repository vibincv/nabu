"""The no-values guard (AR-7, FR-11.6, DD-2.7).

Before the store writes a template or a translation-memory entry, every string in the payload is
compared with every document value registered in the session. A match refuses the write.

Matching rules:
- Strings are normalised: Unicode NFKC, case-folded, whitespace collapsed.
- A payload string equal to a value is refused.
- A payload string that *contains* a value is refused when the value is at least
  MIN_SUBSTRING_LEN characters, so short values ("1", "DE") do not block ordinary labels.
- The same containment check runs again on a compact form of both sides: accents dropped and
  everything but letters and digits removed. "RE 2026 0412", "RE20260412" and the slug
  "re_2026_0412" all match the value "RE-2026-0412"; "beispiel-burobedarf-gmbh" matches
  "Beispiel Bürobedarf GmbH".

Every string is checked, whatever its key, except strings under FIXED_SHAPES keys that match
their key's shape (an ISO code, a timestamp, an enum). Those shapes cannot carry identifying text,
and checking them would refuse ordinary saves: the region "DE" equals the value "DE", and a
timestamp contains today's date. A string under such a key that does not fit the shape is checked
like any other. Slugs (`id`, `key`, `document_type_key`, `format.id`) are derived from names and
can carry a value, so they are always checked.

Known limits:
- FRD Q22: this only catches values Nabu identified as field values in this session.
  Identifying text that was never a field value (a letterhead, an employer name used as a printed
  label) passes. The save dialog shows every stored label so the user can see it (FR-7.1).
- A value rewritten in another format (the date "01.10.2026" stored as "2026-10-01", an amount
  written out in words) is not detected.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator

from nabu.errors import ValueWriteRefused

MIN_SUBSTRING_LEN = 4
_ws = re.compile(r"\s+")
_non_alnum = re.compile(r"[\W_]+")


def _enum(*names: str) -> re.Pattern[str]:
    return re.compile("|".join(map(re.escape, names)))


_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")

# Keys whose strings are skipped when they match the key's shape (DD-1, DD-2, DD-4).
FIXED_SHAPES: dict[str, re.Pattern[str]] = {
    "schema_version": re.compile(r"\d+(?:\.\d+)*"),
    "region": re.compile(r"[A-Z]{2}"),  # ISO 3166-1 alpha-2 (DD-2.8)
    "lang": re.compile(r"[a-z]{2}"),  # ISO 639-1
    "created_at": _TIMESTAMP,
    "updated_at": _TIMESTAMP,
    "added_at": _TIMESTAMP,
    "changed_at": _TIMESTAMP,
    "source": _enum("template", "model", "model_reread", "discovery_rules", "user"),  # DD-1.2
    "box_source": _enum("ocr", "model", "text_layer"),  # DD-1.2
    "status": _enum("from_template", "suggested", "needs_review", "not_found", "not_translated",
                    "edited_by_user"),  # DD-1.3
}


def normalise(s: str) -> str:
    return _ws.sub(" ", unicodedata.normalize("NFKC", s)).strip().casefold()


def compact(s: str) -> str:
    """Letters and digits only, accents dropped. Applied to normalised strings."""
    decomposed = unicodedata.normalize("NFKD", s)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _non_alnum.sub("", no_marks)


def _is_fixed_shape(key: str | None, s: str) -> bool:
    shape = FIXED_SHAPES.get(key or "")
    return shape is not None and shape.fullmatch(s) is not None


def _strings(obj: object, key: str | None = None) -> Iterator[tuple[str, str]]:
    if isinstance(obj, str):
        if not _is_fixed_shape(key, obj):
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
    vals = [(v, compact(v)) for v in values if v]
    if not vals:
        return []
    hits: list[str] = []
    for key, s in _strings(payload):
        ns = normalise(s)
        if not ns:
            continue
        cs = compact(ns)
        for v, cv in vals:
            if (ns == v
                    or (len(v) >= MIN_SUBSTRING_LEN and v in ns)
                    or (len(cv) >= MIN_SUBSTRING_LEN and cv in cs)):
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
