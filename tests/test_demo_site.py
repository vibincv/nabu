"""M5 product page and demo: the synthetic licence sample and the page sources."""

from __future__ import annotations

import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DEMO = ROOT / "fixtures" / "demo"
SVG_NS = "{http://www.w3.org/2000/svg}"


def _generator():
    spec = importlib.util.spec_from_file_location("make_licence", DEMO / "make_licence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wr() -> dict:
    return json.loads((DEMO / "working_result.licence.json").read_text(encoding="utf-8"))


def test_committed_sample_matches_its_generator(wr):
    gen = _generator()
    assert (DEMO / "public" / "licence.svg").read_text(encoding="utf-8") == gen.svg()
    assert wr == gen.working_result()


def test_sample_is_synthetic_and_shows_every_status(wr):
    assert wr["document"]["source_file"].startswith("synthetic_")
    svg = (DEMO / "public" / "licence.svg").read_text(encoding="utf-8")
    assert "SPECIMEN" in svg and "NOT A REAL DOCUMENT" in svg
    shown = {s for f in wr["fields"] for s in f["status"]}
    # edited_by_user appears only once the viewer edits a field
    assert shown == {"from_template", "suggested", "needs_review", "not_found", "not_translated"}
    for f in wr["fields"]:
        assert (f["value"] is None) == ("not_found" in f["status"]) == (f["box"] is None)


def test_every_box_encloses_the_value_the_card_prints(wr):
    """Read from the SVG itself, not from the generator's table, so a hand edit to either side
    that moves a highlight off its text fails here."""
    root = ET.parse(DEMO / "public" / "licence.svg").getroot()
    width, height = float(root.get("width")), float(root.get("height"))
    style = root.find(f"{SVG_NS}style").text
    size = float(re.search(r"\.v \{[^}]*font-size: (\d+(?:\.\d+)?)px", style).group(1))
    printed = {t.text: (float(t.get("x")), float(t.get("y")))
               for t in root.iter(f"{SVG_NS}text") if t.get("class") == "v"}
    page = wr["document"]["pages"][0]
    assert (page["width_px"], page["height_px"]) == (width, height)

    found = [f for f in wr["fields"] if f["value"] is not None]
    assert {f["value"] for f in found} == set(printed)
    for f in found:
        x, baseline = printed[f["value"]]
        x0, y0, x1, y1 = (f["box"][0] * width / 1000, f["box"][1] * height / 1000,
                          f["box"][2] * width / 1000, f["box"][3] * height / 1000)
        narrowest = 0.45 * size * len(f["value"])  # no sans-serif line is narrower than this
        assert x0 <= x and x + narrowest <= x1, f["name"]
        assert y0 <= baseline - 0.7 * size and baseline + 0.2 * size <= y1, f["name"]
        assert y1 - y0 < 2 * size, f"{f['name']}: box spans more than one line"


SOURCES = [
    ROOT / "site" / "index.html",
    ROOT / "site" / "site.css",
    ROOT / "ui" / "index.html",
    *sorted((ROOT / "ui" / "src").glob("*.ts")),
    ROOT / "ui" / "src" / "styles.css",
    DEMO / "public" / "licence.svg",
]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_page_and_demo_load_nothing_from_another_site(path):
    text = path.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
    assert not re.search(r"https?://|//[a-z0-9.-]+\.[a-z]{2,}/|@import", text, re.I)


def test_product_page_makes_no_release_claims():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert "working name" in page and "not available for download" in page
    assert "<script" not in page
    assert not re.search(r'href="[^"#]*\.(?:zip|exe|msi|whl|ps1|sh)"', page)
    assert 'src="demo/index.html"' in page
