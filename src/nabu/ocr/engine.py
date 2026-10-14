"""Engine detection and selection: rapidocr | auto. M1.

One interface (AD-1, EP-3): `OcrEngine.read(page) -> list[Line]` with word boxes on the 0-1000
grid. RapidOCR is the only engine (Q5 closed: no Tesseract).

How languages are handled (measured in tasks/m0-ocr.md): the bundled models detect every text
line and read Latin text well. They read Hangul as confident Chinese, so a line whose reading
contains CJK ideographs or scores low is read again with each installed language pack, and the
pack's reading is kept when it contains that pack's script. Choosing by score alone fails.

The angle classifier is not used (it flipped upright lines in the M0 test).
rapidocr keeps use_det/use_cls/use_rec from one call for the next, so every call passes all three.
rapidocr downloads a model when its path is missing; every path is passed explicitly, and the
egress guard refuses any download anyway.
"""

from __future__ import annotations

import io
import logging
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from nabu.errors import NabuError
from nabu.model.types import PageImage
from nabu.ocr import packs
from nabu.ocr.words import Line, Word, lines_from_words, to_grid

log = logging.getLogger(__name__)

REREAD_BELOW = 0.8  # line score under which installed packs get a try
MIN_WORD_SCORE = 0.3  # lines scoring lower are dropped as noise


def script_of(ch: str) -> str | None:
    """Unicode script of a letter, from its character name. Enough for routing, not linguistics."""
    if not ch.isalpha():
        return None
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
        return "Hangul"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
        return "Han"
    try:
        return unicodedata.name(ch).split(" ")[0].title()
    except ValueError:
        return None


def has_script(text: str, script: str) -> bool:
    return any(script_of(c) == script for c in text)


@dataclass
class OcrResult:
    lines: list[Line]
    notes: list[str]


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self, pack_dirs: dict[str, Path]) -> None:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            raise NabuError("OCR is not installed; run: uv sync --extra read") from None
        import rapidocr

        root = Path(rapidocr.__file__).parent / "models"
        base_params = {
            "Global.log_level": "error",
            "Global.text_score": 0.0,  # keep weak lines: a pack may read them (MIN_WORD_SCORE later)
            "Det.model_path": str(root / "PP-OCRv6_det_small.onnx"),
            "Cls.model_path": str(root / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
            "Rec.model_path": str(root / "PP-OCRv6_rec_small.onnx"),
        }
        for k in ("Det.model_path", "Cls.model_path", "Rec.model_path"):
            if not Path(base_params[k]).is_file():
                raise NabuError("the OCR engine's bundled models are missing; reinstall Nabu")
        self._base = RapidOCR(params=base_params)
        self._packs = {
            lang: (packs.PACKS[lang], RapidOCR(params={
                **base_params,
                "Rec.model_path": str(d / packs.PACKS[lang].model.name),
                "Rec.rec_keys_path": str(d / packs.PACKS[lang].keys.name)}))
            for lang, d in pack_dirs.items()}
        self._lock = threading.Lock()  # onnxruntime sessions are shared; one page at a time

    @property
    def languages(self) -> list[str]:
        return sorted({*packs.BUILTIN_LANGS, *self._packs})

    def read(self, page: PageImage) -> OcrResult:
        import numpy as np
        from PIL import Image

        img = np.asarray(Image.open(io.BytesIO(page.data)).convert("RGB"))[:, :, ::-1].copy()  # BGR
        w, h = page.width_px, page.height_px
        with self._lock:
            # No angle classifier: it turned upright lines 180 degrees in the M0 test ("DE999..."
            # read as "666..."). Image orientation comes from EXIF (extract.raster).
            res = self._base(img, use_det=True, use_cls=False, use_rec=True, return_word_box=True)
            words: list[Word] = []
            cjk_unread = False
            for i, (quad, text, score) in enumerate(zip(res.boxes if res.boxes is not None else [],
                                                        res.txts or (), res.scores or (),
                                                        strict=False)):
                reread = self._reread(img, quad, text, float(score))
                if reread is not None:
                    words += reread
                    continue
                if float(score) < MIN_WORD_SCORE:
                    continue
                if has_script(text, "Han") and not self._packs:
                    cjk_unread = True  # Hangul (or Chinese) with no pack: never show it garbled
                    continue
                words += self._words(res.word_results[i] if res.word_results else (), quad, text,
                                     float(score), w, h)
            if self._packs:
                # rapidocr drops lines its bundled model read as empty, which is what it does
                # with some Hangul lines. Detect again and give those lines to the packs.
                seen = [_bbox(q) for q in (res.boxes if res.boxes is not None else [])]
                det = self._base(img, use_det=True, use_cls=False, use_rec=False)
                for quad in det.boxes if det.boxes is not None else []:
                    if not any(_iou(_bbox(quad), b) > 0.5 for b in seen):
                        words += self._reread(img, quad, "", 0.0) or []
        notes = []
        if cjk_unread:
            notes.append("Korean or Chinese text found; OCR language pack not installed. "
                         "For Korean run: nabu langs pull ko")
        return OcrResult(lines=lines_from_words(words), notes=notes)

    def _reread(self, img, quad, text: str, score: float) -> list[Word] | None:  # type: ignore[no-untyped-def]
        if not self._packs or not (score < REREAD_BELOW or has_script(text, "Han")):
            return None
        crop, (x0, y0, x1, y1) = _crop(img, quad)
        h, w = img.shape[:2]
        for pack, engine in self._packs.values():
            r = engine(crop, use_det=False, use_cls=False, use_rec=True)
            if r.txts and has_script(r.txts[0], pack.script):
                line = r.txts[0]
                return _split_evenly(line, float(r.scores[0]), x0, y0, x1, y1, w, h)
        return None

    @staticmethod
    def _words(word_results, quad, text: str, score: float, w: int, h: int) -> list[Word]:  # type: ignore[no-untyped-def]
        out = []
        for item in word_results or ():
            t, s, box = item[0], float(item[1]), item[2]
            if not t.strip() or box is None:
                continue
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            gb = to_grid(min(xs), min(ys), max(xs), max(ys), w, h)
            if gb is not None:
                out.append(Word(text=t, box=gb, conf=s))
        if out and _joined(out) == _joined_text(text):
            return _merge_chars(out)
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        return _split_evenly(text, score, min(xs), min(ys), max(xs), max(ys), w, h)


def _joined(ws: list[Word]) -> str:
    return "".join(x.text for x in ws).replace(" ", "")


def _joined_text(t: str) -> str:
    return t.replace(" ", "")


def _merge_chars(ws: list[Word]) -> list[Word]:
    """rapidocr gives one box per character for CJK text; merge touching runs into words."""
    out: list[Word] = []
    for x in ws:
        if out and len(x.text) == 1 and len(out[-1].text) >= 1 and _touching(out[-1], x) \
                and not x.text.isspace() and script_of(x.text) in ("Han", "Hangul"):
            p = out[-1]
            assert p.box is not None and x.box is not None
            out[-1] = Word(text=p.text + x.text, box=(p.box[0], min(p.box[1], x.box[1]), x.box[2],
                                                      max(p.box[3], x.box[3])),
                           conf=min(p.conf, x.conf))
        else:
            out.append(x)
    return out


def _touching(a: Word, b: Word) -> bool:
    assert a.box is not None and b.box is not None
    gap = b.box[0] - a.box[2]
    return gap <= max(2, (a.box[3] - a.box[1]) // 3)


def _split_evenly(text: str, score: float, x0: float, y0: float, x1: float, y1: float,
                  w: int, h: int) -> list[Word]:
    """Word boxes for a line with no per-word boxes: split the line box by character count
    (wide characters count double). An estimate, good enough to highlight a value."""
    tokens = text.split()
    if not tokens:
        return []
    widths = [sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in t) for t in tokens]
    total = sum(widths) + len(tokens) - 1
    out, pos = [], 0.0
    for t, cw in zip(tokens, widths, strict=True):
        a = x0 + (x1 - x0) * pos / total
        b = x0 + (x1 - x0) * (pos + cw) / total
        gb = to_grid(a, y0, b, y1, w, h)
        if gb is not None:
            out.append(Word(text=t, box=gb, conf=score))
        pos += cw + 1
    return out


def _bbox(quad) -> tuple[float, float, float, float]:  # type: ignore[no-untyped-def]
    xs, ys = [float(p[0]) for p in quad], [float(p[1]) for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def _iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union_ = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union_ if union_ > 0 else 0.0


def _crop(img, quad):  # type: ignore[no-untyped-def]
    import cv2
    import numpy as np

    q = np.array(quad, dtype=np.float32)
    w = int(max(np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[2] - q[3])))
    h = int(max(np.linalg.norm(q[0] - q[3]), np.linalg.norm(q[1] - q[2])))
    m = cv2.getPerspectiveTransform(q, np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    crop = cv2.warpPerspective(img, m, (max(1, w), max(1, h)))
    xs, ys = q[:, 0], q[:, 1]
    return crop, (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))


def detect(langs_dir: Path, engine: str = "auto") -> RapidOcrEngine | None:
    """The OCR engine, or None when OCR is not installed (Section 14: scans then need the model)."""
    if engine not in ("auto", "rapidocr"):
        raise NabuError(f"unknown OCR engine '{engine}'; use auto or rapidocr")
    try:
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401
    except ImportError:
        return None
    return RapidOcrEngine(packs.installed(langs_dir))


def available() -> bool:
    try:
        import importlib.util

        return all(importlib.util.find_spec(m) is not None for m in ("rapidocr", "onnxruntime"))
    except (ImportError, ValueError):
        return False
