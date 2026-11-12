"""Discovery call per scanned page via ModelClient (FRD 10.3). M1.

One call per page (FR-4.3). The page's OCR text goes with the image as a hint. Every value is
grounded on OCR words (AD-2). The model's type and country guesses only pre-fill the header
(AD-10). An answer that stays invalid after the one repair marks the page "could not read
fields"; its text is still shown (FR-3.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nabu.errors import ModelOutputInvalid
from nabu.fields.grounding import ground
from nabu.model.client import ModelClient
from nabu.model.types import Box, ValueType
from nabu.ocr.words import Page
from nabu.store.guard import compact

COULD_NOT_READ = "could not read fields on this page: the model's answer was not valid JSON"


@dataclass
class ModelPair:
    label: str = field(repr=False)  # the field's name
    printed_label: str | None = field(repr=False)  # None: the value is printed with no label
    value: str | None = field(repr=False)
    value_type: ValueType
    page: int
    box: Box | None
    box_source: str | None
    confidence: float
    exact: bool  # the value matched OCR words exactly


@dataclass
class PageResult:
    pairs: list[ModelPair]
    type_guess: str | None = field(default=None, repr=False)
    country_guess: str | None = None
    message: str | None = None


def discover_page(client: ModelClient, page: Page) -> PageResult:
    assert page.image is not None, "discovery needs the rendered page"
    try:
        d = client.discover_page(page.image, page.text)
    except ModelOutputInvalid:
        return PageResult(pairs=[], message=COULD_NOT_READ)
    pairs = []
    for f in d.fields:
        label = _bare(f.label)  # "Datum:" is the label "Datum"
        printed = _bare(f.printed_label or "") or None
        value = (f.value or "").strip() or None
        if value is not None and compact(value) == compact(label):
            continue  # a title or heading echoed as label and value is not a field
        if value is not None and printed is not None and compact(value) == compact(printed):
            printed = None  # the value given as its own label: it is printed alone
        g = ground(value, page, f.box)
        pairs.append(ModelPair(label=label, printed_label=printed, value=value,
                               value_type=f.value_type, page=page.n, box=g.box,
                               box_source=g.box_source, confidence=f.confidence, exact=g.exact))
    return PageResult(pairs=pairs, type_guess=d.type_guess, country_guess=d.country_guess)


def _bare(label: str) -> str:
    return label.strip().rstrip(":：").strip()
