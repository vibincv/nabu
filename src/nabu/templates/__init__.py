"""Templates: the only thing Nabu learns (AD-4). M3.

Shared here: label matching that tolerates case, spacing and common OCR confusions (FR-5.2),
slugs for keys and ids (DD-2.2, DD-2.8), and small readers of the DD-2 shape.

A template (DD-2) holds no values. Its header block also carries `pages` (each page's aspect
ratio, or null for office and text files) so that "a different page shape scores zero" (FR-5.2)
can be checked; this is an addition to DD-2, reported to the owner.
"""

from __future__ import annotations

import re
import unicodedata

from nabu.model.types import Box
from nabu.ocr.words import GRID, Word, union
from nabu.store.guard import compact, normalise

MAX_RUN = 12  # words in one printed label
_CONFUSIONS = str.maketrans({"o": "0", "l": "1", "i": "1"})
_slug_strip = re.compile(r"[^a-z0-9]+")


def fold(s: str) -> str:
    """Letters and digits only, case and accents dropped, 0/O and 1/l/I treated as one."""
    return compact(normalise(s)).translate(_CONFUSIONS)


def slug(s: str, sep: str = "_", fallback: str = "x") -> str:
    """ASCII slug that satisfies the store's rule ^[a-z0-9][a-z0-9_-]{0,63}$."""
    ascii_ = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    out = _slug_strip.sub(sep, ascii_).strip(sep)[:64].strip(sep)
    return out or fallback


def _near_one(a: str, b: str) -> bool:
    """Edit distance at most one."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = diffs = 0
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            diffs += 1
            if diffs > 1:
                return False
            if len(a) == len(b):
                i += 1
            j += 1
        else:
            i += 1
            j += 1
    return diffs + (len(b) - j) <= 1


def label_matches(text: str, label: str) -> bool:
    a, b = fold(text), fold(label)
    return bool(b) and (a == b or (len(b) >= 6 and _near_one(a, b)))


def centre_in(box: Box, area: Box) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


def widen(box: Box, by: float) -> Box:
    d = round(by * GRID)
    return (max(0, box[0] - d), max(0, box[1] - d), min(GRID, box[2] + d), min(GRID, box[3] + d))


def find_label(label: str, words: list[Word], near: Box | None = None,
               within: Box | None = None) -> tuple[Box, int, int] | None:
    """The run of words that spells `label`: (box, first word index, last word index).
    Prefers the run nearest `near`; with `within`, only runs centred inside it count."""
    target = fold(label)
    if not target:
        return None
    found: list[tuple[Box, int, int]] = []
    for i in range(len(words)):
        acc = ""
        for j in range(i, min(len(words), i + MAX_RUN)):
            acc += fold(words[j].text)
            if len(acc) > len(target) + 1:
                break
            if acc == target or (len(target) >= 6 and _near_one(acc, target)):
                box = union([w.box for w in words[i:j + 1]])
                if box is not None and (within is None or centre_in(box, within)):
                    found.append((box, i, j))
                break
    if not found:
        return None
    if near is None:
        return found[0]
    cx, cy = (near[0] + near[2]) / 2, (near[1] + near[3]) / 2
    return min(found, key=lambda r: ((r[0][0] + r[0][2]) / 2 - cx) ** 2
               + ((r[0][1] + r[0][3]) / 2 - cy) ** 2)


def header(t: dict) -> dict:
    return t.get("template") or {}


def describe(t: dict) -> dict:
    """What the review window shows about a template: never values (a template has none)."""
    h = header(t)
    return {"template_id": h.get("id"), "document_type": h.get("document_type"),
            "region": h.get("region"), "format": (h.get("format") or {}).get("name"),
            "version": h.get("version")}
