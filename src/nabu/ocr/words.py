"""Word/box data types on the 0-1000 page grid (DD-1.1), and the in-memory reading of a document.

Everything here holds document text, so text fields are left out of repr: a stray log line or
traceback cannot print a value (FR-11.5). Nothing here is ever written to disk (AD-8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from nabu.model.types import Box, PageImage

GRID = 1000

Route = Literal["digital_pdf", "raster", "office", "text"]
# Where a page's words came from. Maps to box_source in the working result (DD-1.2).
PageSource = Literal["text_layer", "ocr", "document"]


@dataclass(frozen=True)
class Word:
    text: str = field(repr=False)
    box: Box | None  # None for formats without page positions (AD-15)
    conf: float = 1.0


@dataclass(frozen=True)
class Line:
    """One line in reading order. `cells` holds a table row's cells when the line is a table row."""

    words: tuple[Word, ...] = field(repr=False)
    cells: tuple[str, ...] | None = field(default=None, repr=False)

    @property
    def text(self) -> str:
        if self.cells is not None:
            return "\t".join(self.cells)
        return " ".join(w.text for w in self.words)

    @property
    def box(self) -> Box | None:
        return union([w.box for w in self.words])


@dataclass
class Page:
    n: int
    source: PageSource
    lines: list[Line] = field(default_factory=list, repr=False)
    width_px: int | None = None
    height_px: int | None = None
    image: PageImage | None = field(default=None, repr=False)  # raster pages only (FR-3.6)
    lang: str | None = None
    # Named problems found while reading this page, e.g. a script with no OCR pack (FR-9.9).
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def words(self) -> list[Word]:
        return [w for line in self.lines for w in line.words]


@dataclass
class FormField:
    """A PDF form field (FR-4.2). `label` is the field's tooltip or name."""

    label: str = field(repr=False)
    value: str | None = field(repr=False)
    page: int = 1
    box: Box | None = None


@dataclass
class Reading:
    file_name: str
    route: Route
    pages: list[Page] = field(default_factory=list)
    form_fields: list[FormField] = field(default_factory=list, repr=False)

    @property
    def is_scan(self) -> bool:
        return any(p.source == "ocr" for p in self.pages)


def union(boxes: Sequence[Box | None]) -> Box | None:
    real = [b for b in boxes if b is not None]
    if not real:
        return None
    return (min(b[0] for b in real), min(b[1] for b in real),
            max(b[2] for b in real), max(b[3] for b in real))


def to_grid(x0: float, y0: float, x1: float, y1: float, width: float, height: float) -> Box | None:
    """Pixel or point box -> 0-1000 grid, clamped. None for an empty box."""
    if width <= 0 or height <= 0:
        return None
    b = tuple(min(GRID, max(0, round(v))) for v in
              (x0 * GRID / width, y0 * GRID / height, x1 * GRID / width, y1 * GRID / height))
    if b[2] < b[0] or b[3] < b[1]:
        return None
    return b  # type: ignore[return-value]


def lines_from_words(words: Sequence[Word]) -> list[Line]:
    """Group positioned words into lines, top to bottom then left to right.

    Two words share a line when their vertical centres are closer than half the smaller height.
    """
    placed = sorted((w for w in words if w.box is not None),
                    key=lambda w: (w.box[1] + w.box[3], w.box[0]))  # type: ignore[index]
    rows: list[list[Word]] = []
    for w in placed:
        b = w.box
        assert b is not None
        cy, h = (b[1] + b[3]) / 2, max(1, b[3] - b[1])
        for row in rows:
            r = union([x.box for x in row])
            assert r is not None
            if abs((r[1] + r[3]) / 2 - cy) < min(h, max(1, r[3] - r[1])) / 2:
                row.append(w)
                break
        else:
            rows.append([w])
    rows.sort(key=lambda row: min(x.box[1] for x in row))  # type: ignore[index]
    return [Line(words=tuple(sorted(row, key=lambda x: x.box[0]))) for row in rows]  # type: ignore[index]
