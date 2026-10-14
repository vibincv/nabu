"""Snap model values to OCR word boxes (AD-2). M1.

The model returns value text; Nabu finds the run of consecutive OCR words on the page that matches
it and uses their box (box_source "ocr"). Matching is on the compact form (case, accents, spaces
and punctuation ignored), so "1.428,00 EUR" matches the words "1.428,00" "EUR". When no run
matches, a near match (one character off in a long value) is accepted; otherwise the model's own
box is used when the profile trusts it (box_source "model"), else no box.
"""

from __future__ import annotations

from dataclasses import dataclass

from nabu.model.types import Box
from nabu.ocr.words import Page, Word, union
from nabu.store.guard import compact

MAX_RUN = 12  # words in one value


@dataclass(frozen=True)
class Grounding:
    box: Box | None
    box_source: str | None  # "ocr" | "model" | None
    exact: bool


def _distance_at_most_one(a: str, b: str) -> bool:
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


def _runs(words: list[Word]):  # type: ignore[no-untyped-def]
    for i in range(len(words)):
        acc = ""
        for j in range(i, min(len(words), i + MAX_RUN)):
            acc += compact(words[j].text)
            yield i, j, acc


def find_run(value: str, words: list[Word], near: Box | None = None) -> tuple[Box | None, bool]:
    """Box of the OCR word run matching `value`, preferring the run nearest `near`.
    Returns (box, exact)."""
    target = compact(value)
    if not target:
        return None, False
    exact: list[Box] = []
    close: list[Box] = []
    for i, j, acc in _runs(words):
        if len(acc) > len(target) + 1:
            continue
        box = union([w.box for w in words[i:j + 1]])
        if box is None:
            continue
        if acc == target:
            exact.append(box)
        elif len(target) >= 6 and _distance_at_most_one(acc, target):
            close.append(box)
    # a value inside one longer word ("Datum:01.10.2026" read as one word)
    if not exact:
        for w in words:
            if w.box is not None and len(target) >= 4 and target in compact(w.text):
                exact.append(w.box)
    pool, is_exact = (exact, True) if exact else (close, False)
    if not pool:
        return None, False
    if near is None:
        return pool[0], is_exact
    cx, cy = (near[0] + near[2]) / 2, (near[1] + near[3]) / 2
    return min(pool, key=lambda b: ((b[0] + b[2]) / 2 - cx) ** 2 + ((b[1] + b[3]) / 2 - cy) ** 2), is_exact


def ground(value: str | None, page: Page, model_box: Box | None) -> Grounding:
    if value:
        box, exact = find_run(value, page.words, near=model_box)
        if box is not None:
            return Grounding(box, "ocr", exact)
    if model_box is not None:
        return Grounding(model_box, "model", False)
    return Grounding(None, None, False)


def label_box(label: str, page: Page) -> Box | None:
    box, _ = find_run(label, page.words)
    return box
