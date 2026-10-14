"""FR-2 acceptance: every supported extension maps to its route; unsupported, empty, encrypted,
corrupt and mismatched files each get their own named message."""

import zipfile
from io import BytesIO

import pytest

from nabu.errors import TooLarge, UnreadableInput, UnsupportedFormat
from nabu.router import EXTENSIONS, Upload, check_combination, classify

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
SAMPLES = {
    "pdf": b"%PDF-1.4\n...",
    "image": PNG,
    "text": b"Invoice no: 1\n",
    "csv": b"a,b\n1,2\n",
    "tsv": b"a\tb\n",
    "json": b'{"a": 1}',
    "html": b"<html><body>x</body></html>",
    "rtf": b"{\\rtf1 hello}",
}
IMAGE_HEADS = {".png": PNG, ".jpg": b"\xff\xd8\xff\xe0" + b"\0" * 20,
               ".jpeg": b"\xff\xd8\xff\xdb" + b"\0" * 20,
               ".tif": b"II*\x00" + b"\0" * 20, ".tiff": b"MM\x00*" + b"\0" * 20,
               ".webp": b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 8, ".bmp": b"BM" + b"\0" * 30,
               ".gif": b"GIF89a" + b"\0" * 20}


def ooxml(prefix: str) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(prefix + "document.xml", "<x/>")
    return buf.getvalue()


@pytest.mark.parametrize("ext", sorted(EXTENSIONS))
def test_every_supported_extension_has_a_route(ext):
    kind = EXTENSIONS[ext]
    if kind == "image":
        data = IMAGE_HEADS[ext]
    elif kind in ("docx", "xlsx", "pptx"):
        data = ooxml({"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}[kind])
    else:
        data = SAMPLES[kind]
    assert classify(Upload("f" + ext, data), 100) == kind


def test_unsupported_extension_exact_message():
    with pytest.raises(UnsupportedFormat) as e:
        classify(Upload("notes.xyz", b"hello"), 100)
    assert e.value.message == "unsupported format: .xyz"


def test_no_extension():
    with pytest.raises(UnsupportedFormat, match="no extension"):
        classify(Upload("README", b"hello"), 100)


def test_empty_file_named():
    with pytest.raises(UnreadableInput) as e:
        classify(Upload("scan.pdf", b""), 100)
    assert e.value.message == "scan.pdf is empty"


def test_content_mismatch_names_both():
    with pytest.raises(UnsupportedFormat) as e:
        classify(Upload("photo.png", b"%PDF-1.7\n..."), 100)
    assert e.value.message == "photo.png: the extension is .png but the content is PDF"


def test_binary_in_a_text_file_is_refused():
    with pytest.raises(UnsupportedFormat, match="content is binary data"):
        classify(Upload("a.txt", b"\x00\x01\x02 binary"), 100)


def test_encrypted_office_file():
    with pytest.raises(UnreadableInput, match="password-protected"):
        classify(Upload("secret.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64), 100)


def test_corrupt_office_file():
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("random.txt", "x")
    with pytest.raises(UnreadableInput, match="damaged"):
        classify(Upload("broken.xlsx", buf.getvalue()), 100)


def test_upload_limit_states_the_limit():
    with pytest.raises(TooLarge) as e:
        classify(Upload("big.pdf", b"%PDF-" + b"0" * (1024 * 1024 + 1)), 1)
    assert "1 MB" in e.value.message


def test_only_images_combine():
    check_combination([Upload("a.png", PNG), Upload("b.jpg", PNG)], ["image", "image"])
    with pytest.raises(UnsupportedFormat, match="only image files"):
        check_combination([Upload("a.png", PNG), Upload("b.pdf", b"%PDF")], ["image", "pdf"])
