"""The built review UI must load nothing from outside (FR-6.14, API-3). Runs after `npm run build`."""

import re
from pathlib import Path

import pytest

DIST = Path(__file__).parent.parent / "src" / "nabu" / "server" / "ui_dist"
ALLOWED = {"http://www.w3.org/2000/svg"}  # XML namespace string, not a request
URL = re.compile(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s\"'`)]*")

pytestmark = pytest.mark.skipif(not (DIST / "index.html").exists(), reason="UI not built")


def test_no_remote_urls_in_bundle():
    found: set[str] = set()
    for p in DIST.rglob("*"):
        if p.suffix in {".html", ".js", ".css"}:
            found |= set(URL.findall(p.read_text(encoding="utf-8")))
    assert found <= ALLOWED, found - ALLOWED


def test_token_placeholder_present():
    assert '<meta name="nabu-token" content="">' in (DIST / "index.html").read_text(encoding="utf-8")


def test_no_inline_scripts():  # CSP script-src 'self' would block them
    html = (DIST / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
