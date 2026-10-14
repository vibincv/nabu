"""Build and update templates from a verified working result (FR-7, DD-2). Writes go through
Store only; the store refuses any template that holds a session value (AR-7, DD-2.7).

What is kept per field: name, key, value type, order, and the anchor (printed label, page, the
label's box, the value's box relative to it, tolerance). Never a value (FR-7.7).

- value_offset is relative to the anchor box (DD-2.3). When the printed label cannot be found on
  the page (a field the user drew, or a label the model paraphrased), the anchor box is null and
  value_offset holds the value's own box on the page.
- Office and text files: page, box and value_offset are null (DD-2.4).
- Each version's header carries `change`: what changed, by field names only (FR-7.4).
"""

from __future__ import annotations

import string
from collections.abc import Iterable, Sequence

from nabu.config import Config
from nabu.fields.types import Field, WorkingResult
from nabu.ocr.words import Reading
from nabu.templates import find_label, header, slug
from nabu.templates.link import page_shapes, paginated

SCHEMA_VERSION = "1.0"


def type_key(document_type: str) -> str:
    return slug(document_type, "_", "document")


def format_id(format_name: str) -> str:
    return slug(format_name, "-", "format")


def next_format_name(templates: Iterable[dict], document_type: str, region: str | None) -> str:
    """Format A, Format B, ... within a document type and region (FR-7.3)."""
    key = type_key(document_type)
    used = {(header(t).get("format") or {}).get("name", "").casefold() for t in templates
            if header(t).get("document_type_key") == key and header(t).get("region") == region}
    for letter in string.ascii_uppercase:
        if f"format {letter}".casefold() not in used:
            return f"Format {letter}"
    n = 27
    while f"format {n}" in used:
        n += 1
    return f"Format {n}"


def _kept(result: WorkingResult) -> list[Field]:
    return [f for f in result.fields if not f.removed]


def _anchor(f: Field, reading: Reading, tolerance: float) -> dict:
    if not paginated(reading):
        return {"printed_label": f.printed_label, "page": None, "box": None,
                "value_offset": None, "tolerance": tolerance}
    page = next((p for p in reading.pages if p.n == f.page), None)
    hit = (find_label(f.printed_label, page.words, near=f.box)
           if page is not None and f.printed_label else None)
    lb = hit[0] if hit else None
    offset = None
    if f.box is not None:
        offset = ([f.box[0] - lb[0], f.box[1] - lb[1], f.box[2] - lb[0], f.box[3] - lb[1]]
                  if lb else list(f.box))
    return {"printed_label": f.printed_label, "page": f.page, "box": list(lb) if lb else None,
            "value_offset": offset, "tolerance": tolerance}


def _unique_key(name: str, used: set[str]) -> str:
    base = slug(name, "_", "field")[:56]
    key, n = base, 2
    while key in used:
        key, n = f"{base}_{n}", n + 1
    used.add(key)
    return key


def _fields(result: WorkingResult, reading: Reading, cfg: Config,
            base: dict | None) -> list[dict]:
    base_fields = {bf["key"]: bf for bf in (base or {}).get("fields", [])}
    used: set[str] = set()
    for f in _kept(result):  # keys of template fields stay stable across versions
        if f.template_key in base_fields:
            used.add(f.template_key)
    out = []
    for order, f in enumerate(_kept(result), 1):
        key = f.template_key if f.template_key in base_fields else _unique_key(f.name, used)
        anchor = _anchor(f, reading, cfg.anchor_tolerance)
        old = base_fields.get(key)
        if old is not None and anchor["value_offset"] is None and not anchor["box"]:
            anchor = old["anchor"]  # not read on this document: keep where it was (FR-7.4)
        out.append({"order": order, "name": f.name, "key": key, "value_type": f.value_type,
                    "anchor": anchor})
    return out


def _removed_labels(result: WorkingResult, base: dict | None) -> list[str]:
    kept = {(f.printed_label or "").casefold() for f in _kept(result)}
    labels = list((base or {}).get("removed_labels", []))
    labels += [f.printed_label for f in result.fields if f.removed and f.printed_label]
    return [lb for lb in dict.fromkeys(labels) if lb.casefold() not in kept]


def changes(result: WorkingResult, base: dict | None) -> dict:
    """Field names renamed, added and removed against the template (or the reading), plus
    value types changed and whether the order changed. Names only, never values."""
    kept = _kept(result)
    if base is None:
        return {"renamed": [[f.printed_label, f.name] for f in kept if f.printed_label
                            and "name" in f.translation and f.translation["name"] == "user"],
                "added": [f.name for f in kept if f.source == "user"],
                "removed": [f.name for f in result.fields if f.removed],
                "type_changed": [], "reordered": False}
    old = {bf["key"]: bf for bf in base.get("fields", [])}
    now = [f for f in kept if f.template_key in old]
    return {
        "renamed": [[old[f.template_key]["name"], f.name] for f in now
                    if f.name != old[f.template_key]["name"]],
        "added": [f.name for f in kept if f.template_key not in old],
        "removed": [bf["name"] for k, bf in old.items() if k not in {f.template_key for f in now}],
        "type_changed": [f.name for f in now if f.value_type != old[f.template_key]["value_type"]],
        "reordered": [f.template_key for f in now] != [k for k in old if k in
                                                         {f.template_key for f in now}],
    }


def differs(result: WorkingResult, t: dict) -> bool:
    """FR-6.12: a field name, value type or the field set changed against the linked template."""
    c = changes(result, t)
    return bool(c["renamed"] or c["added"] or c["removed"] or c["type_changed"] or c["reordered"])


def labels_to_store(result: WorkingResult) -> list[str]:
    """The printed labels that will be written to disk as anchors (FR-7.1)."""
    return list(dict.fromkeys(f.printed_label for f in _kept(result) if f.printed_label))


def build_new(result: WorkingResult, reading: Reading, cfg: Config, document_type: str,
              region: str | None, format_name: str, existing: Sequence[dict]) -> dict:
    key, fid = type_key(document_type), format_id(format_name)
    ids = {header(t).get("id") for t in existing}
    tid, n = f"tpl_{key}_{region or 'none'}_{fid}"[:120], 2
    base_id = tid
    while tid in ids:
        tid, n = f"{base_id}_{n}", n + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "template": {"id": tid, "document_type": document_type, "document_type_key": key,
                     "region": region, "format": {"id": fid, "name": format_name},
                     "version": 1, "pages": page_shapes(reading),
                     "change": {"kind": "created", **changes(result, None)}},
        "fields": _fields(result, reading, cfg, None),
        "removed_labels": _removed_labels(result, None),
    }


def build_update(base: dict, result: WorkingResult, reading: Reading, cfg: Config) -> dict:
    h = dict(header(base))
    h["version"] = int(h["version"]) + 1
    h["change"] = {"kind": "updated", **changes(result, base)}
    if h.get("pages") is not None and paginated(reading) and len(reading.pages) >= len(h["pages"]):
        h["pages"] = page_shapes(reading)
    return {"schema_version": SCHEMA_VERSION, "template": h,
            "fields": _fields(result, reading, cfg, base),
            "removed_labels": _removed_labels(result, base)}
