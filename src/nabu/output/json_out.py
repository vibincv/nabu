"""Verified output JSON (DD-3). Returned to the browser; Nabu writes no copy (FR-8.5). M2.

The field order is the working result's order, which is the document's reading order (FR-7.8);
the review list's "needs review first" sort is display only. A linked template's order replaces
it in M3.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TypedDict

from nabu.fields.types import WorkingResult

SCHEMA_VERSION = "1.0"
_COMBINED = re.compile(r" \(\+\d+ images?\)$")  # "front.jpg (+1 images)" from pipeline.read_document
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_LANG = re.compile(r"^[a-z]{2}$")


class Header(TypedDict):
    document_type: str | None
    region: str | None
    format: str | None


def build(result: WorkingResult, header: Header, verified_at: datetime,
          template_id: str | None = None, template_version: int | None = None) -> dict:
    kept = [f for f in result.fields if not f.removed]
    fields: list[dict] = []
    not_found: list[str] = []
    for f in kept:
        value = f.value_en if f.value_en is not None else f.value
        item: dict = {"name": f.name, "value": value}
        if f.value is not None and value is not None and f.value != value:
            item["original"] = f.value
        fields.append(item)
        if value is None:
            not_found.append(f.name)

    terms: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for f in kept:
        if f.lang is None or not _LANG.match(f.lang):
            continue  # an unknown language cannot be named; the term still shows in the window
        for part, text in (("name", f.printed_label), ("value", f.value)):
            if f.translation.get(part) == "untranslated" and text and (text, f.lang) not in seen:
                seen.add((text, f.lang))
                terms.append({"term": text, "lang": f.lang})

    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": header["document_type"],
        "region": header["region"],
        "format": header["format"],
        "template_id": template_id,
        "template_version": template_version,
        "source_file": _COMBINED.sub("", result.source_file),
        "verified_at": verified_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fields": fields,
        "not_found": not_found,
        "untranslated_terms": terms,
    }


def dumps(doc: dict) -> bytes:
    """Byte-identical for the same input (FR-8.6): fixed key order from build(), fixed layout."""
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def file_name(source_file: str) -> str:
    """<source file name>.nabu.json (FR-8.5), safe as a download name on every OS."""
    return _UNSAFE.sub("_", _COMBINED.sub("", source_file)) + ".nabu.json"
