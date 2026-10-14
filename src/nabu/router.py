"""File type by extension and content; unsupported, encrypted, corrupt files (FR-2).

The type is decided by extension AND content (FR-2.2). Every refusal is a named error whose
message names the file and the problem, never a trace (FR-2.5, FR-2.6, NFR-8). Messages may hold
the file name, never document text.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

from nabu.errors import TooLarge, UnreadableInput, UnsupportedFormat

Kind = Literal["pdf", "image", "docx", "xlsx", "pptx", "text", "csv", "tsv", "json", "rtf", "html"]

EXTENSIONS: dict[str, Kind] = {
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image",
    ".webp": "image", ".bmp": "image", ".gif": "image",
    ".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx",
    ".csv": "csv", ".tsv": "tsv", ".txt": "text", ".md": "text", ".json": "json",
    ".rtf": "rtf", ".html": "html", ".htm": "html",  # best effort (FR-2.1)
}
_TEXT_KINDS = frozenset({"text", "csv", "tsv", "json", "rtf", "html"})
_OFFICE_DIRS = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # encrypted OOXML files are OLE containers


@dataclass(frozen=True)
class Upload:
    """One uploaded file, in memory only (FR-3.6)."""

    name: str
    data: bytes

    @property
    def ext(self) -> str:
        return PurePath(self.name).suffix.lower()


def _image_kind(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WebP"
    if head.startswith(b"BM"):
        return "BMP"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    return None


def _ooxml_kind(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    if "[Content_Types].xml" not in names:
        return "ZIP archive"
    for kind, prefix in _OFFICE_DIRS.items():
        if any(n.startswith(prefix) for n in names):
            return kind
    return "ZIP archive"


def sniff(data: bytes) -> str:
    """A short human name for what the content is. Used only for routing and messages."""
    head = data[:16]
    if b"%PDF-" in data[:1024]:
        return "PDF"
    img = _image_kind(head)
    if img:
        return img
    if head.startswith(b"PK\x03\x04"):
        return _ooxml_kind(data) or "ZIP archive"
    if head.startswith(_OLE):
        return "OLE"
    if head.lstrip().startswith(b"{\\rtf"):
        return "RTF"
    if b"\x00" in data[:4096] and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "binary data"
    return "text"


def classify(upload: Upload, limit_mb: int) -> Kind:
    """Return the kind of an upload or raise a named error (FR-2.2, 2.5, 2.6, 2.7)."""
    name = upload.name
    kind = EXTENSIONS.get(upload.ext)
    if kind is None:
        raise UnsupportedFormat(f"unsupported format: {upload.ext or '(no extension)'}")
    if len(upload.data) > limit_mb * 1024 * 1024:
        raise TooLarge(f"{name} is larger than the upload limit of {limit_mb} MB")
    if not upload.data.strip():
        raise UnreadableInput(f"{name} is empty")
    content = sniff(upload.data)
    if kind in _OFFICE_DIRS and content == "OLE":
        raise UnreadableInput(f"{name} is password-protected; remove the password and upload it again")
    expected = {"pdf": "PDF", "docx": "docx", "xlsx": "xlsx", "pptx": "pptx"}.get(kind)
    if kind == "image":
        if _image_kind(upload.data[:16]) is None:
            _mismatch(upload, content)
    elif kind == "rtf":
        if content not in ("RTF", "text"):
            _mismatch(upload, content)
    elif kind in _TEXT_KINDS:
        if content != "text":
            _mismatch(upload, content)
    elif expected and content != expected:
        if content == "ZIP archive" and kind in _OFFICE_DIRS:
            raise UnreadableInput(f"{name} is damaged and could not be read")
        _mismatch(upload, content)
    return kind


def _mismatch(upload: Upload, content: str) -> None:
    raise UnsupportedFormat(
        f"{upload.name}: the extension is {upload.ext} but the content is {content}")


def check_combination(uploads: list[Upload], kinds: list[Kind]) -> None:
    """Several files make one document only when all of them are images (FR-2.8)."""
    if len(uploads) > 1 and any(k != "image" for k in kinds):
        raise UnsupportedFormat(
            "only image files can be combined into one document; upload PDF and office files alone")
