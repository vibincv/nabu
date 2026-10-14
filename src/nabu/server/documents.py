"""The document being reviewed: reading job, edits, verify, save and output (FR-6, FR-8). M2.

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

log = logging.getLogger(__name__)

REGION = re.compile(r"^[A-Z]{2}$")
MAX_NAME = 200
MAX_VALUE = 10_000
TERMINAL = ("done", "error", "cancelled")
TEMPLATES_LATER = "saving templates arrives with templates (M3); choose This document only"
REMEMBER_LATER = "remembering translations arrives with templates (M3)"


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
        if body.get("remember"):
            raise Conflict(REMEMBER_LATER)
        english = _text(body.get("english"), "english", MAX_VALUE)
        if not english:
            raise Invalid("the English text cannot be empty")
        if part == "name":
            f.name = english
        else:
            f.value_en = english
            self._keep(english)
        f.translation[part] = "user"
        _sync_not_translated(f)
        self._changed()
        return f

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
        if not duplicates:
            self.verified_rev = self.rev
        return {
            "fields": len(kept),
            "not_found": sum(1 for f in kept if (f.value_en if f.value_en is not None else f.value) is None),
            "needs_review": sum(1 for f in kept if "needs_review" in f.status),
            "not_translated": sum(1 for f in kept if "not_translated" in f.status),
            "duplicates": duplicates,  # FR-6.16: the only check that blocks Verify
            "can_confirm": not duplicates,
            # FR-6.12: no template is linked before M3, so the dialog always applies
            "save_dialog_needed": True,
            "save_choices": {"document_only": True, "new": False, "update": False},
        }

    def save(self, body: dict) -> None:
        self._ready()
        choice = body.get("choice")
        if choice in ("new", "update"):
            raise Conflict(TEMPLATES_LATER)
        if choice != "document_only":
            raise Invalid("choice must be document_only, new or update")
        if self.verified_rev != self.rev:
            raise Conflict("verify the document first")
        self.saved_rev = self.rev
        self.verified_at = datetime.now(UTC)

    def output(self) -> tuple[str, bytes]:
        result = self._ready()
        if self.saved_rev != self.rev or self.verified_at is None:
            raise Conflict("the output is available after Verify and the save choice")
        doc = json_out.build(result, self.header, self.verified_at)
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

    def __init__(self, cfg: Config, readers: Callable[[], pipeline.Readers]) -> None:
        self.cfg = cfg
        self._readers = readers
        self._lock = threading.Lock()
        self.current: ReviewDocument | None = None

    def start(self, uploads: list[Upload]) -> ReviewDocument:
        with self._lock:
            if self.current is not None:
                raise Conflict("a document is already open; close it first")
            doc = ReviewDocument(uploads=uploads)
            self.current = doc
        threading.Thread(target=self._run, args=(doc,), name="nabu-read", daemon=True).start()
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

    def _run(self, doc: ReviewDocument) -> None:
        def progress(done: int, total: int, stage: str) -> None:
            doc.emit({"type": "progress", "stage": stage, "done": done, "total": total})

        try:
            result = pipeline.run(doc.uploads, self.cfg, doc.session, self._readers(), progress,
                                  doc.cancel.is_set)
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
        guess = result.country_guess
        doc.header = {"document_type": result.type_guess,
                      "region": guess if guess and REGION.match(guess) else None, "format": None}
        doc.state = "ready"
        doc.emit({"type": "done", "fields": len(result.fields),
                  "link": "none"})  # linking arrives in M3
