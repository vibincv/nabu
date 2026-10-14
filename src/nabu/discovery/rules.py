"""Fixed rules for digital files: 'Label: value', form fields, 2-column tables. M1.

No model (FR-4.2, AD-9). Rules, in order, per line:
1. Table rows: two cells -> label, value. A table whose first row is all labels -> each later
   row gives "header: cell" pairs.
2. A line split into segments by wide horizontal gaps (PDF text layer): "Label:" segments take
   the text after the colon, or the next segment when nothing follows the colon; a 2-segment line
   whose first segment is label-like is "Label   value".
3. Plain lines: "Label: value"; text separated by a tab is a row.
A colon between digits (12:30) is not a separator. A label without a value is kept with an empty
value (FR-4.5). Nothing here knows a document type or a field name (NFR-10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nabu.fields import values
from nabu.model.types import Box
from nabu.ocr.words import FormField, Line, Page, Word, union

_COLON = re.compile(r"[:：]\s*$")
# A colon glued to its value ("Ref:A-77"): after a letter, "." or ")", not before "//" (URLs).
# A colon after a digit (12:30) never splits.
_INLINE_COLON = re.compile(r"(?<=[^\W\d_]|[.)])[:：](?!//)")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
MAX_LABEL_WORDS = 6
MAX_LABEL_CHARS = 60
GAP_CHARS = 2.5  # a gap wider than this many average character widths splits a line


@dataclass
class Pair:
    label: str
    value: str | None
    page: int
    box: Box | None  # the value's box, else the label's
    from_layout: bool  # box comes from page positions (text layer)
    confidence: float = 0.9


def label_like(s: str) -> bool:
    s = s.strip().rstrip(":：").strip()
    if not s or len(s) > MAX_LABEL_CHARS or len(s.split()) > MAX_LABEL_WORDS:
        return False
    if not _LETTER.search(s):
        return False
    return values.infer(s) in ("text", "id") and not values.parse_date(s, None)


def _segments(line: Line) -> list[list[Word]]:
    words = list(line.words)
    if not words or any(w.box is None for w in words):
        return [words]
    chars = sum(len(w.text) for w in words)
    span = sum(w.box[2] - w.box[0] for w in words)  # type: ignore[index]
    gap_limit = GAP_CHARS * max(1.0, span / max(1, chars))
    segs: list[list[Word]] = [[words[0]]]
    for prev, w in zip(words, words[1:], strict=False):
        if w.box[0] - prev.box[2] > gap_limit:  # type: ignore[index]
            segs.append([w])
        else:
            segs[-1].append(w)
    return segs


def _text(ws: list[Word]) -> str:
    return " ".join(w.text for w in ws).strip()


def _split_colon(ws: list[Word]) -> tuple[list[Word], list[Word]] | None:
    """Split words at the first word that ends a label with a colon."""
    for i, w in enumerate(ws):
        if _COLON.search(w.text) and _LETTER.search(_text(ws[:i + 1])):
            return ws[:i + 1], ws[i + 1:]
        m = _INLINE_COLON.search(w.text)
        if m and m.end() < len(w.text) and _LETTER.search(w.text[:m.start()]):
            # "Label:value" glued in one word
            head = Word(text=w.text[:m.start() + 1], box=w.box, conf=w.conf)
            tail = Word(text=w.text[m.end():].strip(), box=w.box, conf=w.conf)
            return ws[:i] + [head], [tail, *ws[i + 1:]]
    return None


def _pair(label_ws: list[Word], value_ws: list[Word], page: int) -> Pair | None:
    label = _text(label_ws).rstrip(":：").strip()
    if not label_like(label):
        return None
    value = _text(value_ws) or None
    box = union([w.box for w in value_ws]) if value_ws else union([w.box for w in label_ws])
    return Pair(label=label, value=value, page=page, box=box,
                from_layout=box is not None)


def _line_pairs(line: Line, page: int) -> list[Pair]:
    segs = _segments(line)
    out: list[Pair] = []
    i = 0
    while i < len(segs):
        seg = segs[i]
        split = _split_colon(seg)
        if split:
            label_ws, value_ws = split
            # "Label:" alone in its segment: the value is the next segment unless it is a label too
            if not value_ws and i + 1 < len(segs) and not _split_colon(segs[i + 1]):
                value_ws = segs[i + 1]
                i += 1
            p = _pair(label_ws, value_ws, page)
            if p:
                out.append(p)
        elif len(segs) == 2 and i == 0 and label_like(_text(seg)) and \
                not label_like_value(_text(segs[1])):
            p = _pair(seg, segs[1], page)
            if p:
                out.append(p)
            i += 1
        i += 1
    return out


def label_like_value(s: str) -> bool:
    """True when the right-hand text of a 2-segment line looks like another label ("Label:")."""
    return bool(_COLON.search(s))


def _table_pairs(rows: list[Line], page: int) -> list[Pair]:
    out: list[Pair] = []
    i = 0
    while i < len(rows):
        cells = [c for c in (rows[i].cells or ())]
        nonempty = [c for c in cells if c.strip()]
        if len(nonempty) == 2 and len(cells) <= 3 and label_like(nonempty[0]):
            out.append(Pair(label=nonempty[0].strip().rstrip(":："), value=nonempty[1].strip(),
                            page=page, box=None, from_layout=False))
            i += 1
            continue
        # header table: this row is all labels and the next rows have the same width
        block = [rows[i]]
        j = i + 1
        while j < len(rows) and rows[j].cells is not None and len(rows[j].cells or ()) == len(cells):
            block.append(rows[j])
            j += 1
        if len(cells) >= 2 and len(block) >= 2 and all(label_like(c) for c in cells if c.strip()):
            for r in block[1:]:
                for head, cell in zip(cells, r.cells or (), strict=False):
                    if head.strip() and cell.strip():
                        out.append(Pair(label=head.strip(), value=cell.strip(), page=page,
                                        box=None, from_layout=False))
            i = j
            continue
        i += 1
    return out


def discover(pages: list[Page], form_fields: list[FormField]) -> list[Pair]:
    pairs: list[Pair] = []
    for page in pages:
        rows: list[Line] = []
        for line in page.lines:
            if line.cells is not None:
                rows.append(line)
                continue
            if rows:
                pairs += _table_pairs(rows, page.n)
                rows = []
            pairs += _line_pairs(line, page.n)
        if rows:
            pairs += _table_pairs(rows, page.n)
    for f in form_fields:
        pairs.append(Pair(label=f.label, value=(f.value or "").strip() or None, page=f.page,
                          box=f.box, from_layout=f.box is not None, confidence=1.0))
    return pairs
