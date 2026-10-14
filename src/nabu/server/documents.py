"""The document being reviewed: reading job, link, edits, verify, save and output (FR-5.8, FR-6,
FR-7, FR-8), and the template manager and translation memory routes (FR-7.9 to FR-7.12, FR-9.8).

One document is open at a time. Everything here is in process memory and is released when the
document is closed (FR-11.3). Every value the user types is registered with the session, so the
store refuses to write it anywhere (AR-7).

Revision rule: each edit increases `rev`. Verify records the revision it summarised, the save
choice records the revision it confirmed, and the output is served only when the confirmed
revision is the current one (API-4). An edit after Verify therefore needs a new Verify.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nabu import pipeline
from nabu.config import Config
from nabu.errors import NabuError
from nabu.fields.types import Field, WorkingResult
from nabu.model.types import VALUE_TYPES
from nabu.ocr.words import Reading, lines_from_words
from nabu.output import json_out
from nabu.router import Upload
from nabu.session import Session
from nabu.store.store import Store
from nabu.templates import describe, write
from nabu.templates import header as template_header

log = logging.getLogger(__name__)

REGION = re.compile(r"^[A-Z]{2}$")
MAX_NAME = 200
MAX_VALUE = 10_000
TERMINAL = ("done", "error", "cancelled")
NO_STORE = "templates are not available in this window"


class Conflict(NabuError):
    """The request does not fit the document's current state (HTTP 409)."""


class NotFound(NabuError):
    """No such document, field, page or term (HTTP 404)."""


class Invalid(NabuError):
    """A request body that cannot be applied (HTTP 400)."""


@dataclass
class ReviewDocument:
    uploads: list[Upload] = field(repr=False)
    session: Session = field(default_factory=Session)
    id: str = field(default_factory=lambda: secrets.token_urlsafe(12))
    state: str = "reading"  # reading | ready | error | cancelled
    result: WorkingResult | None = field(default=None, repr=False)
    header: json_out.Header = field(
        default_factory=lambda: {"document_type": None, "region": None, "format": None}, repr=False)
    error: str | None = None
    rev: int = 0
    verified_rev: int | None = None
    saved_rev: int | None = None
    verified_at: datetime | None = None
    cfg: Config = field(default_factory=Config, repr=False)
    store: Store | None = field(default=None, repr=False)
    # The template this document is read with, or was saved to (FR-6.12); none before linking.
    template: dict | None = field(default=None, repr=False)
    saved_template: tuple[str, int] | None = None  # template id and version for the output
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _events: list[dict] = field(default_factory=list, repr=False)
    _cond: threading.Condition = field(default_factory=threading.Condition, repr=False)

    # ---- events (server-sent to the window) ----------------------------------------------
    def emit(self, event: dict) -> None:
        with self._cond:
            self._events.append(event)
            self._cond.notify_all()

    def events_after(self, index: int, timeout: float) -> list[dict]:
        """Events from `index` on; waits up to `timeout` seconds for one to arrive."""
        with self._cond:
            if len(self._events) <= index:
                self._cond.wait(timeout)
            return list(self._events[index:])

    # ---- the working result as the window reads it (DD-1) --------------------------------
    def to_dict(self) -> dict:
        if self.result is None:
            return {"id": self.id, "state": self.state, "error": self.error}
        d = self.result.to_dict()
        d["header"] = dict(self.header)
        d["verified"] = self.saved_rev == self.rev
        d.update(id=self.id, state=self.state, error=None)
        return d

    def _ready(self) -> WorkingResult:
        if self.state != "ready" or self.result is None:
            raise Conflict("the document is not read yet")
        return self.result

    def _field(self, field_id: str) -> Field:
        for f in self._ready().fields:
            if f.id == field_id:
                return f
        raise NotFound("no such field")

    def _changed(self) -> None:
        self.rev += 1

    def _keep(self, value: str | None) -> None:
        self.session.register_value(value)

    # ---- edits (FR-6.5 to FR-6.9) -------------------------------------------------------
    def edit_field(self, field_id: str, body: dict) -> Field:
        f = self._field(field_id)
        if "name" in body:
            name = _text(body["name"], "name", MAX_NAME)
            if not name:
                raise Invalid("a field name cannot be empty")
            f.name = name
            f.translation["name"] = "user"
            f.name_suggestion = None
        if "value" in body:
            value = _text(body["value"], "value", MAX_VALUE, allow_none=True) or None
            f.value_en = value
            f.translation["value"] = "user"
            self._keep(value)
            if value is not None and "not_found" in f.status:
                f.status.remove("not_found")
        if "value_type" in body:
            if body["value_type"] not in VALUE_TYPES:
                raise Invalid("unknown value type")
            f.value_type = body["value_type"]
        if "removed" in body:
            if not isinstance(body["removed"], bool):
                raise Invalid("removed must be true or false")
            f.removed = body["removed"]
        if body.get("accept") is True:  # "suggested" accepted with one click (UX-2.7)
            if f.name_suggestion:  # the similar template's name (FR-5.6)
                f.name, f.name_suggestion = f.name_suggestion, None
                f.translation["name"] = "user"
            for s in ("suggested", "needs_review"):
                if s in f.status:
                    f.status.remove(s)
        if {"name", "value", "value_type"} & body.keys():
            f.flag("edited_by_user")
        _sync_not_translated(f)
        self._changed()
        return f

    def add_field(self, body: dict) -> Field:
        """A field the user drew on the page (FR-6.9): the value is the words inside the box."""
        result = self._ready()
        name = _text(body.get("name"), "name", MAX_NAME)
        if not name:
            raise Invalid("a field name cannot be empty")
        page_n, box = body.get("page"), body.get("box")
        page = next((p for p in result.pages if p.n == page_n), None)
        if page is None:
            raise NotFound("no such page")
        if (not isinstance(box, list) or len(box) != 4
                or not all(isinstance(v, (int, float)) for v in box)):
            raise Invalid("box must be [x0, y0, x1, y1] on the 0-1000 grid")
        x0, y0, x1, y1 = (max(0, min(1000, int(round(v)))) for v in box)
        if x1 <= x0 or y1 <= y0:
            raise Invalid("the box is empty")
        value, box_source = self._words_in((x0, y0, x1, y1), page_n)
        n = max((int(f.id[1:]) for f in result.fields if f.id[1:].isdigit()), default=0) + 1
        f = Field(id=f"f{n}", name=name, printed_label=None, value=value, value_en=value,
                  value_type="text", page=page_n, source="user", confidence=1.0,
                  lang=page.lang, box=(x0, y0, x1, y1), box_source=box_source,
                  status=["edited_by_user"] + ([] if value else ["not_found"]),
                  translation={"name": "user", "value": "not_needed"})
        self._keep(value)
        result.fields.append(f)
        self._changed()
        return f

    def _words_in(self, box: tuple[int, int, int, int], page_n: int) -> tuple[str | None, str | None]:
        reading = self.session.reading
        if not isinstance(reading, Reading):
            return None, None
        page = next((p for p in reading.pages if p.n == page_n), None)
        if page is None:
            return None, None
        x0, y0, x1, y1 = box
        inside = [w for w in page.words if w.box is not None
                  and x0 <= (w.box[0] + w.box[2]) / 2 <= x1 and y0 <= (w.box[1] + w.box[3]) / 2 <= y1]
        if not inside:
            return None, None
        text = " ".join(" ".join(w.text for w in line.words) for line in lines_from_words(inside))
        return text, ("ocr" if page.source == "ocr" else "text_layer")

    def set_translation(self, term_id: str, body: dict) -> Field:
        """A "not translated" term typed by the user (UX-2.9). term_id is <field id>.<name|value>."""
        field_id, _, part = term_id.partition(".")
        if part not in ("name", "value"):
            raise NotFound("no such term")
        f = self._field(field_id)
        english = _text(body.get("english"), "english", MAX_VALUE)
        if not english:
            raise Invalid("the English text cannot be empty")
        if body.get("remember"):
            self._remember(f, part, english)
        if part == "name":
            f.name = english
        else:
            f.value_en = english
            self._keep(english)
        f.translation[part] = "user"
        _sync_not_translated(f)
        self._changed()
        return f

    def _remember(self, f: Field, part: str, english: str) -> None:
        """FR-9.8: only printed labels go to the translation memory, never values."""
        if part != "name" or not f.printed_label:
            raise Invalid("only printed labels can be remembered, never values")
        if not f.lang:
            raise Invalid("the label's language is not known, so it cannot be remembered")
        if self.store is None:
            raise Conflict(NO_STORE)
        entry = {"id": "t" + secrets.token_hex(4), "lang": f.lang, "term": f.printed_label,
                 "english": english, "scope": None}
        try:
            self.store.remember_translation(entry, self.session)
        except NabuError as e:  # a label equal to a value of this document is refused (AR-7)
            raise Conflict(e.message) from None

    def set_header(self, body: dict) -> json_out.Header:
        """Document type and region (FR-6.17). Empty means unknown (null in the output)."""
        self._ready()
        if "document_type" in body:
            self.header["document_type"] = _text(body["document_type"], "document type", MAX_NAME,
                                                 allow_none=True) or None
        if "region" in body:
            region = _text(body["region"], "region", 2, allow_none=True) or None
            if region is not None and not REGION.match(region):
                raise Invalid("region must be a two-letter country code in capitals, or empty")
            self.header["region"] = region
        self._changed()
        return self.header

    def reorder_pages(self, order: list) -> None:
        """New order of uploaded images before Verify (FR-6.2): order[i] is the old page number
        shown as page i + 1."""
        result = self._ready()
        old = [p.n for p in result.pages]
        if result.route != "raster" or len(self.uploads) < 2:
            raise Conflict("only several uploaded images can be reordered")
        if sorted(order) != sorted(old) or len(order) != len(old):
            raise Invalid("order must list every page number once")
        new_of = {o: i + 1 for i, o in enumerate(order)}
        for p in result.pages:
            p.n = new_of[p.n]
        result.pages.sort(key=lambda p: p.n)
        for f in result.fields:
            f.page = new_of[f.page]
        self.session.page_images = {new_of[n]: img for n, img in self.session.page_images.items()}
        if isinstance(self.session.reading, Reading):
            for rp in self.session.reading.pages:
                rp.n = new_of[rp.n]
            self.session.reading.pages.sort(key=lambda p: p.n)
        self._changed()

    # ---- verify, save, output (FR-6.11, FR-6.12, FR-6.16, FR-8) ---------------------------
    def verify(self) -> dict:
        result = self._ready()
        kept = [f for f in result.fields if not f.removed]
        seen: dict[str, int] = {}
        for f in kept:
            seen[f.name.casefold()] = seen.get(f.name.casefold(), 0) + 1
        first: dict[str, str] = {}  # one entry per name, in the spelling seen first
        for f in kept:
            if seen[f.name.casefold()] > 1:
                first.setdefault(f.name.casefold(), f.name)
        duplicates = list(first.values())
        # FR-6.12: no dialog when the linked template is used as it is
        dialog = self.template is None or write.differs(result, self.template)
        if not duplicates:
            self.verified_rev = self.rev
            if not dialog:
                self._confirmed(self.template)
        templates = self._templates()
        targets = self._update_targets(templates)
        doc_type, region = self.header["document_type"], self.header["region"]
        return {
            "fields": len(kept),
            "not_found": sum(1 for f in kept if (f.value_en if f.value_en is not None else f.value) is None),
            "needs_review": sum(1 for f in kept if "needs_review" in f.status),
            "not_translated": sum(1 for f in kept if "not_translated" in f.status),
            "duplicates": duplicates,  # FR-6.16: the only check that blocks Verify
            "can_confirm": not duplicates,
            "save_dialog_needed": dialog,
            "save_choices": {"document_only": True, "new": self.store is not None,
                             "update": bool(targets)},
            "suggested": "update" if self.template is not None and targets else "new",  # FR-7.2
            "update_targets": [describe(t) for t in targets],
            "document_types": sorted({template_header(t).get("document_type") for t in templates
                                      if template_header(t).get("document_type")}),
            "format_suggestion": write.next_format_name(templates, doc_type or "", region),
            "changes": write.changes(result, self.template),  # FR-7.1, names only
            "labels": write.labels_to_store(result),  # what would be written to disk
        }

    def _templates(self) -> list[dict]:
        return self.store.templates() if self.store is not None else []

    def _update_targets(self, templates: list[dict]) -> list[dict]:
        """The linked template, then others of the same document type and region (FR-7.4)."""
        if self.store is None:
            return []
        out = [self.template] if self.template is not None else []
        doc_type = self.header["document_type"]
        if doc_type:
            key = write.type_key(doc_type)
            mine = template_header(self.template).get("id") if self.template else None
            out += [t for t in templates if template_header(t).get("document_type_key") == key
                    and template_header(t).get("region") == self.header["region"]
                    and template_header(t).get("id") != mine]
        return out

    def _confirmed(self, t: dict | None) -> None:
        self.saved_rev = self.rev
        self.verified_at = datetime.now(UTC)
        h = template_header(t) if t else {}
        self.saved_template = (h["id"], h["version"]) if t else None

    def save(self, body: dict) -> None:
        """The save dialog's choice (FR-7). Cancel is simply not calling this (FR-7.6)."""
        result = self._ready()
        choice = body.get("choice")
        if choice not in ("document_only", "new", "update"):
            raise Invalid("choice must be document_only, new or update")
        if self.verified_rev != self.rev:
            raise Conflict("verify the document first")
        if choice == "document_only":  # FR-7.5: no template change
            self._confirmed(None)
            return
        if self.store is None:
            raise Conflict(NO_STORE)
        reading = self.session.reading
        if not isinstance(reading, Reading):
            raise Conflict("the document is not read yet")
        templates = self._templates()
        if choice == "new":
            doc_type = _text(body.get("document_type"), "document type", MAX_NAME)
            fmt = _text(body.get("format"), "format name", MAX_NAME)
            region = _text(body.get("region"), "region", 2, allow_none=True) or None
            if not doc_type or not fmt:
                raise Invalid("a new template needs a document type and a format name (FR-7.3)")
            if region is not None and not REGION.match(region):
                raise Invalid("region must be a two-letter country code in capitals, or empty")
            t = write.build_new(result, reading, self.cfg, doc_type, region, fmt, templates)
        else:
            tid = body.get("template_id")
            targets = {template_header(x).get("id"): x for x in self._update_targets(templates)}
            if tid is None and self.template is not None:
                tid = template_header(self.template).get("id")
            if tid not in targets:
                raise Invalid("update needs the linked template, or one of the same document "
                              "type and region")
            t = write.build_update(self.store.load_template(tid), result, reading, self.cfg)
        try:
            self.store.save_template(t, self.session)
        except NabuError as e:  # a value in a name or label (AR-7), or a format name in use
            raise Conflict(e.message) from None
        h = template_header(t)
        for f, tf in zip([f for f in result.fields if not f.removed], t["fields"], strict=True):
            f.template_key = tf["key"]  # this document now matches the saved template
        self.template = t
        self.header = {"document_type": h["document_type"], "region": h["region"],
                       "format": h["format"]["name"]}
        self._confirmed(t)

    def output(self) -> tuple[str, bytes]:
        result = self._ready()
        if self.saved_rev != self.rev or self.verified_at is None:
            raise Conflict("the output is available after Verify and the save choice")
        tid, ver = self.saved_template or (None, None)
        doc = json_out.build(result, self.header, self.verified_at, tid, ver)
        return json_out.file_name(result.source_file), json_out.dumps(doc)

    def page_image(self, n: int) -> bytes:
        img = self.session.page_images.get(n)
        if img is None:
            raise NotFound("no image for this page")
        return img

    def close(self) -> None:
        self.cancel.set()
        self.session.close()
        self.uploads = []
        self.result = None


def _text(v: object, what: str, limit: int, allow_none: bool = False) -> str:
    if v is None and allow_none:
        return ""
    if not isinstance(v, str):
        raise Invalid(f"{what} must be text")
    v = v.strip()
    if len(v) > limit:
        raise Invalid(f"{what} is longer than {limit} characters")
    return v


def _sync_not_translated(f: Field) -> None:
    untranslated = "untranslated" in f.translation.values()
    if untranslated:
        f.flag("not_translated")
    elif "not_translated" in f.status:
        f.status.remove("not_translated")


class DocumentService:
    """Holds the one open document and runs its reading job in a worker thread (AD-13).

    Model and OCR calls block, so they never run on the server's event loop.
    """

    def __init__(self, cfg: Config, readers: Callable[[], pipeline.Readers],
                 store: Store | None = None) -> None:
        self.cfg = cfg
        self._readers = readers
        self.store = store
        self._lock = threading.Lock()
        self.current: ReviewDocument | None = None

    def start(self, uploads: list[Upload]) -> ReviewDocument:
        with self._lock:
            if self.current is not None:
                raise Conflict("a document is already open; close it first")
            doc = ReviewDocument(uploads=uploads, cfg=self.cfg, store=self.store)
            self.current = doc
        self._job(doc, lambda readers, progress: pipeline.run(
            doc.uploads, self.cfg, doc.session, readers, progress, doc.cancel.is_set,
            self.store.templates() if self.store is not None else ()))
        return doc

    def relink(self, doc_id: str, body: dict) -> ReviewDocument:
        """FR-5.8: read again with the chosen template, or with none (template_id null)."""
        doc = self.get(doc_id)
        doc._ready()
        tid = body.get("template_id")
        if tid is not None and not isinstance(tid, str):
            raise Invalid("template_id must be a template id or null")
        if tid is not None and self.store is None:
            raise Conflict(NO_STORE)
        try:
            t = self.store.load_template(tid) if tid is not None and self.store else None
        except NabuError as e:
            raise NotFound(e.message) from None
        doc.state, doc.result, doc.template = "reading", None, None
        doc.rev += 1  # any earlier Verify no longer applies
        with doc._cond:
            doc._events = []
        self._job(doc, lambda readers, progress: pipeline.relink(
            doc.session, self.cfg, readers, t, progress, doc.cancel.is_set))
        return doc

    def get(self, doc_id: str) -> ReviewDocument:
        doc = self.current
        if doc is None or not secrets.compare_digest(doc.id, doc_id):
            raise NotFound("no such document")
        return doc

    def close(self, doc_id: str) -> None:
        doc = self.get(doc_id)
        with self._lock:
            self.current = None
        doc.close()

    def close_all(self) -> None:
        with self._lock:
            doc, self.current = self.current, None
        if doc is not None:
            doc.close()

    def _job(self, doc: ReviewDocument,
             work: Callable[[pipeline.Readers, pipeline.Progress], WorkingResult]) -> None:
        threading.Thread(target=self._run, args=(doc, work), name="nabu-read",
                         daemon=True).start()

    def _run(self, doc: ReviewDocument,
             work: Callable[[pipeline.Readers, pipeline.Progress], WorkingResult]) -> None:
        def progress(done: int, total: int, stage: str) -> None:
            doc.emit({"type": "progress", "stage": stage, "done": done, "total": total})

        try:
            result = work(self._readers(), progress)
        except pipeline.Cancelled:
            doc.state = "cancelled"
            doc.emit({"type": "cancelled"})
            return
        except NabuError as e:  # messages never carry values (errors.py)
            doc.state, doc.error = "error", e.message
            doc.emit({"type": "error", "message": e.message})
            return
        except Exception as e:  # noqa: BLE001 - reported by type only; the text may hold values
            log.error("reading failed: %s", type(e).__name__)
            doc.state, doc.error = "error", "reading failed because of an internal error"
            doc.emit({"type": "error", "message": doc.error})
            return
        if doc.cancel.is_set():  # closed while the last page was being read
            doc.state = "cancelled"
            doc.emit({"type": "cancelled"})
            return
        doc.result = result
        link = result.link or {}
        about = link.get("template") or {}
        guess = result.country_guess
        if link.get("outcome") == "linked":  # the template's header (FR-5.7)
            doc.template = self._template(link.get("template_id"))
            doc.header = {"document_type": about.get("document_type"),
                          "region": about.get("region"), "format": about.get("format")}
        elif link.get("outcome") == "similar":  # FR-5.6: its type and region pre-filled
            doc.header = {"document_type": about.get("document_type"),
                          "region": about.get("region"), "format": None}
        else:
            doc.header = {"document_type": result.type_guess,
                          "region": guess if guess and REGION.match(guess) else None,
                          "format": None}
        doc.state = "ready"
        doc.emit({"type": "done", "fields": len(result.fields), "link": link.get("outcome")})

    def _template(self, template_id: str | None) -> dict | None:
        if self.store is None or template_id is None:
            return None
        return self.store.load_template(template_id)

    # ---- template manager and translation memory (FR-7.9 to FR-7.12, FR-9.8) --------------
    def _values(self) -> set[str]:
        """Values of the open document: no template write may contain one (AR-7)."""
        doc = self.current
        return doc.session.values() if doc is not None else set()

    def _store(self) -> Store:
        if self.store is None:
            raise Conflict(NO_STORE)
        return self.store

    def templates(self) -> list[dict]:
        """Grouped by document type, then region, then format (FR-7.9, UX-4)."""
        groups: dict[str, dict[str, list[dict]]] = {}
        names: dict[str, str] = {}
        for t in self._store().templates():
            h = template_header(t)
            key = h.get("document_type_key", "")
            names.setdefault(key, h.get("document_type") or key)
            groups.setdefault(key, {}).setdefault(h.get("region") or "", []).append(
                {**describe(t), "fields": len(t.get("fields") or []),
                 "updated_at": h.get("updated_at"),
                 "field_names": [f.get("name") for f in t.get("fields") or []]})
        return [{"document_type": names[k], "regions": [
                    {"region": r or None,
                     "formats": sorted(fs, key=lambda x: (x["format"] or "").casefold())}
                    for r, fs in sorted(groups[k].items())]}
                for k in sorted(groups, key=lambda k: names[k].casefold())]

    def template(self, template_id: str) -> dict:
        try:
            return self._store().load_template(template_id)
        except Conflict:
            raise
        except NabuError as e:
            raise NotFound(e.message) from None

    def delete_template(self, template_id: str) -> None:
        self.template(template_id)
        self._store().delete_template(template_id)

    def history(self, template_id: str) -> list[dict]:
        self.template(template_id)
        return self._store().history_entries(template_id)

    def rollback(self, template_id: str, body: dict) -> dict:
        version = body.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise Invalid("version must be a number")
        self.template(template_id)
        try:
            self._store().rollback_template(template_id, version, self._values())
        except NabuError as e:
            raise Conflict(e.message) from None
        return self.template(template_id)

    def rename(self, template_id: str, body: dict) -> dict:
        """FR-7.11: a format renames this template; a document type renames it in all of its
        templates. Every name is checked before anything is written."""
        t = self.template(template_id)
        h = template_header(t)
        store = self._store()
        if "format" in body:
            name = _text(body.get("format"), "format name", MAX_NAME)
            if not name:
                raise Invalid("a format name cannot be empty")
            moves = [(h["id"], {"format": {"id": write.format_id(name), "name": name}},
                      {"kind": "renamed", "format": [h["format"]["name"], name]})]
        elif "document_type" in body:
            name = _text(body.get("document_type"), "document type", MAX_NAME)
            if not name:
                raise Invalid("a document type cannot be empty")
            key = h["document_type_key"]
            moves = [(template_header(x)["id"],
                      {"document_type": name, "document_type_key": write.type_key(name)},
                      {"kind": "renamed", "document_type": [h["document_type"], name]})
                     for x in store.templates()
                     if template_header(x).get("document_type_key") == key]
        else:
            raise Invalid("rename needs a document_type or a format")
        self._check_free(moves)
        try:
            for tid, changes, note in moves:
                store.move_template(tid, changes, note, self._values())
        except NabuError as e:
            raise Conflict(e.message) from None
        return self.template(template_id)

    def _check_free(self, moves: list[tuple[str, dict, str | dict]]) -> None:
        moving = {m[0] for m in moves}
        taken = set()
        for t in self._store().templates():
            h = template_header(t)
            if h.get("id") not in moving:
                taken.add((h.get("document_type_key"), h.get("region"), h["format"]["id"]))
        by_id = {template_header(t)["id"]: template_header(t) for t in self._store().templates()}
        for tid, changes, _ in moves:
            h = {**by_id[tid], **changes}
            if (h["document_type_key"], h.get("region"), h["format"]["id"]) in taken:
                raise Conflict("another template already uses this document type, region and "
                               "format; choose a different name")

    def translations(self) -> list[dict]:
        return list(self._store().translations()["entries"])

    def delete_translation(self, entry_id: str) -> None:
        if not self._store().delete_translation(entry_id):
            raise NotFound("no such remembered translation")
