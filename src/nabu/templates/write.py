"""Build and update templates from a verified working result (FR-7, DD-2). Writes go through
Store only; the store refuses any template that holds a session value (AR-7, DD-2.7).

What is kept per field: name, key, value type, order, and the anchor (printed label, page, the
label's box, the value's box relative to it, tolerance). Never a value (FR-7.7).

- value_offset is relative to the anchor box (DD-2.3). When the printed label cannot be found on
  the page (a field the user drew, or a label the model paraphrased), the anchor box is null and
  value_offset holds the value's own box on the page.
- Office and text files: page, box and value_offset are null (DD-2.4).
- `landmarks` (DD-2 addition): fixed printed lines that are not values, so a template whose
  fields have no printed label (an ID card) can still link and be placed on a photo.
- Each version's header carries `change`: what changed, by field names only (FR-7.4).
"""

from __future__ import annotations

import string
from collections.abc import Iterable, Sequence

from nabu.config import Config
from nabu.fields.types import Field, WorkingResult
from nabu.model.types import Box
from nabu.ocr.words import Reading, Word, union
from nabu.store.guard import find_values
from nabu.templates import MAX_RUN, align, find_label, fold, header, slug
from nabu.templates.link import page_shapes, paginated

SCHEMA_VERSION = "1.0"
MAX_LANDMARKS = 6
MIN_LANDMARK_LEN = 6  # letters and digits
MIN_LANDMARK_CONF = 0.8
RUN_GAP = 30  # grid units: a wider gap starts another landmark


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


def _removed_labels(result: WorkingResult, base: dict | None, values: list[str]) -> list[str]:
    kept = {(f.printed_label or "").casefold() for f in _kept(result)}
    labels = list((base or {}).get("removed_labels", []))
    labels += [f.printed_label for f in result.fields if f.removed and f.printed_label]
    return [lb for lb in _no_values(dict.fromkeys(labels), values) if lb.casefold() not in kept]


def _no_values(names: Iterable[str], values: list[str]) -> list[str]:
    """Names of removed fields without those that carry a value: a label-less document gets
    labels taken from its printed values (AR-7). Such a label never recurs, so nothing is lost."""
    return [n for n in names if not find_values(n, values)]


def _change(kind: str, result: WorkingResult, base: dict | None, values: list[str]) -> dict:
    c = changes(result, base)
    return {"kind": kind, **c, "removed": _no_values(c["removed"], values)}


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


def _overlaps(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def landmarks(result: WorkingResult, reading: Reading, values: Iterable[str]) -> list[dict]:
    """Fixed printed text that lets a template link when its fields have no printed label (an
    ID card prints values with no "Name:" beside them). DD-2 addition, M3 fix 2026-10-14.

    A line qualifies when it is not a field value or label (no overlap with any field's box,
    removed fields included), has few digits, was read with confidence, is not a session value,
    and appears once on its page. The longest MAX_LANDMARKS lines are kept. The save dialog lists
    them and the user can leave any out (FR-7.1), because a line that was never a field could
    still be personal (FRD Q22)."""
    if not paginated(reading):
        return []
    values = list(values)
    taken: dict[int, list[Box]] = {}
    for f in result.fields:
        if f.box is not None:
            taken.setdefault(f.page, []).append(f.box)
    labels = {fold(f.printed_label) for f in _kept(result) if f.printed_label}  # anchors already
    found: list[tuple[float, int, int, Box, str]] = []
    for page in reading.pages:
        counts: dict[str, int] = {}
        runs = []
        for line in page.lines:
            if line.cells is not None or any(w.box is None for w in line.words):
                continue
            for words in _runs(list(line.words)):
                if len(words) > MAX_RUN:
                    continue
                text = " ".join(w.text for w in words).strip()
                key = fold(text)
                counts[key] = counts.get(key, 0) + 1
                runs.append((words, text, key))
        for words, text, key in runs:
            box = union([w.box for w in words])
            if (box is None or len(key) < MIN_LANDMARK_LEN or key in labels or counts[key] > 1
                    or sum(c.isdigit() for c in key) * 3 > len(key)
                    or min(w.conf for w in words) < MIN_LANDMARK_CONF
                    or any(_overlaps(box, b) for b in taken.get(page.n, []))
                    or find_values(text, values)):
                continue
            # Surest reading first: text the OCR misread (another script) will not match again.
            conf = round(min(w.conf for w in words) * 20) / 20
            found.append((conf, len(key), page.n, box, text))
    found.sort(key=lambda x: (-x[0], -x[1], x[2], x[3][1], x[3][0]))
    keep = sorted(found[:MAX_LANDMARKS], key=lambda x: (x[2], x[3][1], x[3][0]))
    return [{"text": text, "page": n, "box": list(box)} for _, _, n, box, text in keep]


def _runs(words: list[Word]) -> list[list[Word]]:
    """A line split where the gap between words is wide: two headings on one line are two
    landmarks, so losing one (it touches a field) keeps the other."""
    out: list[list[Word]] = []
    for w in words:
        if out and w.box[0] - out[-1][-1].box[2] <= RUN_GAP:  # type: ignore[index]
            out[-1].append(w)
        else:
            out.append([w])
    return out


def _kept_landmarks(base: dict, reading: Reading, cfg: Config) -> list[dict]:
    """On update, only landmarks of the template that are also on this document are kept: the
    list can only shrink, so an update never adds new text to disk. Each keeps the box where it
    is on this document, as the update also takes this document's page shape and fields."""
    out = []
    for page in reading.pages:
        items = [a for a in align.anchors(base, page.n) if a.field is None]
        pl = align.place(items, page, cfg.anchor_tolerance, align.page_aspect(base, page.n))
        out += [{"text": items[k].text, "page": page.n, "box": list(pl.hits[k][0])}
                for k in sorted(pl.hits)]
    return out


def _without(found: list[dict], excluded: Iterable[str]) -> list[dict]:
    ex = {fold(x) for x in excluded}
    return [lm for lm in found if fold(lm["text"]) not in ex]


def build_new(result: WorkingResult, reading: Reading, cfg: Config, document_type: str,
              region: str | None, format_name: str, existing: Sequence[dict],
              values: Iterable[str] = (), excluded: Iterable[str] = ()) -> dict:
    values = list(values)
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
                     "change": _change("created", result, None, values)},
        "fields": _fields(result, reading, cfg, None),
        "landmarks": _without(landmarks(result, reading, values), excluded),
        "removed_labels": _removed_labels(result, None, values),
    }


def build_update(base: dict, result: WorkingResult, reading: Reading, cfg: Config,
                 values: Iterable[str] = (), excluded: Iterable[str] = ()) -> dict:
    values = list(values)
    h = dict(header(base))
    h["version"] = int(h["version"]) + 1
    h["change"] = _change("updated", result, base, values)
    if h.get("pages") is not None and paginated(reading) and len(reading.pages) >= len(h["pages"]):
        h["pages"] = page_shapes(reading)
    marks = (_kept_landmarks(base, reading, cfg) if "landmarks" in base and base["landmarks"]
             else landmarks(result, reading, values))  # templates saved before landmarks
    return {"schema_version": SCHEMA_VERSION, "template": h,
            "fields": _fields(result, reading, cfg, base),
            "landmarks": _without(marks, excluded),
            "removed_labels": _removed_labels(result, base, values)}


def landmarks_to_store(result: WorkingResult, reading: Reading, cfg: Config, values: Iterable[str],
                       base: dict | None) -> list[str]:
    """The landmark lines a save would write (shown in the save dialog with an opt-out)."""
    found = (_kept_landmarks(base, reading, cfg) if base and base.get("landmarks")
             else landmarks(result, reading, values))
    return [lm["text"] for lm in found]
