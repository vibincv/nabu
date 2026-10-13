# M1 Reading engine (proposed 2026-10-13, awaiting approval)

Scope per FRD 15.2: FR-1.1, FR-2, FR-3, FR-4, FR-9 (not 9.8), FR-10, FR-11.1-3/5-7, FR-12, NFR-1, 5-9.
Out of scope: linking and templates (M3), review UI on live data and jobs (M2), installer (M4).
Rule kept: the pipeline is a library (AR-1); no CLI read command (FR-12.2); values only in memory.

## 0. Before starting
- [ ] User commits the current uncommitted work (model layer + review fixes) so M1 starts from a clean tree

## 1. OCR spike (M0 part that blocks M1; AD-1, Q4, Q5)
- [ ] `uv sync --extra read`; record install size of each read dependency (NFR-2)
- [ ] RapidOCR on the 7 synthetic pages: English and **Korean** accuracy, s/page
- [ ] Check whether RapidOCR downloads models at run time (the egress guard must refuse it; models must ship or come via `nabu langs pull`)
- [ ] Check Python 3.11-3.13 wheels for every read dependency (CI runs 3.13)
- [ ] Decide engine + Korean pack; write results to tasks/m0-ocr.md and propose FRD Section 12/13 text

## 2. Input (FR-2)
- [ ] `router.py`: route by extension AND magic bytes; mismatch names both; size limit; unsupported/encrypted/empty/corrupt each a named error; image-only combining (FR-2.8)
- [ ] `ocr/words.py`: Word(text, box 0-1000, conf), Page(n, width_px, height_px, words, text, lang, has_text_layer), Reading

## 3. Reading (FR-3)
- [ ] `extract/text.py`: txt/md/csv/tsv/json from bytes (encoding detection: utf-8, utf-16 BOM, fallback named error)
- [ ] `extract/office.py`: docx paragraphs + tables, xlsx sheets, pptx shapes; label-only, no positions (AD-15)
- [ ] `extract/digital_pdf.py`: pdfplumber words with boxes per page; pages without text layer go to raster (FR-2.3); form fields
- [ ] `extract/raster.py`: pypdfium2 render at 200 DPI (FR-2.4); images via Pillow (gif first frame, EXIF orientation); all in memory
- [ ] `ocr/engine.py`: one interface; rapidocr adapter; tesseract detected only (Q5 open); "no OCR" path per Section 14

## 4. Language (FR-9.1, 9.2, 9.9)
- [ ] `lang/detect.py`: script detection by Unicode ranges + small stopword lists, no new dependency; unsupported script named, never garbled

## 5. Discovery (FR-4)
- [ ] `discovery/rules.py`: "Label: value", "Label value" lines, PDF form fields, 2-column table rows; no model
- [ ] `discovery/prompt.py`: one model call per scanned page via ModelClient; type/country guess
- [ ] `fields/grounding.py`: match model value text to OCR word runs (AD-2); fallback model box marked `box_source: model`; else null
- [ ] Duplicates (FR-4.6): same label+value merged; same label, different value numbered in reading order
- [ ] Drop items whose label equals its value (seen in the qwen3.5 eval)
- [ ] Never invent a value: label without value -> empty + needs_review (FR-4.5); no model + scan -> OCR text + named message (FR-3.4)

## 6. English output (FR-9.3-9.7, 9.10)
- [ ] `lang/translate.py`: value-type rules (name/id/number kept; date -> ISO with region day/month; ambiguous -> needs_review; amount -> "1428.00 EUR")
- [ ] Labels/address/text: memory first (read path only), then model text call; unchanged or low confidence -> untranslated, never a guess

## 7. Orchestrator and result
- [ ] `pipeline.py`: read_document -> detect -> discover -> ground -> translate -> working result (DD-1); per-page progress callback (for M2 jobs); cancel between pages
- [ ] Working result validated against DD-1 shape; values never in logs or repr

## 8. Doctor and CLI (FR-1.1, FR-12)
- [ ] doctor: OCR engine present, OCR language packs, free RAM, GPU/VRAM where detectable (nvidia-smi optional)
- [ ] CLI: `langs list|pull`, `--quiet`, exit codes 0/1/2 documented; `translations list|delete`; `templates history|rollback` stubs stay M3

## 9. Fixtures and tests (NFR-5, 6, 9)
- [ ] Generated synthetic fixtures (script in repo): invoice, form, letter, ID card as PDF (text layer), DOCX/XLSX, scan PNG; English + Korean + accented Latin; encrypted/empty/corrupt/mismatched files
- [ ] Route table test for every extension; error-message tests; digital fixtures need no model; scans call the stub once per page
- [ ] Translation-rule tests (FR-9 acceptance a-f, except d which is M3)
- [ ] No-values scan of store and logs after the suite; egress test still passes
- [ ] Real reads: sample PDF, DOCX and scan through real OCR + qwen3.5:4b; report what ran for real vs stub

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
