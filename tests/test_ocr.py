"""Real OCR (AD-1, FR-3.2): bundled models, no network, words with boxes on the 0-1000 grid.

Korean needs the pack (`nabu langs pull ko`); that test runs only when NABU_TEST_OCR_LANGS points
at a folder holding ko/rec.onnx and ko/keys.txt, so CI stays offline.
"""

import os
from pathlib import Path

import docgen
import pytest

from nabu.extract.raster import image_pages
from nabu.ocr import engine, packs
from nabu.store.guard import compact

pytest.importorskip("rapidocr")
pytest.importorskip("onnxruntime")


@pytest.fixture(scope="module")
def latin_engine(tmp_path_factory):
    return engine.detect(tmp_path_factory.mktemp("no-packs"))


def test_reads_latin_with_word_boxes(latin_engine):
    data = docgen.page_image([("Invoice no:", "INV-0042"), ("Date:", "2026-10-01"),
                              ("Total:", "1.428,00 EUR")], title="INVOICE")
    res = latin_engine.read(image_pages(data, "scan.png")[0])
    text = compact(" ".join(line.text for line in res.lines))
    for expected in ("INV-0042", "2026-10-01", "1.428,00 EUR", "Invoice no"):
        assert compact(expected) in text
    words = [w for line in res.lines for w in line.words]
    assert words and all(w.box is not None and 0 <= w.box[0] < w.box[2] <= 1000 for w in words)
    inv = next(w for w in words if compact(w.text) == compact("INV-0042"))
    assert 400 < inv.box[0] < 520  # the value column starts at x=560 of 1240 px (~452)
    assert res.notes == []


def test_engine_languages_without_packs(latin_engine):
    assert latin_engine.languages == sorted(packs.BUILTIN_LANGS)


def test_script_detection():
    assert engine.script_of("한") == "Hangul" and engine.script_of("中") == "Han"
    assert engine.script_of("ü") == "Latin" and engine.script_of("1") is None
    assert engine.has_script("성명: 홍길동", "Hangul")


def test_pack_with_a_bad_checksum_is_not_installed(tmp_path):
    d = tmp_path / "ko"
    d.mkdir()
    (d / "rec.onnx").write_bytes(b"not the model")
    (d / "keys.txt").write_bytes(b"x")
    assert packs.installed(tmp_path) == {}


@pytest.mark.skipif(not os.environ.get("NABU_TEST_OCR_LANGS"), reason="Korean OCR pack not provided")
def test_reads_korean_with_the_pack():
    from PIL import Image, ImageDraw, ImageFont

    font = next((f for f in ("C:/Windows/Fonts/malgun.ttf",
                             "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                             "/System/Library/Fonts/AppleSDGothicNeo.ttc") if Path(f).exists()), None)
    if font is None:
        pytest.skip("no Hangul font on this machine")
    import io

    img = Image.new("RGB", (1240, 600), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(font, 36)
    d.text((80, 100), "성명:", font=f, fill="black")
    d.text((500, 100), "홍길동", font=f, fill="black")
    d.text((80, 200), "주소:", font=f, fill="black")
    d.text((500, 200), "서울특별시 중구 예시로 1", font=f, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    eng = engine.detect(Path(os.environ["NABU_TEST_OCR_LANGS"]))
    assert "ko" in eng.languages
    res = eng.read(image_pages(buf.getvalue(), "ko.png")[0])
    text = compact(" ".join(line.text for line in res.lines))
    for expected in ("성명", "홍길동", "주소", "서울특별시 중구 예시로 1"):
        assert compact(expected) in text
