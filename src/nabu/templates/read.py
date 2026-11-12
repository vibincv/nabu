"""Read values at a template's anchors (FR-5.5); crop re-read of failed fields (FR-5.9, AD-6);
name suggestions and hidden labels from a similar template (FR-5.6, DD-2.5).

For each template field, in the template's order:
1. place the template page on this one (templates.align: one scale + shift fitted from the
   labels and landmarks found); find the printed label where the fit puts it, or the nearest
   copy; the value box is the label box plus value_offset. A field with no printed label is
   read at its page position through the same fit;
2. the value is the lines centred inside that box (sideways widened by the tolerance); only
   when none is, the one nearest line within the margin. Continued to the right along the line
   while the gap stays small, so a longer value is read whole. Words found as a label or a
   landmark of the template are printed card text, never part of a value;
3. office and text files: the rest of the line, or the next table cell, after the label.
A field with no value is "not found". With a model installed and template_reread on, only a crop
around the expected box is sent to the model (source model_reread); otherwise "needs review".
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from nabu.config import Config
from nabu.errors import ModelOutputInvalid, ModelUnavailable
from nabu.fields import grounding
from nabu.fields.types import Field
from nabu.lang import detect
from nabu.model.client import ModelClient
from nabu.model.types import Box, CropField
from nabu.ocr.words import GRID, Page, Reading, Word, lines_from_words, union
from nabu.templates import align, centre_in, find_label, fold, label_matches
from nabu.templates.link import find_in_lines, paginated

log = logging.getLogger(__name__)

LINE_GAP = 20  # grid units between words of one value on a line
ONE_ANCHOR = ("This template found too little fixed text on the page, so it cannot tell how far "
              "the photo is zoomed and the boxes may be on the wrong lines. Check every field. "
              "To fix it, delete the template and save it again, keeping fixed text near the top "
              "and the bottom of the form.")


def _shift(box: Box, by: Box) -> Box:
    return (box[0] + by[0], box[1] + by[1], box[0] + by[2], box[1] + by[3])


def _value_area(expected: Box, tol: float) -> Box:
    """Where the value's words may be centred. The box is already placed from the label found on
    this document, so the shift of the scan is compensated: sideways the full tolerance (values
    differ in length), vertically half the value's height only, so the next line never joins."""
    dx = round(tol * GRID)
    dy = max(2, (expected[3] - expected[1]) // 2)
    return (max(0, expected[0] - dx), max(0, expected[1] - dy),
            min(GRID, expected[2] + dx), min(GRID, expected[3] + dy))


def _cy(b: Box) -> float:
    return (b[1] + b[3]) / 2


def _value_words(page: Page, expected: Box, tol: float, skip: set[int]) -> list[Word]:
    words = page.words
    area = _value_area(expected, tol)
    picked = [i for i, w in enumerate(words)
              if i not in skip and w.box is not None and centre_in(w.box, area)]
    inside = [i for i in picked if expected[1] <= _cy(words[i].box) <= expected[3]]  # type: ignore[arg-type]
    if not inside and picked:  # the value moved a little: the one nearest line, never two
        mid = _cy(expected)
        near = min(picked, key=lambda i: abs(_cy(words[i].box) - mid))  # type: ignore[arg-type]
        nb = words[near].box
        assert nb is not None
        inside = [i for i in picked if nb[1] <= _cy(words[i].box) <= nb[3]]  # type: ignore[arg-type]
    if not inside:
        return []
    chosen = set(inside)
    grown = True
    while grown:  # continue to the right along the same line
        grown = False
        right = max((words[i] for i in chosen), key=lambda w: w.box[2])  # type: ignore[index]
        rb = right.box
        assert rb is not None
        for i, w in enumerate(words):
            if i in chosen or i in skip or w.box is None:
                continue
            cy = (w.box[1] + w.box[3]) / 2
            if rb[1] <= cy <= rb[3] and 0 <= w.box[0] - rb[2] <= LINE_GAP:
                chosen.add(i)
                grown = True
                break
    return [words[i] for i in sorted(chosen)]


def _text(words: list[Word]) -> str | None:
    text = " ".join(" ".join(w.text for w in line.words) for line in lines_from_words(words))
    return text.strip().lstrip(":：").strip() or None


def _read_paginated(page: Page, anchor: dict, tol: float, fit: align.Fit,
                    hit: tuple[Box, int, int] | None, printed_text: set[int]) -> tuple[
                        str | None, Box | None, Box | None, str | None]:
    """(value, value box, expected box, label as printed on this document). `fit` places the
    template page on this one; `hit` is the label where the fit expects it, if found there;
    `printed_text` the words found as the template's labels and landmarks."""
    label, abox, offset = anchor.get("printed_label"), anchor.get("box"), anchor.get("value_offset")
    if offset is None:
        return None, None, None, None
    expected: Box | None = None
    skip = set(printed_text)
    printed = None
    if label and abox:
        a = fit.box(tuple(abox))  # type: ignore[arg-type]
        hit = hit or find_label(label, page.words, near=a)  # moved further: the nearest copy
        if hit is not None:
            lb, i, j = hit
            skip |= set(range(i, j + 1))
            printed = " ".join(w.text for w in page.words[i:j + 1]).rstrip(":： ")
            expected = _shift(lb, fit.offset(tuple(offset)))  # type: ignore[arg-type]
        else:  # label not found: where it would be
            expected = fit.box(_shift(tuple(abox), tuple(offset)))  # type: ignore[arg-type]
    else:
        expected = fit.box(tuple(offset))  # type: ignore[arg-type]  # no label: page position
    assert expected is not None
    expected = tuple(max(0, min(GRID, v)) for v in expected)  # type: ignore[assignment]
    words = _value_words(page, expected, tol, skip)
    if not words:
        return None, None, expected, printed
    return _text(words), union([w.box for w in words]), expected, printed


def read_linked(reading: Reading, t: dict, cfg: Config, model: ModelClient | None,
                missing_pages: list[int], messages: list[str],
                cancelled: Callable[[], bool] = lambda: False) -> tuple[list[Field], bool]:
    """Fields of template `t` read from the document, in the template's order.
    Returns (fields, model used)."""
    by_n = {p.n: p for p in reading.pages}
    fields: list[Field] = []
    model_used = False
    rereads: list[tuple[Field, Page, Box]] = []
    placed: dict[int, tuple[align.Placement, dict[int, tuple[Box, int, int]], set[int]]] = {}
    if paginated(reading):  # one fit per page, from its labels and landmarks
        for p in reading.pages:
            items = align.anchors(t, p.n)
            pl = align.place(items, p, cfg.anchor_tolerance, align.page_aspect(t, p.n))
            placed[p.n] = (pl, {items[k].field: h for k, h in pl.hits.items()  # type: ignore[misc]
                                if items[k].field is not None},
                           {n for _, i, j in pl.hits.values() for n in range(i, j + 1)})
    for i, tf in enumerate(t.get("fields") or [], 1):
        a = tf.get("anchor") or {}
        label = a.get("printed_label")
        tol = a.get("tolerance") or cfg.anchor_tolerance
        value = box = expected = None
        printed = None
        supported = False  # a label-less value placed by anchors found on this document
        page_n = a.get("page") or 1
        page = by_n.get(page_n)
        if page is not None and page_n not in missing_pages:
            if paginated(reading):
                pl, label_hits, printed_text = placed.get(page_n, (align.Placement(), {}, set()))
                value, box, expected, printed = _read_paginated(page, a, tol, pl.fit,
                                                                label_hits.get(i - 1), printed_text)
                supported = not (label and a.get("box")) and pl.found > 0 and pl.zoom_known
                if not (label and a.get("box")) and pl.found > 0 and not pl.zoom_known \
                        and ONE_ANCHOR not in messages:
                    messages.append(ONE_ANCHOR)
            elif label:
                for p in reading.pages:
                    found, value = find_in_lines(label, p)
                    if found:
                        page, page_n, printed = p, p.n, label
                        break
        f = Field(id=f"f{i}", name=tf["name"], printed_label=printed or label, value=value,
                  value_type=tf.get("value_type", "text"), page=page_n, source="template",
                  confidence=1.0 if value is not None and (printed or supported) else 0.6,
                  lang=detect.field_language(printed or label or "", value,
                                             page.lang if page else None),
                  box=box, box_source=_box_source(page) if box else None,
                  status=["from_template"], template_key=tf.get("key"))
        if value is None:
            f.flag("not_found")
            if (model is not None and cfg.template_reread and page is not None
                    and page.image is not None and expected is not None):
                rereads.append((f, page, expected))
            else:
                f.flag("needs_review")
        elif not printed and not supported:
            f.flag("needs_review")  # read where the label used to be, nothing seen to confirm
        fields.append(f)
    for f, page, expected in rereads:  # FR-5.9: one crop per failed field, never the page
        if cancelled() or model is None:
            f.flag("needs_review")
            continue
        try:
            got = model.reread_crop(page.image, expected,  # type: ignore[arg-type]
                                    CropField(f.name, f.printed_label or "", f.value_type))
        except ModelUnavailable as e:
            if e.message not in messages:
                messages.append(e.message)
            model = None
            f.flag("needs_review")
            continue
        except ModelOutputInvalid:
            f.flag("needs_review")
            continue
        model_used = True
        if not got.value:
            f.flag("needs_review")
            continue
        g = grounding.ground(got.value, page, got.box)
        f.value, f.box, f.box_source = got.value, g.box, g.box_source  # type: ignore[assignment]
        f.source, f.confidence = "model_reread", got.confidence
        f.status.remove("not_found")
        if not g.exact or got.confidence < cfg.review_confidence:
            f.flag("needs_review")
    return fields, model_used


def _box_source(page: Page) -> str:
    return "ocr" if page.source == "ocr" else "text_layer"


def apply_similar(fields: list[Field], t: dict) -> None:
    """FR-5.6 and DD-2.5 on discovered fields: a printed label that matches an anchor of the
    similar template gets that template's field name as a one-click suggestion; a label the
    user marked "Not required" in that template starts removed (the user can restore it)."""
    anchors = [(tf["anchor"]["printed_label"], tf["name"]) for tf in t.get("fields") or []
               if (tf.get("anchor") or {}).get("printed_label")]
    removed = [fold(lb) for lb in t.get("removed_labels") or []]
    for f in fields:
        if not f.printed_label:
            continue
        if fold(f.printed_label) in removed:
            f.removed = True
            continue
        for label, name in anchors:
            if label_matches(f.printed_label, label) and name != f.name:
                f.name_suggestion = name
                f.flag("suggested")
                break
