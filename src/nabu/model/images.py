"""Image size limit (FR-10.3), crops for the re-read (AD-6) and box conversion (FR-10.6).

All in memory. Pillow refuses images above its decompression-bomb limit, which is reported as
TooLarge (threat model: crafted file exhausts memory).
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from nabu.errors import NabuError, TooLarge, UnreadableInput
from nabu.model.profiles import Coords
from nabu.model.types import Box, PageImage

GRID = 1000


def _pil():  # type: ignore[no-untyped-def]
    try:
        from PIL import Image
    except ImportError:
        raise NabuError("image support is not installed; run: uv sync --extra read") from None
    return Image


def _open(data: bytes):  # type: ignore[no-untyped-def]
    Image = _pil()  # noqa: N806
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError:
        raise TooLarge("the page image is too large to process") from None
    except (OSError, ValueError):
        raise UnreadableInput("the page image could not be decoded") from None
    return img


def _png(img) -> bytes:  # type: ignore[no-untyped-def]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def image_size(data: bytes) -> tuple[int, int]:
    img = _open(data)
    return img.width, img.height


def fit(page: PageImage, max_edge_px: int) -> PageImage:
    """Return the page with its long edge at most max_edge_px. Unchanged if it already fits."""
    if max(page.width_px, page.height_px) <= max_edge_px:
        return page
    Image = _pil()  # noqa: N806
    img = _open(page.data)
    scale = max_edge_px / max(img.width, img.height)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    small = img.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    return PageImage(data=_png(small), width_px=small.width, height_px=small.height, page=page.page)


def crop(page: PageImage, box: Box, margin: int = 30) -> tuple[PageImage, Box]:
    """Crop a grid box plus a margin (grid units). Returns the crop and the grid box it covers."""
    x0, y0, x1, y1 = (max(0, box[0] - margin), max(0, box[1] - margin),
                      min(GRID, box[2] + margin), min(GRID, box[3] + margin))
    if x1 <= x0 or y1 <= y0:
        raise NabuError("crop box is empty")
    img = _open(page.data)
    px = (round(x0 * img.width / GRID), round(y0 * img.height / GRID),
          round(x1 * img.width / GRID), round(y1 * img.height / GRID))
    part = img.convert("RGB").crop(px)
    return (PageImage(data=_png(part), width_px=part.width, height_px=part.height, page=page.page),
            (x0, y0, x1, y1))


def raw_box(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 4:
        return None
    try:
        a, b, c, d = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return (a, b, c, d)


def to_grid(raw: tuple[float, float, float, float] | None, coords: Coords,
            width_px: int, height_px: int) -> Box | None:
    """Convert a model box to the 0-1000 grid of the image it was given (FR-10.6)."""
    if raw is None or coords == "none":
        return None
    if coords == "pixels":
        sx, sy = GRID / width_px, GRID / height_px
    elif coords == "unit":
        sx = sy = float(GRID)
    else:  # grid_1000
        sx = sy = 1.0
    x0, x1 = sorted((raw[0] * sx, raw[2] * sx))
    y0, y1 = sorted((raw[1] * sy, raw[3] * sy))
    box = tuple(min(GRID, max(0, round(v))) for v in (x0, y0, x1, y1))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box  # type: ignore[return-value]


def crop_to_page(box: Box | None, crop_area: Box) -> Box | None:
    """Map a box on the crop's grid back to the page grid."""
    if box is None:
        return None
    w, h = crop_area[2] - crop_area[0], crop_area[3] - crop_area[1]
    return (crop_area[0] + round(box[0] * w / GRID), crop_area[1] + round(box[1] * h / GRID),
            crop_area[0] + round(box[2] * w / GRID), crop_area[1] + round(box[3] * h / GRID))
