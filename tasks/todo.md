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
