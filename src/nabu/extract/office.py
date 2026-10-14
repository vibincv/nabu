"""DOCX/XLSX/PPTX from bytes (python-docx, openpyxl, python-pptx). M1.

Office files have no page positions, so words carry no boxes (AD-15). Pages: one for a DOCX,
one per sheet for an XLSX, one per slide for a PPTX. Table rows keep their cells (FR-3.1).
All reading is from io.BytesIO; nothing touches disk (FR-3.6).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterator

from nabu.errors import NabuError, UnreadableInput
from nabu.extract.text import row_line, text_line
from nabu.ocr.words import Line, Page, Reading
from nabu.router import Kind

MAX_SHEET_CELLS = 200_000  # a crafted sheet must not exhaust memory (threat model)
_MAX_UNCOMPRESSED = 500 * 1024 * 1024  # zip bomb guard on the OOXML container


def _require(module: str):  # type: ignore[no-untyped-def]
    try:
        return __import__(module, fromlist=["_"])
    except ImportError:
        raise NabuError("office support is not installed; run: uv sync --extra read") from None


def _check_container(data: bytes, name: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            total = sum(i.file_size for i in z.infolist())
    except (zipfile.BadZipFile, OSError, ValueError):
        raise UnreadableInput(f"{name} is damaged and could not be read") from None
    if total > _MAX_UNCOMPRESSED:
        raise UnreadableInput(f"{name} expands to more than 500 MB and was not read")


def _docx(data: bytes) -> list[Page]:
    docx = _require("docx")
    doc = docx.Document(io.BytesIO(data))
    lines: list[Line] = []
    body = doc.element.body
    tables = iter(doc.tables)
    paragraphs = iter(doc.paragraphs)
    for child in body.iterchildren():  # keep document order of paragraphs and tables
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = next(paragraphs, None)
            if p is not None and p.text.strip():
                lines += [text_line(s) for s in p.text.splitlines() if s.strip()]
        elif tag == "tbl":
            t = next(tables, None)
            if t is not None:
                lines += [row_line(cells) for cells in _docx_rows(t) if any(c.strip() for c in cells)]
    return [Page(n=1, source="document", lines=lines)]


def _docx_rows(table) -> Iterator[list[str]]:  # type: ignore[no-untyped-def]
    for row in table.rows:
        cells: list[str] = []
        last = None
        for cell in row.cells:  # merged cells repeat the same object; keep one copy
            if cell._tc is last:
                continue
            last = cell._tc
            cells.append(cell.text.replace("\n", " "))
        yield cells


def _xlsx(data: bytes) -> list[Page]:
    openpyxl = _require("openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    pages: list[Page] = []
    seen = 0
    try:
        for n, ws in enumerate(wb.worksheets, 1):
            lines = []
            for row in ws.iter_rows(values_only=True):
                seen += len(row)
                if seen > MAX_SHEET_CELLS:
                    raise UnreadableInput("the workbook has too many cells to read")
                cells = ["" if v is None else _cell(v) for v in row]
                while cells and not cells[-1].strip():
                    cells.pop()
                if any(c.strip() for c in cells):
                    lines.append(row_line(cells))
            pages.append(Page(n=n, source="document", lines=lines))
    finally:
        wb.close()
    return pages


def _cell(v: object) -> str:
    if hasattr(v, "isoformat"):
        s = v.isoformat()  # type: ignore[union-attr]
        return s[:10] if s.endswith("T00:00:00") else s
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _pptx(data: bytes) -> list[Page]:
    pptx = _require("pptx")
    prs = pptx.Presentation(io.BytesIO(data))
    pages = []
    for n, slide in enumerate(prs.slides, 1):
        lines: list[Line] = []
        for shape in slide.shapes:
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.replace("\n", " ") for c in row.cells]
                    if any(c.strip() for c in cells):
                        lines.append(row_line(cells))
            elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(r.text for r in para.runs)
                    if text.strip():
                        lines.append(text_line(text))
        pages.append(Page(n=n, source="document", lines=lines))
    return pages


_READERS: dict[str, Callable[[bytes], list[Page]]] = {"docx": _docx, "xlsx": _xlsx, "pptx": _pptx}


def read(data: bytes, name: str, kind: Kind) -> Reading:
    _check_container(data, name)
    try:
        pages = _READERS[kind](data)
    except NabuError:
        raise
    except Exception:  # library errors on malformed files; never show their trace (NFR-8)
        raise UnreadableInput(f"{name} is damaged and could not be read") from None
    if not any(p.lines for p in pages):
        raise UnreadableInput(f"{name} has no text to read")
    return Reading(file_name=name, route="office", pages=pages)
