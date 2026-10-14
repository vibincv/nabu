"""Value-type rules (FR-9.6), memory first, then model; flag untranslated. M1.

Order for every label and every translatable value (FR-9.5, AD-12):
1. Already English, or kept by rule (name, id, number)      -> not_needed
2. Dates -> ISO 8601 using the region for day-month order; ambiguous -> printed form + needs_review
3. Amounts -> "<number> <ISO 4217>"; no currency known -> printed form + needs_review
4. Translation memory                                      -> memory
5. The model, one text-only call per page and language    -> translated / low_confidence
6. Anything else                                          -> untranslated: original kept, flagged
A model answer that equals the original is untranslated, never "translated" (FR-9.7).
With no model, only memory translates (FR-9.10).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from nabu.errors import ModelOutputInvalid, ModelUnavailable
from nabu.fields import values
from nabu.fields.types import Field
from nabu.lang.memory import TranslationMemory
from nabu.model.client import ModelClient
from nabu.model.types import TranslateItem
from nabu.store.guard import compact

log = logging.getLogger(__name__)

KEEP_TYPES = frozenset({"name", "id", "number"})
TRANSLATE_TYPES = frozenset({"address", "text"})
ENGLISH = "en"


def apply_value_rules(f: Field, region: str | None) -> bool:
    """Set value_en for kept, date and amount values. Returns True when the value still needs
    translating (address and text)."""
    if f.value is None:
        f.value_en = None
        f.translation["value"] = "not_needed"
        return False
    if f.value_type in KEEP_TYPES:
        f.value_en = f.value
        f.translation["value"] = "not_needed"
        return False
    if f.value_type == "date":
        d = values.parse_date(f.value, region)
        if d is None or d.iso is None:
            f.value_en = f.value
            f.flag("needs_review")
            f.translation["value"] = "untranslated"
        else:
            f.value_en = d.iso
            f.translation["value"] = "not_needed"
        return False
    if f.value_type == "amount":
        a = values.parse_amount(f.value, region)
        if a is None or a.number is None or a.currency is None:
            f.value_en = f.value
            f.flag("needs_review")
            f.translation["value"] = "untranslated"
        else:
            f.value_en = f"{a.number} {a.currency}"
            f.translation["value"] = "not_needed"
        return False
    if f.lang == ENGLISH or not _has_letters(f.value):
        f.value_en = f.value
        f.translation["value"] = "not_needed"
        return False
    return True


def _has_letters(s: str) -> bool:
    return any(c.isalpha() for c in s)


@dataclass
class Outcome:
    messages: list[str] = field(default_factory=list)  # for the user; never contain values
    model_calls: int = 0


def translate_fields(fields: list[Field], memory: TranslationMemory, model: ModelClient | None,
                     region: str | None, doc_type: str | None = None) -> Outcome:
    """Fill name (English) and value_en for every field."""
    out = Outcome()
    messages = out.messages
    # (lang, page) -> items; one model call per page and language
    pending: dict[tuple[str, int], list[tuple[Field, str, str]]] = defaultdict(list)
    for f in fields:
        _label(f, memory, doc_type, pending)
        if apply_value_rules(f, region):
            hit = memory.lookup(f.value or "", f.lang, doc_type)
            if hit is not None:
                f.value_en, f.translation["value"] = hit, "memory"
            elif model is None:
                _untranslated(f, "value")
            else:
                pending[(f.lang or "", f.page)].append((f, "value", f.value or ""))
    if model is None:  # FR-9.10: only memory translates
        for items in pending.values():
            for f, part, _ in items:
                _untranslated(f, part)
        return out
    for (lang, _page), items in pending.items():
        batch = [TranslateItem(id=str(i), text=text) for i, (_, _, text) in enumerate(items)]
        try:
            answers = model.translate(batch, lang or "unknown", doc_type)
            out.model_calls += 1
        except (ModelOutputInvalid, ModelUnavailable) as e:
            log.info("translation call failed: %s", type(e).__name__)
            for f, part, _ in items:
                _untranslated(f, part)
            if isinstance(e, ModelUnavailable) and e.message not in messages:
                messages.append(e.message)
            continue
        for (f, part, text), a in zip(items, answers, strict=True):
            english = a.english.strip()
            if a.status == "not_needed" and part == "value":
                _set(f, part, text, "not_needed")
            elif a.status in ("translated", "low_confidence") and english and \
                    compact(english) != compact(text):
                _set(f, part, english, a.status)
                if a.status == "low_confidence":
                    f.flag("needs_review")
            else:  # unchanged, unsure, or "not_needed" for a label: never a guess
                _untranslated(f, part)
    return out


def _label(f: Field, memory: TranslationMemory, doc_type: str | None,
           pending: dict[tuple[str, int], list[tuple[Field, str, str]]]) -> None:
    label = f.printed_label or ""
    if not label or f.lang == ENGLISH or not _has_letters(label):
        f.name = label or f.name
        f.translation["name"] = "not_needed"
        return
    hit = memory.lookup(label, f.lang, doc_type)
    if hit is not None:
        f.name, f.translation["name"] = hit, "memory"
        return
    f.name = label  # the original stays until a translation arrives (FR-9.7)
    pending[(f.lang or "", f.page)].append((f, "name", label))


def _set(f: Field, part: str, text: str, status: str) -> None:
    if part == "name":
        f.name = text
    else:
        f.value_en = text
    f.translation[part] = status  # type: ignore[assignment]


def _untranslated(f: Field, part: str) -> None:
    if part == "value":
        f.value_en = f.value
    else:
        f.name = f.printed_label or f.name
    f.translation[part] = "untranslated"
    f.flag("not_translated")
