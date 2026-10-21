"""Score a document against every template; link outcome (FR-5.1 to FR-5.4). No model calls.

Score = share of the template's anchors found on the document. Anchors are the printed labels
and the landmarks (fixed printed text that is not a value). Each is looked up on its page, one
scale + shift is fitted from the matches (a photo is framed differently each time), and an
anchor counts when it sits where the fit puts it, within the anchor tolerance (templates.align).
Only words and boxes from reading are used, so linking needs no model (FR-5.1).

- Fewer pages than the template: scored on the pages present; the missing pages are reported.
- More pages, or a page of another shape (aspect ratio differs by more than SHAPE_TOLERANCE),
  or a paginated document against a label-only template (and the reverse): score 0.
- Office and text files (AD-15): an anchor counts when its label appears anywhere.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from nabu.config import Config
from nabu.ocr.words import Page, Reading
from nabu.templates import align, describe, fold, header, label_matches

log = logging.getLogger(__name__)

SHAPE_TOLERANCE = 0.10  # relative aspect-ratio difference; provisional, like FR-5.3's values


def paginated(reading: Reading) -> bool:
    return bool(reading.pages) and all(p.width_px and p.height_px for p in reading.pages)


def aspect(page: Page) -> float:
    return round((page.width_px or 1) / (page.height_px or 1), 3)


def page_shapes(reading: Reading) -> list[dict] | None:
    """The `pages` entry of a template header: aspect ratio per page, null for AD-15 files."""
    if not paginated(reading):
        return None
    return [{"aspect": round(aspect(p), 2)} for p in reading.pages]


def find_in_lines(label: str, page: Page) -> tuple[bool, str | None]:
    """Label-only lookup for office and text files (AD-15): a table cell that is the label (the
    value is the next non-empty cell), or a line that starts with it (the value is the rest of
    the line). Returns (label found, value or None)."""
    target = fold(label)
    if not target:
        return False, None
    for line in page.lines:
        if line.cells is not None:
            cells = list(line.cells)
            for i, c in enumerate(cells):
                if label_matches(c.rstrip(":： "), label):
                    rest = [x.strip() for x in cells[i + 1:] if x.strip()]
                    return True, rest[0] if rest else None
            continue
        words = list(line.words)
        acc = ""
        for j, w in enumerate(words):
            acc += fold(w.text)
            if acc == target:
                rest = " ".join(x.text for x in words[j + 1:]).strip().lstrip(":：").strip()
                return True, rest or None
            if len(acc) >= len(target):
                break
    return False, None


def label_on_page(label: str, page: Page) -> bool:
    return find_in_lines(label, page)[0]


@dataclass
class Score:
    value: float
    missing_pages: list[int] = field(default_factory=list)


def score(reading: Reading, t: dict, cfg: Config) -> Score:
    shapes = header(t).get("pages")
    fields = t.get("fields") or []
    if shapes is None:  # label-only template (AD-15)
        if paginated(reading):
            return Score(0.0)
        labels = [f["anchor"]["printed_label"] for f in fields
                  if (f.get("anchor") or {}).get("printed_label")]
        if not labels:
            return Score(0.0)
        found = sum(1 for lb in labels if any(label_on_page(lb, p) for p in reading.pages))
        return Score(found / len(labels))
    if not paginated(reading) or len(reading.pages) > len(shapes):
        return Score(0.0)
    for page, shape in zip(reading.pages, shapes, strict=False):
        want = shape.get("aspect") or 0
        if not want or abs(aspect(page) - want) / want > SHAPE_TOLERANCE:
            return Score(0.0)
    present = len(reading.pages)
    missing = list(range(present + 1, len(shapes) + 1))
    total = found = 0
    for page in reading.pages:  # labels and landmarks, placed through one fit per page
        pl = align.place(align.anchors(t, page.n), page, cfg.anchor_tolerance)
        total, found = total + pl.total, found + pl.found
    return Score(found / total if total else 0.0, missing)


@dataclass
class Link:
    outcome: str  # linked | ambiguous | similar | none (FR-5.4)
    template: dict | None = field(default=None, repr=False)  # linked or most similar template
    score: float = 0.0
    candidates: list[dict] = field(default_factory=list)
    missing_pages: list[int] = field(default_factory=list)
    chosen: bool = False  # the user picked it (FR-5.8)

    def to_dict(self) -> dict:
        d = describe(self.template) if self.template else {}
        return {"outcome": self.outcome,
                "template_id": d.get("template_id") if self.outcome == "linked" else None,
                "template_version": d.get("version") if self.outcome == "linked" else None,
                "score": round(self.score, 3), "candidates": self.candidates,
                "template": d or None, "missing_pages": self.missing_pages,
                "chosen": self.chosen}


def link(reading: Reading, templates: Sequence[dict], cfg: Config) -> Link:
    if not templates:
        return Link("none")
    scored = [(score(reading, t, cfg), t) for t in templates]
    scored.sort(key=lambda st: (-st[0].value, str(header(st[1]).get("id"))))

    def cand(st: tuple[Score, dict]) -> dict:
        return {**describe(st[1]), "score": round(st[0].value, 3)}

    best_score, best = scored[0]
    b = best_score.value
    log.info("link scores: %s", " ".join(f"{s.value:.2f}" for s, _ in scored))
    if b >= cfg.link_threshold:
        close = [st for st in scored
                 if st[0].value >= cfg.link_threshold and b - st[0].value <= cfg.ambiguity_margin]
        if len(close) > 1:
            return Link("ambiguous", best, b, [cand(st) for st in close])
        return Link("linked", best, b, [], best_score.missing_pages)
    if b >= cfg.similar_threshold:
        return Link("similar", best, b,
                    [cand(st) for st in scored if st[0].value >= cfg.similar_threshold])
    return Link("none", None, b)


def chosen(reading: Reading, t: dict, cfg: Config) -> Link:
    """The user picked this template (FR-5.8): linked whatever the score."""
    s = score(reading, t, cfg)
    return Link("linked", t, s.value, [], s.missing_pages, chosen=True)
