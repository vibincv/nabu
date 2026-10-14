"""Render pages to images in memory (pypdfium2; never PyMuPDF, AGPL). M1.

PDF pages are rendered at the configured DPI (FR-2.4). Image files are decoded with Pillow: EXIF
orientation applied, GIF first frame only, multi-page TIFF one page per frame (FR-2.1). Images
stay in memory as PNG bytes (FR-3.6). Pillow's decompression-bomb limit applies (threat model).
"""

from __future__ import annotations

import io

from nabu.errors import NabuError, TooLarge, UnreadableInput
from nabu.model.types import PageImage

MAX_RENDER_EDGE_PX = 4000  # a huge page at 200 DPI must not exhaust memory
MAX_FRAMES = 200


def _pil():  # type: ignore[no-untyped-def]
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise NabuError("image support is not installed; run: uv sync --extra read") from None
    return Image, ImageOps


def _png(img, page: int) -> PageImage:  # type: ignore[no-untyped-def]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return PageImage(data=buf.getvalue(), width_px=img.width, height_px=img.height, page=page)


def image_pages(data: bytes, name: str, first_page: int = 1) -> list[PageImage]:
    Image, ImageOps = _pil()  # noqa: N806
    try:
        img = Image.open(io.BytesIO(data))
        frames = 1 if img.format == "GIF" else min(getattr(img, "n_frames", 1), MAX_FRAMES)
        out = []
        for i in range(frames):
            img.seek(i)
            frame = ImageOps.exif_transpose(img.copy()).convert("RGB")
            out.append(_png(frame, first_page + i))
        return out
    except Image.DecompressionBombError:
        raise TooLarge(f"{name} is too large an image to process") from None
    except (OSError, ValueError, EOFError, SyntaxError):
        raise UnreadableInput(f"{name} is damaged and could not be read") from None


def open_pdf(data: bytes, name: str):  # type: ignore[no-untyped-def]
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise NabuError("PDF support is not installed; run: uv sync --extra read") from None
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise UnreadableInput(
                f"{name} is password-protected; remove the password and upload it again") from None
        raise UnreadableInput(f"{name} is damaged and could not be read") from None


def render_pdf_page(pdf, index: int, dpi: int, name: str) -> PageImage:  # type: ignore[no-untyped-def]
    """Render one PDF page (0-based index) at `dpi`, capped at MAX_RENDER_EDGE_PX."""
    try:
        page = pdf[index]
        w_pt, h_pt = page.get_size()
        scale = dpi / 72
        if max(w_pt, h_pt) * scale > MAX_RENDER_EDGE_PX:
            scale = MAX_RENDER_EDGE_PX / max(w_pt, h_pt)
        img = page.render(scale=scale).to_pil().convert("RGB")
    except Exception:  # pdfium errors on a malformed page; never show their trace (NFR-8)
        raise UnreadableInput(f"{name}: page {index + 1} could not be rendered") from None
    return _png(img, index + 1)
