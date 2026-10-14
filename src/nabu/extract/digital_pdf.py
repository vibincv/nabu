"""PDF text layer with word boxes (pdfplumber). Input is bytes (io.BytesIO). M1.

Each page is read on its own (FR-2.3): a page with a text layer gives words with boxes on the
0-1000 grid; a page without one is marked for rendering and OCR. Form fields come from the
AcroForm (FR-4.2).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from nabu.errors import NabuError, UnreadableInput
from nabu.ocr.words import FormField, Page, Word, lines_from_words, to_grid

# A page counts as having a text layer when it has at least this many non-space characters.
# Fewer usually means a scan with a stray header or page number.
MIN_TEXT_CHARS = 10
MAX_FORM_FIELDS = 2000


@dataclass
class PdfText:
    pages: list[Page | None]  # None where the page has no text layer and needs OCR
    form_fields: list[FormField]


def _plumber():  # type: ignore[no-untyped-def]
    try:
        import pdfplumber
    except ImportError:
        raise NabuError("PDF support is not installed; run: uv sync --extra read") from None
    return pdfplumber


def read(data: bytes, name: str) -> PdfText:
    pdfplumber = _plumber()
    pages: list[Page | None] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, p in enumerate(pdf.pages, 1):
                words = p.extract_words(keep_blank_chars=False, use_text_flow=False,
                                        extra_attrs=[])
                chars = sum(len(w["text"].strip()) for w in words)
                if chars < MIN_TEXT_CHARS:
                    pages.append(None)
                    continue
                ws = [Word(text=w["text"], box=to_grid(w["x0"], w["top"], w["x1"], w["bottom"],
                                                       float(p.width), float(p.height)))
                      for w in words if w["text"].strip()]
                pages.append(Page(n=i, source="text_layer", lines=lines_from_words(ws),
                                  width_px=round(float(p.width)), height_px=round(float(p.height))))
            fields = _form_fields(pdf)
    except NabuError:
        raise
    except Exception:  # pdfminer errors on malformed files; never show their trace (NFR-8)
        raise UnreadableInput(f"{name} is damaged and could not be read") from None
    return PdfText(pages=pages, form_fields=fields)


def _text(v: object) -> str | None:
    from pdfminer.psparser import PSLiteral

    if v is None:
        return None
    if isinstance(v, bytes):
        if v.startswith((b"\xfe\xff", b"\xff\xfe")):
            return v.decode("utf-16", errors="replace")
        return v.decode("latin-1")
    if isinstance(v, PSLiteral):
        name = v.name
        return name.decode("latin-1") if isinstance(name, bytes) else str(name)
    return str(v)


def _form_fields(pdf) -> list[FormField]:  # type: ignore[no-untyped-def]
    from pdfminer.pdftypes import resolve1

    acro = resolve1(pdf.doc.catalog.get("AcroForm"))
    if not isinstance(acro, dict):
        return []
    page_of = {p.page_obj.pageid: p for p in pdf.pages}
    out: list[FormField] = []
    stack = [(f, "") for f in (resolve1(acro.get("Fields")) or [])]
    while stack and len(out) < MAX_FORM_FIELDS:
        ref, parent = stack.pop(0)
        f = resolve1(ref)
        if not isinstance(f, dict):
            continue
        name = _text(resolve1(f.get("T"))) or ""
        full = f"{parent}.{name}" if parent and name else (name or parent)
        kids = resolve1(f.get("Kids"))
        if kids and any("T" in (resolve1(k) or {}) for k in kids):
            stack += [(k, full) for k in kids]
            continue
        label = _text(resolve1(f.get("TU"))) or full
        value = _text(resolve1(f.get("V")))
        if value in ("Off",):
            value = None
        page, box = 1, None
        widget = f if "Rect" in f else (resolve1(kids[0]) if kids else None)
        if isinstance(widget, dict):
            pref = widget.get("P")
            pobj = page_of.get(getattr(pref, "objid", None))
            if pobj is not None:
                page = pobj.page_number
                r = [float(x) for x in resolve1(widget.get("Rect")) or []]
                if len(r) == 4:
                    h = float(pobj.height)
                    box = to_grid(min(r[0], r[2]), h - max(r[1], r[3]), max(r[0], r[2]),
                                  h - min(r[1], r[3]), float(pobj.width), h)
        if label.strip():
            out.append(FormField(label=label.strip(), value=value, page=page, box=box))
    return out
