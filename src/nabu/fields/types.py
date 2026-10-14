"""The working result (DD-1): what the review window shows. In memory only (AD-8, FR-11.3).

Mirrors ui/src/types.ts and fixtures/working_result.sample.json. Additions to DD-1, reported to
the owner: `translation` per field (FR-9.7 statuses) and per page `text` and `messages`
(FR-3.4, FR-3.5, FR-9.9: the text is still shown when fields cannot be found); M3 adds per field
`template_key` and `name_suggestion`, and in `link` the template described, missing pages and
whether the user chose it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from nabu.model.types import Box, ValueType

Source = Literal["template", "model", "model_reread", "discovery_rules", "user"]
BoxSource = Literal["ocr", "model", "text_layer"]
Status = Literal["from_template", "suggested", "needs_review", "not_found", "not_translated",
                 "edited_by_user"]
TStatus = Literal["not_needed", "memory", "translated", "low_confidence", "untranslated", "user"]


@dataclass
class Field:
    id: str
    name: str = field(repr=False)  # English field name (FR-9.3)
    printed_label: str | None = field(repr=False)  # as printed, original language (FR-9.4)
    value: str | None = field(repr=False)  # as printed
    value_type: ValueType
    page: int
    source: Source
    confidence: float = 0.0
    value_en: str | None = field(default=None, repr=False)
    lang: str | None = None
    box: Box | None = None
    box_source: BoxSource | None = None
    status: list[Status] = field(default_factory=list)
    translation: dict[str, TStatus] = field(default_factory=dict)  # {"name": ..., "value": ...}
    removed: bool = False  # "Not required" in the review window (FR-6.8)
    template_key: str | None = None  # the template field this was read for (M3)
    name_suggestion: str | None = field(default=None, repr=False)  # from a similar template (FR-5.6)

    def flag(self, s: Status) -> None:
        if s not in self.status:
            self.status.append(s)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageInfo:
    n: int
    width_px: int | None
    height_px: int | None
    lang: str | None
    text: str = field(default="", repr=False)
    messages: list[str] = field(default_factory=list)


@dataclass
class WorkingResult:
    source_file: str
    pages: list[PageInfo]
    fields: list[Field] = field(repr=False)
    route: str = ""
    model_used: bool = False
    type_guess: str | None = field(default=None, repr=False)
    country_guess: str | None = None
    messages: list[str] = field(default_factory=list)
    link: dict | None = None  # DD-1.4; set by the pipeline (templates.link.Link.to_dict)

    def to_dict(self) -> dict:
        """The DD-1 shape the review window reads."""
        return {
            "schema_version": "1.0",
            "verified": False,
            "document": {"source_file": self.source_file, "route": self.route,
                         "model_used": self.model_used,
                         "pages": [asdict(p) for p in self.pages]},
            "header": {"document_type": self.type_guess, "region": self.country_guess,
                       "format": None},
            "link": self.link or {"outcome": "none", "template_id": None,
                                  "template_version": None, "score": 0.0, "candidates": [],
                                  "template": None, "missing_pages": [], "chosen": False},
            "type_guess": self.type_guess,
            "country_guess": self.country_guess,
            "messages": list(self.messages),
            "fields": [f.to_dict() for f in self.fields],
        }
