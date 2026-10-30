"""Writes the M5 demo sample: a synthetic specimen driving licence (public/licence.svg, copied
next to the demo page by `vite build --mode demo`) and the working result the demo review window
shows for it (working_result.licence.json).

Both come from one table, so every highlight box sits on the text the card prints. The issuer
"Musterland", the person and every number are made up; the card copies no real licence's layout,
number scheme or emblem. Run it after changing the table:

    python fixtures/demo/make_licence.py
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
W, H = 1000, 680  # card units; the page is W x H px, so 1 unit = 1 px
LABEL_SIZE, VALUE_SIZE = 16, 24
CHAR_W = 0.62  # width of one character per font-size unit, generous for the sans-serif stack
PAD = 6  # box padding around the printed value, in card units
LABEL_X, VALUE_X = 270, 450
# Printed labels sit left of their values, and rows are 58 apart: the review window draws each
# field's name just above its box (15px), which must not cover the card's own text.
ROW_Y = 58

# id, name, printed label, value, value_en, type, row (None: label under the photo), status,
# source, confidence
ROWS = [
    ("f1", "Surname", "Name", "MUSTERMANN", "MUSTERMANN", "name", 0, "from_template", "template", 0.97),
    ("f2", "Given Names", "Vorname", "ERIKA", "ERIKA", "name", 1, "from_template", "template", 0.96),
    ("f3", "Date of Birth", "Geburtsdatum", "12.08.1990", "1990-08-12", "date", 2,
     "from_template", "template", 0.95),
    ("f4", "Issue Date", "Ausstellungsdatum", "03.02.2021", "2021-02-03", "date", 3,
     "from_template", "template", 0.94),
    ("f5", "Expiry Date", "Gültig bis", "02.02.2036", "2036-02-02", "date", 4,
     "needs_review", "model_reread", 0.52),
    ("f6", "Licence Number", "Führerscheinnr.", "MX-0000-4711-SPEC", "MX-0000-4711-SPEC", "id", 5,
     "suggested", "model", 0.81),
    ("f7", "Categories", "Klassen", "B, AM", "B, AM", "text", 6, "from_template", "template", 0.93),
    ("f9", "Address", "Anschrift", "Musterstraße 1, 12345 Musterstadt", "Musterstraße 1, 12345 Musterstadt",
     "address", 7, "from_template", "template", 0.9),
    ("f10", "Conditions", "Auflagen", "Sehhilfe erforderlich", "Sehhilfe erforderlich", "text", 8,
     "not_translated", "model", 0.74),
    ("f8", "Issuing Authority", "Ausstellende Behörde", None, None, "text", None,
     "not_found", "template", 0.0),
]


def baseline(row: int) -> int:
    return 150 + ROW_Y * row


def text_box(x: int, baseline: int, text: str, size: int) -> tuple[float, float, float, float]:
    """Card-unit box of a printed line: cap height above the baseline, descenders below."""
    return (x, baseline - 0.8 * size, x + CHAR_W * size * len(text), baseline + 0.25 * size)


def grid_box(x: int, baseline: int, text: str) -> list[int]:
    """The value's box on the 0-1000 grid of both axes (DD-1), padded."""
    x0, y0, x1, y1 = text_box(x, baseline, text, VALUE_SIZE)
    return [round((x0 - PAD) * 1000 / W), round((y0 - PAD) * 1000 / H),
            round((x1 + PAD) * 1000 / W), round((y1 + PAD) * 1000 / H)]


def svg() -> str:
    t = []
    for _, _, label, value, _, _, row, *_ in ROWS:
        if row is None:  # a printed label whose value is missing on this card
            t.append(f'<text class="l" x="40" y="420">{escape(label)}</text>')
            continue
        t.append(f'<text class="l" x="{LABEL_X}" y="{baseline(row)}">{escape(label)}</text>')
        t.append(f'<text class="v" x="{VALUE_X}" y="{baseline(row)}">{escape(value)}</text>')
    rows = "\n  ".join(t)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <!-- Synthetic specimen for the Nabu demo. Not a real document; made-up issuer and person. -->
  <style>
    text {{ font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; fill: #1d2a33; }}
    .l {{ font-size: {LABEL_SIZE}px; fill: #4c6270; }}
    .v {{ font-size: {VALUE_SIZE}px; font-weight: 600; }}
  </style>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#e3f1ee"/><stop offset="1" stop-color="#f6efe0"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="{W}" height="{H}" rx="28" fill="url(#bg)" stroke="#9ab3ad" stroke-width="2"/>
  <rect x="0" y="0" width="{W}" height="96" rx="28" fill="#2f6f68"/>
  <rect x="0" y="60" width="{W}" height="36" fill="#2f6f68"/>
  <text x="40" y="52" style="font-size:32px;font-weight:700;fill:#ffffff">MUSTERLAND · FÜHRERSCHEIN</text>
  <text x="40" y="82" style="font-size:18px;fill:#d6ece8">DRIVING LICENCE · SPECIMEN</text>
  <text x="{W - 40}" y="64" text-anchor="end"
        style="font-size:22px;font-weight:700;fill:#ffd88a">SPECIMEN</text>
  <text x="560" y="420" text-anchor="middle" transform="rotate(-18 560 420)"
        style="font-size:120px;font-weight:800;fill:#2f6f68;fill-opacity:0.07">SPECIMEN</text>
  <rect x="40" y="128" width="200" height="250" rx="10" fill="#cfdcd9" stroke="#9ab3ad"/>
  <circle cx="140" cy="222" r="50" fill="#a9bdb8"/>
  <path d="M50 378 C 60 300, 220 300, 230 378 Z" fill="#a9bdb8"/>
  {rows}
  <text x="{W - 40}" y="{H - 18}" text-anchor="end"
        style="font-size:15px;fill:#7a8a90">SYNTHETIC SAMPLE · NOT A REAL DOCUMENT</text>
</svg>
"""


def working_result() -> dict:
    fields = []
    for fid, name, label, value, value_en, vtype, row, status, source, conf in ROWS:
        found = row is not None
        field = {
            "id": fid, "name": name, "printed_label": label, "value": value, "value_en": value_en,
            "value_type": vtype, "lang": "de", "page": 1,
            "box": grid_box(VALUE_X, baseline(row), value) if found else None,
            "box_source": "ocr" if found else None,
            "confidence": conf, "source": source, "status": [status],
        }
        if status == "not_translated":
            field["translation"] = {"value": "untranslated"}
        fields.append(field)
    return {
        "schema_version": "1.0",
        "verified": False,
        "document": {
            "source_file": "synthetic_specimen_licence.png",
            "route": "raster",
            "model_used": True,
            "pages": [{"n": 1, "width_px": W, "height_px": H, "lang": "de"}],
        },
        "header": {"document_type": "Driving licence", "region": None, "format": "Musterland 2021 card"},
        "link": {
            "outcome": "linked",
            "template_id": "tpl_driving_licence_musterland-2021",
            "template_version": 2,
            "score": 0.94,
            "candidates": [],
            "template": {
                "template_id": "tpl_driving_licence_musterland-2021", "document_type": "Driving licence",
                "region": None, "format": "Musterland 2021 card", "version": 2,
            },
        },
        "type_guess": None,
        "country_guess": None,
        "fields": fields,
    }


def write() -> None:
    (HERE / "public" / "licence.svg").write_text(svg(), encoding="utf-8", newline="\n")
    (HERE / "working_result.licence.json").write_text(
        json.dumps(working_result(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write()
