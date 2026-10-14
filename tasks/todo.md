# M2 Review and output (approved 2026-10-14: D1 doc-only dialog, plan without first-run) - done

Scope per FRD 15.2: FR-6, FR-8, FR-11.3, UX-1, UX-2, API 10.2 (document routes).
Acceptance: screenshots of a fixture with highlights; rename, value edit, remove and restore; Verify
summary; output JSON validated against DD-3; no-values scan after a session. All without a model.
Out of scope: linking, save as new/update, template manager, translation memory "remember" (M3).
Rule kept: the server calls the M1 pipeline as a library; nothing re-implements reading.

## Decisions (confirmed)
- D1 FR-6.12 before templates exist: Verify -> save dialog with only "This document only" enabled;
  "Save as new" / "Update" shown disabled ("arrives with templates"). API contract stays M3-ready.
- D2 One open document at a time; a second upload while one is open -> 409 "close the current document".
- D3 Upload without multipart: Starlette 1.7 spools uploads > 1 MB to a temp file (checked:
  SpooledTemporaryFile max 1 MB), which breaks FR-11.3/API-2. The UI sends the raw bytes of the files
  back to back plus an `X-Nabu-Files` header (names and sizes); the server reads the stream into
  memory with the upload limit enforced while reading.
- D4 Additions to API 10.2: `PATCH /api/documents/{id}/header` (FR-6.17 document type, region) and
  `PUT /api/documents/{id}/pages/order` (FR-6.2 image order). Reported, FRD not edited.

## 1. Sessions and jobs (server/documents.py, session.py)
- [x] ReviewDocument + DocumentService: uploads in memory, worker thread runs pipeline.run, progress per page, cancel flag
- [x] Events to SSE through a thread-safe event list (fetch-read in the UI: EventSource cannot send the token header)
- [x] Session keeps the Reading for drawn-box fields; released on DELETE, quit and server stop
- [x] Pipeline errors reach the UI as named messages; unexpected errors by type only

## 2. Document API (server/app.py)
- [x] POST /api/documents (202), GET events (SSE), GET result, GET pages/{n}.png, DELETE
- [x] PATCH fields/{id}: name, value, value_type, removed/restored, accept; values the user types are registered (AR-7)
- [x] POST fields: drawn box -> words inside it (none -> empty value, not_found)
- [x] PATCH translations/{field}.{name|value} (remember -> 409 until M3)
- [x] PATCH header, PUT pages/order (several images only)
- [x] POST verify (counts, duplicates block, save_dialog_needed), POST save (document_only), GET output (409 until verify+save at the current revision)
- [x] GET /api/documents: the open document, so a reloaded window resumes it (found in the browser run)
- [x] /api/doctor returns the real report (in a thread)

## 3. Output (output/json_out.py)
- [x] DD-3 from the working result: reading order, English value, original when different, not_found, untranslated_terms
- [x] Deterministic bytes; schema-validated in tests; download name <source>.nabu.json

## 4. Review UI (ui/src)
- [x] Upload: drag-and-drop and picker, several images, order before reading; reorder after reading
- [x] Progress (reading, finding fields, translating) with Cancel; designed states (no fields, no model, errors)
- [x] Page images with highlights; text view for office/text files
- [x] Edits through the API; draw a box to add a field; not-translated box; accept suggestion
- [x] Header document type + region (country list from Intl.DisplayNames, offline); model guess as one-click suggestion
- [x] Verify summary from the server; save dialog (D1); download; Close document clears the window's DOM
- [x] Fixture mode kept (fixtureBackend) for dev and the M5 demo

## 5. Tests and evidence
- [x] tests/test_documents_api.py (28) + tests/test_output.py (5): journey, state rules, token on every route, no disk writes, no values in the product log
- [x] UI: tsc + build; bundle tests pass (no remote URLs, no inline scripts)
- [x] Real `nabu serve` run in Chrome (qwen3.5:9b): see Review

## Review (2026-10-14)
- Tests: 311 passed, 4 skipped (Windows, Python 3.11, UI built); ruff and tsc clean.
- Real run in Chrome, synthetic docs: DE PDF -> 5 fields highlighted, translated, 01/02/2026 -> 2026-02-01;
  rename, value edit, remove, restore, drawn box ("Rechnung" from the text layer), header, Verify summary,
  save dialog, output fetched (200, no-store) with the header and edits; edit after save -> output 409;
  2 images -> OCR + model, 3 fields, header pre-filled from the model guess, page reorder; Close -> server
  has no document, window DOM has no values; Nabu store: only 2 startup log lines, no values.
- Found and fixed in the browser run: page scrolled as a whole (header lost), narrow region picker,
  reloaded window locked out by the open document, banner kept "Verified" after an edit, closed
  document's text left in the hidden DOM, no progress during translation.
- Gaps (not done): drawing a box needs a mouse (FR-6.13 keyboard: no keyboard way to add a field);
  field-name suggestions from other templates (FR-6.5) and document-type names wait for templates (M3);
  the Download button itself was not clicked (it would save a file to Downloads); the output was fetched
  through the same API call instead.
- API additions to 10.2 (reported, FRD not edited): GET /api/documents, PATCH header, PUT pages/order,
  X-Nabu-Files raw upload instead of multipart.

---

# Owner decisions 2026-10-14

- [x] Day-month dates with no region: resolved by language when every region of that language is
  day first (de, fr, es, it, pt, nl). English, Korean and unknown stay needs_review; a region
  always wins (`values.DAY_FIRST_LANGS`, `parse_date(text, region, lang)`)
- [x] Language detection scores German/Dutch compound labels (half a point when a long word starts
  or ends with a long vocabulary word). Without it the date rule never fired on a real invoice:
  every label was a compound, the page language was None
- [x] qwen3.5:9b is the model: config switched (`nabu models use qwen3.5:9b`); tier table kept

## Review
- Tests: 275 passed, 7 skipped (Windows, Python 3.11); ruff clean. Korean pack test skipped (pack not
  installed in this run).
- Real reads (RTX 4060 8 GB, synthetic docs; `realread.py` in the session scratchpad):
  | model | DE digital PDF, no region | DE invoice scan |
  |---|---|---|
  | qwen3.5:4b | 3/4 (date needs review, before the detect fix), 11.0 s | 6/6, 20.3 s |
  | qwen3.5:9b | 4/4 after the fix, 5.4 s | 6/6, 31.8-33.9 s |
- 9b is about 60% slower per scanned page than 4b with equal accuracy on these two documents.
  Clean synthetic pages cannot show 9b's accuracy gain; that needs real, messy scans.

---

# M1 Reading engine (approved 2026-10-13 "continue")

Scope per FRD 15.2: FR-1.1, FR-2, FR-3, FR-4, FR-9 (not 9.8), FR-10, FR-11.1-3/5-7, FR-12, NFR-1, 5-9.
Out of scope: linking and templates (M3), review UI on live data and jobs (M2), installer (M4).
Rule kept: the pipeline is a library (AR-1); no CLI read command (FR-12.2); values only in memory.
Legend: [x] done and tested, [~] partly done (gap stated).

## 0. Before starting
- [x] User commits the current uncommitted work (4f43843)

## 1. OCR spike (M0 part that blocks M1; AD-1, Q4, Q5) - results in tasks/m0-ocr.md
- [x] Install size (NFR-2): read extra 292 MB on Windows (budget raised to 300 MB)
- [x] Bundled models read no Korean; PP-OCRv5 Korean rec + script rule fixes it
- [x] Run-time downloads: none when model paths are given (guard on); adapter always passes paths
- [x] Python 3.13: rapidocr-onnxruntime is capped < 3.13 -> switched to `rapidocr` 3.10 + onnxruntime
- [x] Owner decisions: NFR-2 300 MB, NFR-3 < 10 s, `langs pull` is the AR-3 exception, Q5 closed

## 2. Input (FR-2)
- [x] `router.py`: extension AND content; mismatch names both; size limit; unsupported/encrypted/empty/corrupt named; image-only combining
- [x] `ocr/words.py`: Word, Line (with table cells), Page, Reading, FormField; grid helpers; values out of repr

## 3. Reading (FR-3)
- [x] `extract/text.py`: txt/md/csv/tsv/json; UTF-8/UTF-16 else named error; html and rtf best effort
- [x] `extract/office.py`: docx paragraphs + tables in order, xlsx sheets, pptx shapes/tables; no positions; zip-bomb and cell limits
- [x] `extract/digital_pdf.py`: words with boxes per page; pages without text layer go to OCR (FR-2.3); AcroForm fields
- [x] `extract/raster.py`: pypdfium2 render at cfg.dpi (capped 4000 px); images via Pillow (EXIF, gif first frame, tiff frames)
- [x] `ocr/engine.py`: rapidocr adapter; detect once, Korean re-read by script rule, second detection pass for dropped lines; no angle classifier (flipped lines in M0)

## 4. Language (FR-9.1, 9.2, 9.9)
- [x] `lang/detect.py`: script + short-word lists, no dependency; per field follows page for short Latin labels
- [~] FR-9.9: Korean/Chinese text on a scan without a pack is named and not shown. Other scripts on scans
  (Thai, Arabic, ...) are not named: the bundled OCR returns low-score noise that is dropped. Digital files
  read every script.

## 5. Discovery (FR-4)
- [x] `discovery/rules.py`: "Label: value" (also glued and fullwidth colon), gap-split layout lines, several pairs per line, 2-column and header tables, form fields
- [x] `discovery/prompt.py`: one model call per scanned page; type/country guess; colons stripped from labels
- [x] `fields/grounding.py`: OCR word runs (exact, then one-character-off for long values); model box as fallback; else none
- [x] Duplicates merged before translation, repeats numbered after (FR-4.6); label == value dropped
- [x] Never invent: model value not found as printed -> needs_review; empty label kept empty; no model + scan -> text + message

## 6. English output (FR-9.3-9.7, 9.10)
- [x] `fields/values.py` + `lang/translate.py`: name/id/number kept; dates ISO by region; ambiguous -> needs_review; amounts "1428.00 EUR"
- [x] Memory first (read path), then one model call per page and language; unchanged -> untranslated; low confidence -> needs_review
- [x] New answer status `not_needed` (proper names, codes): value kept exactly as printed; for labels it counts as untranslated

## 7. Orchestrator and result
- [x] `pipeline.py`: read_document -> discover -> merge -> translate -> number -> working result; progress per page; cancel between pages; values registered (AR-7)
- [x] DD-1 shape (`fields/types.py`); additions reported: per-field `translation`, per-page `text`/`messages`, `document.route`/`model_used`, top-level `messages`

## 8. Doctor and CLI (FR-1.1, FR-12)
- [x] doctor: OCR engine, languages, packs; free RAM; NVIDIA GPU/VRAM (1.2-1.3 s warm)
- [~] FR-1.1 "which models accept images" not reported yet
- [x] CLI: `langs list|pull`, `translations list|delete`; guard skipped only for `langs pull`
- [~] FR-12.4 `serve --verbose` (route, link scores) waits for M2/M3: serve does not read documents yet

## 9. Fixtures and tests (NFR-5, 6, 9)
- [x] `tests/docgen.py` builds synthetic PDFs (text, form, scan, encrypted), images, DOCX/XLSX/PPTX in memory
- [x] Route table for every extension; named-error tests; digital needs no model; scans call the stub once per page
- [x] Translation-rule tests (FR-9 a, b, c, read path of d); e (refuse remembering a value) already in test_store
- [~] No-values: logs (caplog) and store refusal tested; a full store-folder scan after the suite is not added
- [x] Real reads (synthetic docs, real OCR + Korean pack + qwen3.5:4b): see Review
- [x] CI installs `--extra read`

## Review (2026-10-13)
- Tests: 265 passed, 6 skipped (Windows, Python 3.11 and 3.13, with read extra, Korean pack test included);
  254 passed, 13 skipped without the extra; ruff clean.
- Real reads on this machine (RTX 4060 8 GB, Ollama, qwen3.5:4b, synthetic docs):
  digital DE PDF 4/4 fields, 7.8 s (translation call only); EN DOCX 4/4, 0.0 s, no model;
  DE invoice scan 6/6 values exact, OCR boxes, 24.6 s; KO form scan 5/5, Korean pack, 38.1 s.
- OCR alone: 2-3 s/page on the 7 eval pages (meets NFR-3 < 10 s; even the old 5 s).
- Open for the owner: digital files have no region until the user sets one, so day-month dates stay
  "needs review" (FRD rule). Proposal: resolve by language when every region of that language is
  day-first (de, fr, es, it, pt, nl). Not implemented.
- Tier table: doctor now sees the GPU and recommends qwen3.5:9b (64 GB RAM rule), while the
  measured eval favoured 4b. Proposal: tier rule ">= 32 GB RAM -> 9b" changes to "only with >= 8 GB VRAM"
  after a 9b run on real documents. Not changed.
- Not wired: the review server does not call the pipeline yet (M2: upload endpoint, jobs, page images).

---

# Pluggable model layer + remaining review findings

Approved 2026-10-13: default model qwen3.5 (Apache-2.0), plug-and-play models, fix the review findings.

## A. Pluggable model layer (FR-10, AD-3, 10.3, 10.4)
- [x] `model/types.py`: PageImage, Box (0-1000 grid), PageDiscovery, FieldReading, TranslateItem, Translation; wire schemas for model JSON (pydantic)
- [x] `model/profiles.py`: per-family profile as data (coords convention, thinking off, structured output, image edge); built-ins for qwen3.5, qwen3-vl, qwen2.5vl, gemma4, granite-vision, generic; user profiles from config
- [x] `model/http.py`: loopback-only HTTP base (no proxy, no redirects, relative paths only, guard installed)
- [x] `model/ollama.py`: Ollama runtime adapter (`/api/tags`, `/api/chat`, `/api/pull`), distinct errors (FR-10.4)
- [x] `model/openai_compat.py`: OpenAI-compatible adapter (llama.cpp, LM Studio, vLLM)
- [x] `model/client.py`: ModelClient with the FRD 10.4 methods (discover_page, reread_crop, translate), prompts from 10.3, schema validation, one repair (FR-3.5), coordinate conversion (FR-10.6), image limit (FR-10.3)
- [x] `model/tiers.py`: tier table (MH-1) with qwen3.5 defaults; doctor shows recommended model
- [x] Config: `model_runtime`, `model_profile`, `model_profiles`, `model_timeout_s`
- [x] CLI: `models list | use | pull` (FR-12.1, FR-10.5); config written through the store (AR-2)
- [x] `python -m nabu.model.evaluate`: eval harness (accuracy, JSON validity, s/page, coordinate-convention fit); metrics only, never values
- [x] Stub runtime extended (chat with images/format/think, pull, OpenAI-compat routes); tests

## B. Review findings
- [x] F2: review window claimed by the first browser (HttpOnly SameSite=Strict cookie); API needs cookie + token
- [x] F3: residual risks (browser session restore, swap/hibernation, runtime logs) in README; FRD wording proposed to the user
- [x] F5: guard installed by every network entry point (model HTTP base, server app)
- [x] F6: FRD inconsistencies (AR-2 output JSON, AR-7 temp folder): proposed text for the user, FRD not edited
- [x] F7: refuse non-HTTP scopes; token compare safe for non-ASCII; relative-path check in model HTTP
- [x] F8: refuse template id/path collision and non-increasing versions; damaged template files give a named error; CLI catches unexpected errors without traceback; log file created 0600

## Verify
- [x] Full test suite and ruff (red-on-old-code checked for the netguard/no-values tests only; the model layer is new code)
- [x] `uv lock` updated (pillow added explicitly), `uv sync --locked` works

## Review
- 143 passed, 6 skipped (Windows, Python 3.11, `uv sync --locked`); ruff clean; `uv lock --check` clean.
- Real model check: `gemma4:latest` on a synthetic invoice through Ollama: valid JSON first try,
  4/4 labels and values, ~40 s/page. Its boxes fit no convention, so built-in profiles keep
  `coords: "none"` (boxes from OCR, AD-2) until the M0 eval measures each model.
- Real server check (uvicorn): first browser gets the page and API; a second client gets 409 and
  401 even with the token.
- Changed from the FRD: tier ">= 32 GB RAM" now gets qwen3.5:9b; 27b needs >= 16 GB VRAM.
- Not done here: qwen3.5 not pulled or measured (needs a ~4 GB download, user's call);
  FRD text changes proposed, not written; Linux/macOS/3.13 run only in CI.
