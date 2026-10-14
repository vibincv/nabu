"""OCR language packs (FR-1.9, FR-9.9).

The OCR engine's bundled models read English and other Latin-script text (plus Chinese). Other
scripts need a recognition model per language, downloaded once with `nabu langs pull <lang>`.

`langs pull` is the one exception to "loopback only" (AR-3, owner decision 2026-10-13): it
downloads only the pinned URLs below, checks every file's sha256, writes through the store, and
is refused while the egress guard is installed (that is, inside a process that reads documents).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from nabu.errors import NabuError

_MODELSCOPE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/"


@dataclass(frozen=True)
class PackFile:
    name: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Pack:
    lang: str  # ISO 639-1
    language: str  # English name, for messages
    script: str  # Unicode script the pack reads
    model: PackFile
    keys: PackFile  # character list for the recognition model

    @property
    def size_mb(self) -> float:
        return round((self.model.size_bytes + self.keys.size_bytes) / 2**20, 1)


# PP-OCRv5 Korean recognition (PaddleOCR, Apache-2.0), ONNX export by RapidAI.
PACKS: dict[str, Pack] = {
    "ko": Pack(
        lang="ko", language="Korean", script="Hangul",
        model=PackFile("rec.onnx", _MODELSCOPE + "onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx",
                       "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b", 13488748),
        keys=PackFile("keys.txt", _MODELSCOPE
                      + "paddle/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile/ppocrv5_korean_dict.txt",
                      "a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7", 47451),
    ),
}

# Languages the bundled models read without a pack.
BUILTIN_LANGS = ("en", "de", "fr", "es", "it", "pt", "nl")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def installed(langs_dir: Path) -> dict[str, Path]:
    """Packs present and complete on disk. A pack whose files fail their checksum is not listed."""
    out = {}
    for lang, pack in PACKS.items():
        d = langs_dir / lang
        files = [d / pack.model.name, d / pack.keys.name]
        if all(f.is_file() for f in files) and all(
                sha256(f.read_bytes()) == pf.sha256 for f, pf in zip(files, (pack.model, pack.keys),
                                                                        strict=True)):
            out[lang] = d
    return out


def download(lang: str) -> dict[str, bytes]:
    """Fetch a pack's files from their pinned URLs and verify them. Returns {file name: bytes}.

    Runs only outside the reading process: refused when the egress guard is installed.
    """
    from nabu import netguard

    pack = PACKS.get(lang)
    if pack is None:
        raise NabuError(f"no OCR language pack for '{lang}'. Available: {', '.join(sorted(PACKS))}")
    if netguard.installed():
        raise NabuError("language packs cannot be downloaded while Nabu is reading documents; "
                        "close the review window and run: nabu langs pull " + lang)
    import httpx

    out = {}
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True,
                      trust_env=True) as client:
        for pf in (pack.model, pack.keys):
            try:
                r = client.get(pf.url)
                r.raise_for_status()
            except httpx.HTTPError:
                raise NabuError(f"could not download the {pack.language} OCR pack ({pf.name}); "
                                "check the internet connection and try again") from None
            if sha256(r.content) != pf.sha256:
                raise NabuError(f"the downloaded {pack.language} OCR pack file {pf.name} does not "
                                "match its checksum; nothing was installed")
            out[pf.name] = r.content
    return out
