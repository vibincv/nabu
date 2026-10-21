"""Pinned downloads (FR-1.12). Every file the installer fetches is named here with its sha256.

The fetcher takes a key from ARTEFACTS, never a URL, so nothing outside this table can be
downloaded. Values were read from the GitHub release API and the Ollama registry on 2026-10-14.

Ollama cannot pull by digest (`name@sha256:…` gives "invalid model name" on 0.40.3, tested
2026-10-14). Models are therefore pulled by tag, and the digest the runtime reports for the
pulled model (the sha256 of the registry manifest, which lists every layer's sha256) is compared
with MODELS below. A mismatch removes the model and stops the install.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Artefact:
    key: str
    url: str
    sha256: str
    size_bytes: int


_OLLAMA = "https://github.com/ollama/ollama/releases/download/v0.40.3/"
OLLAMA_VERSION = "0.40.3"

ARTEFACTS: dict[str, Artefact] = {a.key: a for a in (
    Artefact("ollama-windows", _OLLAMA + "OllamaSetup.exe",
             "ab81db6c6f4f65547242d1b2912e854da660ab3bc1dbd5ae3483831cf7668c80", 1578217944),
    Artefact("ollama-macos", _OLLAMA + "ollama-darwin.tgz",
             "a2d1d906a2c8febd9cb18f5c183854d0a6db5dc522940d68b0c0ed048e8dfdea", 167455486),
    Artefact("ollama-linux-amd64", _OLLAMA + "ollama-linux-amd64.tar.zst",
             "ce6f8b671a699bf1ebafb28d60dbbabf4f37b30b499145fa308a8ba72de021d6", 1437349190),
    Artefact("ollama-linux-arm64", _OLLAMA + "ollama-linux-arm64.tar.zst",
             "5754700747a93ea14db88888f08072386d2da6fbf7dd75be19a684348b9f28b8", 1558419074),
)}


@dataclass(frozen=True)
class ModelPin:
    digest: str  # sha256 of the registry manifest; what /api/tags reports as "digest"
    size_bytes: int  # sum of the manifest's layers and config


MODELS: dict[str, ModelPin] = {
    "qwen3.5:0.8b": ModelPin("de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c",
                             1322069277),
    "qwen3.5:2b": ModelPin("0689d44085e06d165161a8a9a1731344278cfb5aade63a3c3dbdb48ab54b130a",
                           2683396812),
    "qwen3.5:4b": ModelPin("d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04",
                           3324173934),
    "qwen3.5:9b": ModelPin("56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90",
                           6550825550),
    "qwen3.5:27b": ModelPin("64ae5b1d651fb2709d5928ccb8dcfb4bb2cc9c2c8001ac34497e36a6cf905b59",
                            17478556591),
}


def runtime_artefact(system: str, arch: str) -> Artefact | None:
    """The Ollama download for this platform, or None when there is no pinned build."""
    a = arch.lower()
    if system == "Windows" and a in ("amd64", "x86_64"):
        return ARTEFACTS["ollama-windows"]
    if system == "Darwin":
        return ARTEFACTS["ollama-macos"]
    if system == "Linux" and a in ("x86_64", "amd64"):
        return ARTEFACTS["ollama-linux-amd64"]
    if system == "Linux" and a in ("aarch64", "arm64"):
        return ARTEFACTS["ollama-linux-arm64"]
    return None
