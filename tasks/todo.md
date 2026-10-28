# M3.3 Owner retest fixes (2026-10-28) - done, awaiting owner retest

- [x] Save refused on an Aadhaar card ("in: removed, removed_labels"): a removed field labelled by
      a printed value. write.py leaves such names and labels out (they never recur). Test added.
- [x] DOB read the date, the name and card text: each update stored the box of what was read, so
      the PAN template's DOB box grew 34 -> 62 -> 107 grid units over v1-v3. Fixed in read.py
      (lines centred in the box; else the one nearest line; words found as a label or landmark
      never join a value) and documents.py (an edited value printed on the page moves the box).
      Tests: printed line under a value, landmark inside a grown box, edit + update keeps one line.
- [x] Owner's PAN template rolled back to v1 (saved as v4).
- Result: 386 passed, 4 skipped; ruff clean.
- Not done: an edited value not printed as typed (a translation, a fix of an OCR error) keeps the
  read box; drawing the box again is the way to correct it.

# M3.2 Linking on real photos, template folder, export folder (approved 2026-10-21) - done, awaiting owner retest

Owner retest: a second PAN card did not link; the template had to be picked by hand.

## Root cause (investigated)
1. The owner's `pancard.json` (Temp\nabu-test, saved 2026-10-14 15:10) predates the landmark fix
   (align.py 15:30): no printed labels, no boxes, no landmarks -> link.score total 0 -> 0.0.
2. Even re-saved, link.py:96-99 rejects a page whose aspect differs > 10% from the template's.
   That is the photo's shape, not the card's, so any differently framed photo scores 0.
3. Removing the gate alone is not enough: align fits in the 0-1000 grid per axis, so a photo of
   another aspect needs a different scale on x and y; the uniform fit fails. Tests never caught
   it because every test card is an A4 PDF page.
4. Templates went to Temp because the server ran with NABU_HOME=Temp\nabu-test.

## Decisions (owner, 2026-10-21)
- Export: one JSON per document into a configured folder, written only on Save after Verify.
- Templates: configurable folder (config key), default stays the per-user store.
- Shape gate: skipped when the template has labels or landmarks; kept for templates with none.

## 1. Linking across photo shapes (templates/align.py, link.py)
- [x] Fit in aspect-true units: grid x * w/max(w,h), y * h/max(w,h); template side uses the
      stored page aspect, document side the page's own. Fit.box maps back to the document grid.
- [x] link.score: shape check only when the template has no anchors on that page.
- [x] Scale range 0.75-1.33 -> 0.5-2.0 (provisional). Needed: a card at 60% size scored
      "similar" with the old floor. False-link guard unchanged (one fit, link_threshold).
- [x] Tests: docgen.pdf gets a page size; PAN card on a landscape page, a tall phone-photo page
      and a landscape page at 60% links and reads; an unrelated document on a landscape page
      does not link; unit fit across page shapes.
- [x] Found while fixing: read.py scaled label->value offsets by one factor (Fit.offset now
      per axis); an update kept landmark boxes from the old photo while taking the new photo's
      shape (now the box where each is found on this document). Test: update from a landscape
      photo, then a third card links.
- [x] test_link.test_page_rules: the "landscape template never links a portrait page" check
      replaced by the rule that remains (shape counts only on a page without anchors).
- Result: 366 passed, 4 skipped; ruff clean.

## 2. Template folder (config, store/paths.py, cli.py)
- [x] Config `templates_dir: str | None` (absolute path; None -> <data_dir>/templates).
- [x] StorePaths takes an optional templates root; cli.py applies it after load_config, so
      serve (also from the shortcut, which goes through the CLI), templates CLI and doctor all
      use the same folder. `doctor` prints the folder.
- [x] The data folder itself, or a folder holding it, is refused (logs and OCR packs would sit
      among the templates).
- [x] `forget --templates` removes only Nabu's template files (<type>/<region>/<format>.json and
      versions/), then empty folders; it no longer rmtree's the folder. Needed once the folder
      can be one the owner chose that holds other files.
- [x] Existing templates are not moved automatically; README section "Templates folder".
- [x] tests/test_templates_dir.py (7): relative refused, default, save and list in the folder,
      data folder / parent refused, forget keeps other files, CLI list and doctor use it.
      Real CLI run on a scratch store: doctor shows the folder, both refusals named.
- Result: 373 passed, 4 skipped; ruff clean.
- Not guarded: two machines saving the same template at the same moment in a shared folder.

## 3. Export folder (AR-7 change: one value-bearing write path)
- [x] Config `export_dir: str | None`, default None (off: no disk writes, as today).
      Refused if it overlaps the data or templates folder either way (no-values scans stay valid).
- [x] Store.export_output(name, bytes): the only method allowed to write values. Atomic
      (dot-prefixed temp file in the same folder, then rename) so the service never reads a
      partial file. Name: <source>.<UTC yyyymmddThhmmssZ>.<doc id 8>.nabu.json.
- [x] ReviewDocument.save: after the save, if export_dir set, write the DD-3 output.
      Export failure -> `export_error` in the 200 reply; the save stays, download still works.
- [x] Save reply carries `exported` (full path) and `export_error`; the "Output ready" dialog
      says where it went, or why not ("Nabu keeps no copy" only when export is off).
- [x] Product log records only the time + id tag, not the file name (it carries the upload's
      name, which may be a person's name).
- [x] tests/test_export.py (9): document-only and new-template saves export, bytes equal the
      download, store and nabu log value-free, nothing written when off, failure keeps the
      save, relative and overlapping folders refused. tsc clean, UI rebuilt.
- [x] Real `nabu serve` run (scratch store, export + templates folders): upload, verify, save
      new -> one file in the outbox with the values, template in the templates folder, no value
      in store or templates, log line shows only the tag.
- [ ] FRD notes: AR-7 exception (export folder), new config keys. (owner)
- Result: 382 passed, 4 skipped; ruff clean.
- Checked, not a leak: pdfminer logs page text at DEBUG, but hardening caps it at WARNING and
  the product log handlers sit on the "nabu" logger only.
- Not done: the review window was not clicked through in a browser for the new dialog text.

## Not in scope
- Pushing to the service (it reads the folder), deleting exported files, encrypting them.
- Moving the owner's current template: delete `Temp\nabu-test\templates\id\IN\pancard.json`
  and save the PAN card again after this lands.

# M3 fix: templates for documents without printed labels (approved 2026-10-14, "Fix templates first") - done, awaiting owner retest

Found by the owner on a PAN card: the template saved with printed_label null on every field, so
linking scored 0.00 and nothing could be read.

- [x] Landmarks (DD-2 addition `landmarks: [{text, page, box}]`): up to 6 runs of printed words
      (a line split at wide gaps) that are not kept labels, overlap no field box (removed fields
      included), have few digits, OCR confidence >= 0.8, are not session values, appear once.
      Ranked by OCR confidence, then length.
- [x] templates/align.py: candidate fits (none, each match, each pair), most agreeing wins,
      refined; uniform scale 0.75-1.33; a move over 20% of the page is another layout.
- [x] Linking and reading go through the fit; label-less values placed with landmark support are
      not flagged needs_review.
- [x] Save dialog: landmarks listed with an opt-out box; warning when nothing can link.
      Update keeps only landmarks seen again (the list only shrinks, never adds text).
- [x] tests/test_landmarks.py (6): label-less card links and reads, shifted + zoomed card,
      other document does not link, update shrinks landmarks, fit unit tests.

## Review
- 360 passed, 4 skipped; ruff, tsc clean; UI rebuilt.
- Limit: zoom needs landmarks spread over the page; two lines close together cannot tell zoom
  from shift. Provisional: MAX_MOVE 200, RUN_GAP 30, MIN_LANDMARK_CONF 0.8, MAX_LANDMARKS 6.
- Privacy (Q22): landmarks are text that was never a field; the dialog lists each one with an
  opt-out. Needs an FRD note.
- The owner's existing PAN template has no landmarks and never links: delete and save again.

# M4 Portable installer (approved 2026-10-14: uv + wheel, Windows tested + install.sh dry-run, first run + Quit in M4) - done

Scope: FR-1.2 to FR-1.12, §7.6 flow, MH-1 to MH-9, FR-1.11 shortcut and Quit, UX-2.14 first run.

## Decisions (confirmed)
- M4-1 Release folder: install.ps1, install.sh, nabu wheel, requirements.txt, SHA256SUMS. Changed
  during build: `uv venv` + `uv pip install --require-hashes` (from uv.lock) instead of
  `uv tool install`, so every Python package is hash-pinned as well.
- M4-2 Windows tested end to end; install.sh dry-run tests only (Q1).
- M4-3 First-run screen and Quit button in M4.
- M4-4 Installer logic in `python -m nabu.install`; CLI contract (10.1) unchanged.

## 0. Spike (results)
- [x] Ollama 0.40.3 rejects `name@sha256:…` ("invalid model name"). The /api/tags digest equals the
      sha256 of the registry manifest (checked for qwen3.5:4b and :9b), so: pull by tag, compare,
      delete and stop on mismatch.
- [x] Ollama v0.40.3 assets pinned (Windows Inno Setup, PrivilegesRequired=lowest, starts the app
      after a silent install). Note: released 2026-10-11, pinned because it is the version tested
      here with qwen3.5.
- [x] uv 0.12.19 (2026-09-25) pinned for 6 platforms.

## 1-4. Built
- [x] `install/plan.py` (pure, deterministic), `pins.py`, `fetch.py` (child process, pin key only),
      `__main__.py` (detect, consent, runtime install/start, health, pull + digest, timed model
      check, OCR packs via `nabu langs pull`, config, shortcut, sample read), `shortcut.py`.
- [x] `nabu/app.py`: shortcut entry; reuses a running Nabu (recognised by its 401 reply).
- [x] Quit Nabu button, first-run dialog, GET/POST /api/first-run.
- [x] Bundled synthetic sample `src/nabu/install/sample.pdf`.
- [x] install.ps1, install.sh, build_release.py; uv cache off; skip keyed on wheel sha256.
- [~] MH-6: the chosen model is timed on the sample after install and shown on the first-run
      screen. Not done: timing every tier BEFORE the user chooses (only installed models could be
      timed without downloading).

## 5. Tests and evidence
- [x] tests/test_install.py (22): every plan path, checksum and digest mismatch, dry-run identical
      and changes nothing, install.sh and install.ps1 dry runs, shortcut, first run, pythonw stdio.
- [x] Windows end to end in temporary LOCALAPPDATA/APPDATA/NABU_HOME: install 180 s, re-run 24 s
      with no download, the real .lnk starts Nabu, a second click reuses it, first run shown once,
      Quit stops the server.
- [x] README install section.

## Review (2026-10-14)
- 353 passed, 4 skipped; ruff and tsc clean; UI rebuilt.
- Bug found only by running the real shortcut: pythonw has no stdout, uvicorn's log setup raised
  and the server never started. Fixed in nabu/app.py, with a regression test.
- Install size: app venv + Python 3.12 = 372 MB (Python 61 MB). NFR-2 says 120 MB provisional;
  M1 already measured ~270 MB for the reading stack. Needs an owner decision on the budget.
- FRD additions to report: config keys `first_run_done`, `model_seconds_per_page`; route
  /api/first-run; digest check after pull instead of pull by digest (FR-1.12 wording).
- Not tested for real: runtime download/install path (Ollama already present here), model pull
  path (only with the stub), install.sh on Linux/macOS, Linux runtime needs GNU tar with zstd.
- No uninstall command (not in FR-1); README says what to delete.
- Security review (TOCTOU): runtime download moved from the shared temp dir to a user-only
  <data_dir>/downloads (symlink refused), sha256 re-checked in the installer right before running,
  file and folder removed after; .part created O_EXCL|O_NOFOLLOW 0600. DD-6 addition: transient
  downloads/ folder, no values.

# M3 Templates: linking, saving, reuse (approved 2026-10-14: synthetic thresholds, page aspect in header) - done

Scope: FR-5, FR-7, FR-6.5, FR-6.12 (real rule), FR-9.8 remember, FR-12 templates/translations,
DD-2, DD-4, API 10.2 template and translation routes, UX-3, UX-4, AD-6 crop re-read.
Already in place: Store.save_template (AR-7 guard, versions/, atomic), templates(), delete,
history(), translation memory read path, config thresholds, CLI list/show/delete/history.
Rule kept: linking uses only words and boxes from reading; no model call (FR-5.1).

## Decisions to confirm
- M3-1 Thresholds (FR-5.3, Q9): tune on synthetic fixtures only and keep them provisional,
  unless the owner supplies an evaluation set.
- M3-2 Page shape (FR-5.2 "different page shape scores zero") needs something DD-2 does not list:
  store `pages: [{"aspect": w/h rounded to 0.01}]` in the template header. No values; reported as
  an FRD addition.
- M3-3 Ambiguous: discovery result is shown with a "choose a template" banner; picking one
  re-reads from the in-memory reading (no OCR or upload again).
- M3-4 History entries: each version's header carries `change: {renamed, added, removed,
  reordered}` with field names only; `history` lists versions with these.

## 1. Template write (templates/write.py)
- [x] build_new(result, reading, header, format_name, cfg) -> DD-2 dict: id, key slugs, version 1,
      fields in verified order (FR-7.8), anchor = printed label + label_box + value_offset
      (value box relative to anchor box), tolerance; null positions for office/text (DD-2.4);
      removed_labels from removed fields (DD-2.5).
- [x] build_update(template, ...) -> version + 1 with change summary (FR-7.4).
- [x] next_format_name (Format A, B, ...) per type and region (FR-7.3).
- [x] rollback(template_id, version): restores as a new version (FR-7.12); rename type/format (FR-7.11).

## 2. Linking (templates/link.py)
- [x] score(reading, template, cfg): share of anchors found on their page inside box widened by
      tolerance; label match tolerant to case, spacing, 0/O and 1/l; fewer pages -> score on pages
      present plus missing-page note; more pages or other shape -> 0; label-only for AD-15.
- [x] link(reading, templates, cfg) -> outcome linked / ambiguous / similar / none + candidates (FR-5.4).

## 3. Template read (templates/read.py)
- [x] For each template field: find anchor, value = words inside anchor box + offset (with
      tolerance); label-only files: rest of the line after the label. source "template",
      status from_template; missing -> not_found (FR-5.5).
- [x] Missing field with model and template_reread on -> crop around expected box to the model,
      source model_reread; else needs_review (FR-5.9, AD-6).
- [x] Similar: discovered printed labels matching an anchor get the template name as a one-click
      suggestion (FR-5.6). removed_labels hidden on linked and similar.

## 4. Pipeline and documents
- [x] pipeline.run: link after reading, before any model call; linked -> template read,
      otherwise discovery. Link result into DD-1 `link`.
- [x] PUT /api/documents/{id}/link: template id or none; re-read from session.reading (FR-5.8).
- [x] verify: save dialog needed only if not linked or names/types/field set differ (FR-6.12);
      save choices and suggested choice (FR-7.2); list of labels to be stored (FR-7.1).
- [x] save: new / update / document_only through Store; Cancel saves nothing (FR-7.5, 7.6).
- [x] translations PATCH remember -> Store.remember_translation, labels only (FR-9.8);
      memory reloaded for the next document.
- [x] Routes: GET /api/templates, GET/DELETE/PATCH /api/templates/{id}, GET .../history,
      POST .../rollback, GET/DELETE /api/translations[/{id}].

## 5. CLI
- [x] templates rollback <id> <version>; history shows the change summaries (FR-7.13).

## 6. UI
- [x] Link banner with the four FR-5.7 texts; template picker (ambiguous, change link).
- [x] Save dialog: three choices, "suggested" label, type (existing names), region, format
      (default next letter), renamed/added/removed names and labels to be stored; Save disabled
      until filled (UX-3).
- [x] Template manager screen (UX-4): tree type -> region -> format, view, delete with named
      confirmation, rename, history, roll back.
- [x] Name picker from same-type templates (FR-6.5); "Remember this translation" box (FR-9.8).

## 7. Tests and evidence
- [x] FR-5 acceptance (a)-(f) and FR-7 acceptance (a)-(f) as tests on synthetic fixtures,
      including two formats of one type and region, and a near-identical pair (ambiguous).
- [x] After every save: scan the whole store for session values (none); linking makes no model call.
- [x] Browser run in Chrome: save Format A, a second document links to it, update removes a
      field, roll back, delete; DOM checked after close.

## Review (2026-10-14)
- Results: 331 passed, 4 skipped (20 new: tests/test_templates_api.py 13 covering FR-5 (a)-(f) and
  FR-7 (a)-(f), tests/test_link.py 6 on scans with fake OCR and the stub model, 1 CLI); ruff, tsc clean.
- Browser run (Chrome, `nabu serve` with a temporary NABU_HOME, synthetic PDFs): save as new with two
  renames -> second document linked with names, values and "from your template"; remove a field ->
  Update suggested -> v2; history; roll back -> v3; rename format -> v4; half-moved layout -> similar
  with "use <name>" suggestions and header pre-filled; Change template -> linked read; delete with a
  named confirmation. After close: no values in the DOM; store held only the log (outcomes and
  scores, no values); empty template folders pruned.
- Bugs found: value box took the next line (vertical slack was the full anchor tolerance; now half the
  value height, since the box is already placed from the found label); `.wide` dialogs capped at
  440px by the base dialog rule.
- Gaps: thresholds and SHAPE_TOLERANCE (0.10) are provisional (synthetic only, Q9). "Remember this
  translation" tested through the API only, not clicked in the browser. Updating a template from an
  unlinked document replaces its fields (matching is by template key, not by label). Crop re-read
  tested with the stub model only, not qwen3.5:9b. Keyboard drawing (FR-6.13) still open from M2.
- FRD additions (reported, not written into the FRD): template header `pages` (aspect per page) and
  `change` (per version, names only); DD-1 `link.template`, `missing_pages`, `chosen`; field
  `template_key`, `name_suggestion`; verify returns `suggested`, `update_targets`, `document_types`,
  `format_suggestion`, `changes`, `labels`; PUT link returns 202 and re-reads from memory.

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
