"""Orchestrator: the only place the flow lives (AR-1, FRD Section 7). M1.

The model is reached only through nabu.model.client.ModelClient (build_client returns None in
no-model mode, FR-3.4). The egress guard is installed by every network entry point (the model
HTTP layer and the review server), so library callers are covered too.

Flow (7.3, without linking, which is M3): route -> read (text layer, office, text, or render +
OCR) -> language per page -> discovery (rules for digital pages, one model call per scanned page)
-> ground -> merge duplicates -> English by value-type rules, memory, then model -> number
repeats -> working result. Everything stays in memory (AD-8). Calls block: run this in a worker
thread, never on the server's event loop (AD-13). `progress` is called after every page;
`cancelled` is checked between pages (Section 14: reading stops after the current page).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from nabu import discovery
from nabu.config import Config
from nabu.discovery import prompt as model_discovery
from nabu.discovery import rules
from nabu.errors import ModelUnavailable, NabuError, TooLarge
from nabu.extract import digital_pdf, office, raster
from nabu.extract import text as text_files
from nabu.fields import values
from nabu.fields.types import Field, PageInfo, WorkingResult
from nabu.lang import detect, translate
from nabu.lang.memory import TranslationMemory
from nabu.model.client import ModelClient
from nabu.ocr.engine import RapidOcrEngine
from nabu.ocr.words import Page, Reading
from nabu.router import Upload, check_combination, classify
from nabu.session import Session

log = logging.getLogger(__name__)

NEEDS_MODEL = "Finding fields on scans needs a local AI model"
NO_OCR = "this page is a scan and no OCR engine is installed; run: uv sync --extra read"

Progress = Callable[[int, int, str], None]  # (pages done, pages total, stage)


class Cancelled(NabuError):
    def __init__(self) -> None:
        super().__init__("reading was cancelled")


@dataclass
class Readers:
    """What is installed. Each part may be missing: Nabu then does less, never guesses."""

    ocr: RapidOcrEngine | None
    model: ModelClient | None
    memory: TranslationMemory


def _noop(done: int, total: int, stage: str) -> None:
    pass


def _never() -> bool:
    return False


def read_document(uploads: list[Upload], cfg: Config, ocr: RapidOcrEngine | None,
                  progress: Progress = _noop, cancelled: Callable[[], bool] = _never) -> Reading:
    """Route and read one document: text and words with boxes, per page, with its language."""
    if not uploads:
        raise NabuError("no file was uploaded")
    total_bytes = sum(len(u.data) for u in uploads)
    if total_bytes > cfg.upload_limit_mb * 1024 * 1024:
        raise TooLarge(f"the upload is larger than the limit of {cfg.upload_limit_mb} MB")
    kinds = [classify(u, cfg.upload_limit_mb) for u in uploads]
    check_combination(uploads, kinds)
    first, kind = uploads[0], kinds[0]
    name = first.name if len(uploads) == 1 else f"{first.name} (+{len(uploads) - 1} images)"

    if kind == "image":
        images = []
        for u in uploads:  # FR-2.8: pages in upload order
            images += raster.image_pages(u.data, u.name, first_page=len(images) + 1)
        pages = [Page(n=img.page, source="ocr", width_px=img.width_px, height_px=img.height_px,
                      image=img) for img in images]
        reading = Reading(file_name=name, route="raster", pages=pages)
    elif kind == "pdf":
        pdf = raster.open_pdf(first.data, first.name)
        try:
            text = digital_pdf.read(first.data, first.name)
            pages = []
            for i, tp in enumerate(text.pages):
                if cancelled():
                    raise Cancelled()
                img = raster.render_pdf_page(pdf, i, cfg.dpi, first.name)  # shown in the window
                if tp is None:
                    pages.append(Page(n=i + 1, source="ocr", width_px=img.width_px,
                                      height_px=img.height_px, image=img))
                else:
                    tp.image, tp.width_px, tp.height_px = img, img.width_px, img.height_px
                    pages.append(tp)
        finally:
            pdf.close()
        route = "digital_pdf" if any(p.source == "text_layer" for p in pages) else "raster"
        reading = Reading(file_name=first.name, route=route, pages=pages,
                          form_fields=text.form_fields)
    elif kind in ("docx", "xlsx", "pptx"):
        reading = office.read(first.data, first.name, kind)
    else:
        reading = text_files.read(first.data, first.name, kind)

    total = len(reading.pages)
    for done, page in enumerate(reading.pages, 1):
        if cancelled():
            raise Cancelled()
        if page.source == "ocr":
            if ocr is None:
                page.notes.append(NO_OCR)
            else:
                assert page.image is not None
                res = ocr.read(page.image)
                page.lines, page.notes = res.lines, page.notes + res.notes
        page.lang = detect.page_language(page.text)
        progress(done, total, "reading")
    return reading


def _from_pair(p: rules.Pair, page: Page) -> Field:
    f = Field(id="", name=p.label, printed_label=p.label, value=p.value,
              value_type=values.infer(p.value), page=p.page, source="discovery_rules",
              confidence=p.confidence, box=p.box,
              box_source="text_layer" if p.from_layout else None, status=["suggested"])
    if p.value is None:
        f.flag("needs_review")  # FR-4.5: a label without a readable value
    return f


def _from_model(p: model_discovery.ModelPair, cfg: Config) -> Field:
    f = Field(id="", name=p.label, printed_label=p.label, value=p.value,
              value_type=p.value_type, page=p.page, source="model", confidence=p.confidence,
              box=p.box, box_source=p.box_source, status=["suggested"])  # type: ignore[arg-type]
    if p.value is None or not p.exact or p.confidence < cfg.review_confidence:
        f.flag("needs_review")  # empty, not found as printed on the page, or unsure
    return f


def discover(reading: Reading, cfg: Config, readers: Readers, progress: Progress = _noop,
             cancelled: Callable[[], bool] = _never) -> WorkingResult:
    by_n = {p.n: p for p in reading.pages}
    fields: list[Field] = []
    messages: list[str] = []
    page_msgs: dict[int, list[str]] = {p.n: list(p.notes) for p in reading.pages}
    type_guess = country_guess = None
    model = readers.model
    model_used = False

    digital = [p for p in reading.pages if p.source != "ocr"]
    for pair in rules.discover(digital, reading.form_fields):
        fields.append(_from_pair(pair, by_n[pair.page]))

    scans = [p for p in reading.pages if p.source == "ocr"]
    for done, page in enumerate(scans, 1):
        if cancelled():
            raise Cancelled()
        if model is None:
            page_msgs[page.n].append(NEEDS_MODEL)  # FR-3.4: text shown, no fields, no guess
            continue
        try:
            res = model_discovery.discover_page(model, page)
        except ModelUnavailable as e:
            messages.append(e.message)
            for rest in scans[done - 1:]:
                page_msgs[rest.n].append(NEEDS_MODEL)
            model = None  # do not try the remaining pages or translation
            break
        model_used = True
        if res.message:
            page_msgs[page.n].append(res.message)
        type_guess = type_guess or res.type_guess
        country_guess = country_guess or res.country_guess
        fields += [_from_model(p, cfg) for p in res.pairs]
        progress(done, len(scans), "finding fields")

    for f in fields:
        f.lang = detect.field_language(f.printed_label or "", f.value, by_n[f.page].lang)
    fields = discovery.merge(fields)
    progress(0, 1, "translating")
    outcome = translate.translate_fields(fields, readers.memory, model, country_guess, type_guess)
    progress(1, 1, "translating")
    messages += outcome.messages
    model_used = model_used or outcome.model_calls > 0
    fields = discovery.number(fields)
    for i, f in enumerate(fields, 1):
        f.id = f"f{i}"

    pages = [PageInfo(n=p.n, width_px=p.width_px, height_px=p.height_px, lang=p.lang,
                      text=p.text, messages=page_msgs[p.n]) for p in reading.pages]
    return WorkingResult(source_file=reading.file_name, pages=pages, fields=fields,
                         route=reading.route, model_used=model_used, type_guess=type_guess,
                         country_guess=country_guess, messages=_unique(messages))


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def run(uploads: list[Upload], cfg: Config, session: Session, readers: Readers,
        progress: Progress = _noop, cancelled: Callable[[], bool] = _never) -> WorkingResult:
    """Read one document into a working result held by the session (FRD 10.4 read_document +
    discover + translate_fields). Every value found is registered with the session, so the store
    refuses to write it anywhere (AR-7)."""
    reading = read_document(uploads, cfg, readers.ocr, progress, cancelled)
    result = discover(reading, cfg, readers, progress, cancelled)
    for f in result.fields:
        session.register_value(f.value)
        if f.value_en != f.value:
            session.register_value(f.value_en)
    session.page_images = {p.n: p.image.data for p in reading.pages if p.image is not None}
    session.reading = reading  # words with boxes, for fields the user draws (FR-6.9)
    session.working_result = result.to_dict()
    return result
