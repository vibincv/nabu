"""The model client the pipeline uses (FRD 10.4). Runtime- and model-independent.

- Prompts are FRD 10.3. Every answer must be JSON: it is checked against a schema, with one
  repair attempt; after that ModelOutputInvalid (FR-3.5). Raw replies are never logged.
- Everything the model returns is a suggestion the user verifies (AD-10). Answers are clamped:
  unknown value types become "text", confidence outside 0-1 is clipped, missing confidence is 0
  (so the field needs review), malformed boxes are dropped.
- Images are limited to max_image_edge_px on the long edge (FR-10.3). Boxes are converted to
  the 0-1000 grid per profile (FR-10.6).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nabu.config import Config
from nabu.errors import ConfigError, ModelOutputInvalid, ModelUnavailable
from nabu.model import images
from nabu.model.profiles import ModelProfile, resolve_profile
from nabu.model.runtime import ChatRequest, ModelRuntime, make_runtime, same_model
from nabu.model.types import (
    VALUE_TYPES,
    Box,
    CropField,
    DiscoveredField,
    FieldReading,
    PageDiscovery,
    PageImage,
    TranslateItem,
    Translation,
)

log = logging.getLogger("nabu.model")
W = TypeVar("W", bound=BaseModel)

_COORD_WORDS = {
    "pixels": "Give each box in pixel coordinates of the image you received, top-left origin.",
    "none": "Give each box in pixel coordinates of the image you received, top-left origin.",
    "grid_1000": "Give each box on a 0-1000 grid of the image, top-left origin.",
    "unit": "Give each box as fractions from 0 to 1 of the image, top-left origin.",
}

# M6 finding 2 (2026-10-30): asked only for "every printed label and its value", qwen3.5:9b
# with thinking off stopped after the first field, echoed each line of a label-less ID card as
# label and value, and listed headings as values. Measured on synthetic cards in three layouts.
_DISCOVERY_SYSTEM = (
    "You read one document page. Return ONLY JSON matching the schema.\n"
    "List every field on the page: each value, with the label printed beside or above it. "
    "Pages usually have several fields; list all of them, in reading order.\n"
    "Some documents print a value with no label (an ID card prints the holder's name alone). "
    "Still list it: set printed_label to null and name to a short English name for it.\n"
    "Also list fixed printed text that is the same on every copy of this form (headings, "
    "titles, the issuer's name, words like Signature) with kind fixed_text and value null. "
    "Everything that differs between people or copies (names, numbers, dates) is kind field.\n"
    "Copy values exactly as printed. Never invent a value.\n"
    "{coords}\n"
    "country_guess: ISO 3166-1 alpha-2 code, or null if unsure.\n"
    "value_type is one of: name, id, number, date, amount, address, text."
)
_REREAD_SYSTEM = (
    "You read one field from a cropped part of a document. Return ONLY JSON.\n"
    "If the value is not visible, return value = null. Never invent a value.\n"
    "{coords}"
)
_TRANSLATE_SYSTEM = (
    "Translate each item into English. Return ONLY JSON.\n"
    'If you are not sure of an item, return it unchanged with status "untranslated". Never guess.\n'
    'If an item is a proper name (person, company, place, product) or a code, return it unchanged '
    'with status "not_needed".\n'
    "status is one of: translated, low_confidence, untranslated, not_needed."
)
_REPAIR = ("\n\nYour previous answer was not valid JSON for the required schema. "
           "Answer again with ONLY the JSON object.")

_NOTHING = {"", "null", "none", "unknown", "n/a"}  # a guess written as a word for "no guess"
_BOX = {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 4, "maxItems": 4}
_NULLABLE_STR = {"type": ["string", "null"]}

DISCOVERY_SCHEMA = {
    "type": "object",
    "properties": {
        "type_guess": _NULLABLE_STR,
        "country_guess": _NULLABLE_STR,
        "fields": {"type": "array", "items": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["field", "fixed_text"]},
                           "name": {"type": "string"}, "printed_label": _NULLABLE_STR,
                           "value": _NULLABLE_STR,
                           "value_type": {"type": "string", "enum": sorted(VALUE_TYPES)},
                           "bbox": _BOX, "confidence": {"type": "number"}},
            "required": ["kind", "name", "printed_label", "value", "value_type", "bbox",
                         "confidence"],
        }},
    },
    "required": ["type_guess", "country_guess", "fields"],
}
REREAD_SCHEMA = {
    "type": "object",
    "properties": {"value": _NULLABLE_STR, "bbox": _BOX, "confidence": {"type": "number"}},
    "required": ["value", "bbox", "confidence"],
}
TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "english": {"type": "string"},
                       "status": {"type": "string",
                                  "enum": ["translated", "low_confidence", "untranslated",
                                           "not_needed"]}},
        "required": ["id", "english", "status"],
    }}},
    "required": ["items"],
}


# ---- answer validation (lenient where safe, strict where it matters) ----------------------------
def _clip_confidence(v: object) -> float:
    try:
        return min(1.0, max(0.0, float(v)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _WireField(_Wire):
    kind: str = "field"  # "fixed_text": printed form text, never a value
    name: str = ""
    printed_label: str | None = None
    label: str = ""  # the earlier answer shape: the printed label, also the name
    value: str | None = None
    value_type: str = "text"
    bbox: object = None
    confidence: float = 0.0

    @field_validator("name", "label", mode="before")
    @classmethod
    def _label(cls, v: object) -> str:
        return "" if v is None else str(v)

    @field_validator("printed_label", mode="before")
    @classmethod
    def _printed(cls, v: object) -> str | None:
        return None if v is None else (str(v).strip() or None)

    def printed(self) -> str | None:
        """The printed label; an answer in the earlier shape gives it as `label`."""
        if "printed_label" in self.model_fields_set or "name" in self.model_fields_set:
            return self.printed_label
        return self.label.strip() or None

    @field_validator("value_type", mode="before")
    @classmethod
    def _known_type(cls, v: object) -> str:
        v = str(v or "").strip().lower()
        return v if v in VALUE_TYPES else "text"

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: object) -> float:
        return _clip_confidence(v)

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, v: object) -> str | None:
        return None if v is None else str(v)


class _WireDiscovery(_Wire):
    type_guess: str | None = None
    country_guess: str | None = None
    fields: list[_WireField] = Field(default_factory=list)

    @field_validator("type_guess", mode="before")
    @classmethod
    def _type(cls, v: object) -> str | None:
        v = str(v).strip() if v is not None else ""
        return None if v.casefold() in _NOTHING else v[:80]

    @field_validator("country_guess", mode="before")
    @classmethod
    def _country(cls, v: object) -> str | None:
        v = str(v).strip().upper() if v is not None else ""
        return v if re.fullmatch(r"[A-Z]{2}", v) else None


class _WireReread(_Wire):
    value: str | None = None
    bbox: object = None
    confidence: float = 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: object) -> float:
        return _clip_confidence(v)

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, v: object) -> str | None:
        return None if v is None else str(v)


class _WireTranslation(_Wire):
    id: str
    english: str
    status: str

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, v: object) -> str:
        v = str(v or "").strip().lower()
        return v if v in ("translated", "low_confidence", "untranslated", "not_needed") \
            else "untranslated"


class _WireTranslate(_Wire):
    items: list[_WireTranslation]


def _extract_json(text: str) -> object:
    """Parse a reply that should be one JSON object. Tolerates code fences and stray text
    around the object; anything else raises ValueError."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    return json.loads(t[start:end + 1])


class ModelClient:
    def __init__(self, cfg: Config, runtime: ModelRuntime | None = None) -> None:
        if not cfg.model:
            raise ConfigError("no model is configured. Run: nabu models use <model>")
        self.model: str = cfg.model
        self.profile: ModelProfile = resolve_profile(cfg.model, cfg.model_profile, cfg.model_profiles)
        self.max_edge = min(cfg.max_image_edge_px,
                            self.profile.max_image_edge_px or cfg.max_image_edge_px)
        self.runtime = runtime or make_runtime(cfg)

    def close(self) -> None:
        self.runtime.close()

    def available(self) -> bool:
        """The runtime answers and the configured model is installed (FR-1.7)."""
        if not self.runtime.available():
            return False
        try:
            return any(same_model(m, self.model) for m in self.runtime.models())
        except ModelUnavailable:
            return False

    # ---- FRD 10.4 --------------------------------------------------------------------------
    def discover_page(self, page: PageImage, ocr_text: str) -> PageDiscovery:
        img = images.fit(page, self.max_edge)
        user = f"OCR text of this page (may contain errors):\n{ocr_text}"
        system = _DISCOVERY_SYSTEM.format(coords=_COORD_WORDS[self.profile.coords])
        wire = self._ask(system, user, (img.data,), DISCOVERY_SCHEMA, _WireDiscovery)
        fields = []
        for f in wire.fields:
            name = (f.name or f.label).strip()
            # Fixed text is dropped here, before its text could be registered as a value: it
            # stays page text, so it can become a landmark.
            if f.kind == "fixed_text" or not name:  # an item without a name is dropped
                continue
            raw = images.raw_box(f.bbox)
            fields.append(DiscoveredField(
                label=name, value=f.value, value_type=f.value_type,  # type: ignore[arg-type]
                box=images.to_grid(raw, self.profile.coords, img.width_px, img.height_px),
                raw_box=raw, confidence=f.confidence, printed_label=f.printed()))
        return PageDiscovery(fields=fields, type_guess=wire.type_guess,
                             country_guess=wire.country_guess)

    def reread_crop(self, page: PageImage, box: Box, field: CropField) -> FieldReading:
        part, area = images.crop(page, box)
        part = images.fit(part, self.max_edge)
        user = (f'Field: {field.name}, printed label "{field.printed_label}", '
                f"value type {field.value_type}")
        system = _REREAD_SYSTEM.format(coords=_COORD_WORDS[self.profile.coords])
        wire = self._ask(system, user, (part.data,), REREAD_SCHEMA, _WireReread)
        on_crop = images.to_grid(images.raw_box(wire.bbox), self.profile.coords,
                                 part.width_px, part.height_px)
        return FieldReading(value=wire.value, box=images.crop_to_page(on_crop, area),
                            confidence=wire.confidence)

    def translate(self, items: list[TranslateItem], lang: str,
                  doc_type: str | None) -> list[Translation]:
        if not items:
            return []
        listing = json.dumps([{"id": i.id, "text": i.text} for i in items], ensure_ascii=False)
        user = (f"Source language: {lang}. Document type: {doc_type or 'unknown'}.\n"
                f"Items: {listing}")
        wire = self._ask(_TRANSLATE_SYSTEM, user, (), TRANSLATE_SCHEMA, _WireTranslate)
        answers = {t.id: t for t in wire.items}
        out = []
        for i in items:  # every item comes back, in order; anything missing stays untranslated
            a = answers.get(i.id)
            if a is None or a.status == "untranslated" or not a.english.strip():
                out.append(Translation(id=i.id, english=i.text, status="untranslated"))
            elif a.status == "not_needed":  # kept as printed, whatever the model wrote
                out.append(Translation(id=i.id, english=i.text, status="not_needed"))
            else:
                out.append(Translation(id=i.id, english=a.english, status=a.status))  # type: ignore[arg-type]
        return out

    # ---- one call + one repair (FR-3.5) -------------------------------------------------------
    def _ask(self, system: str, user: str, imgs: tuple[bytes, ...], schema: dict,
             wire: type[W]) -> W:
        req = ChatRequest(model=self.model, system=system, user=user, images=imgs,
                          schema=schema if self.profile.structured_output else None,
                          disable_thinking=self.profile.disable_thinking,
                          temperature=self.profile.temperature)
        for attempt in (1, 2):
            reply = self.runtime.chat(req)
            try:
                return wire.model_validate(_extract_json(reply))
            except (ValueError, ValidationError):
                log.info("model answer was not valid JSON (attempt %d)", attempt)
                req = ChatRequest(model=req.model, system=req.system, user=user + _REPAIR,
                                  images=req.images, schema=req.schema,
                                  disable_thinking=req.disable_thinking,
                                  temperature=req.temperature)
        raise ModelOutputInvalid("could not read fields: the model's answer was not valid JSON")


def build_client(cfg: Config) -> ModelClient | None:
    """None when no model is configured: no-model mode (FR-3.4)."""
    return ModelClient(cfg) if cfg.model else None
