# Beta for the team: one start script (2026-11-12) - done on Windows; macOS + clean-laptop Ollama check open

Goal: a teammate on Windows or macOS clones the repo, runs one script, and Nabu opens. The
script checks the machine, installs Nabu if needed, makes sure Ollama runs and the model is
there (installing or pulling after one y/N with sizes), then opens the review window. Every
later run skips straight to "start Ollama if needed, open Nabu".

Owner decisions (2026-11-12): Windows + macOS; delivery = git clone; ask once before
downloads; model path verified here, Ollama install path verified by the owner on a clean laptop.

Found while reviewing (README, install/*, src/nabu/install):
- The installer already does detect -> Ollama -> model + digest -> shortcut -> test read. It
  ends with "open it from the shortcut" and does not start Nabu.
- macOS bug (verified 2026-11-12): the pinned ollama-darwin.tgz holds a bare `ollama` binary +
  58 libs, not Ollama.app. plan.py unpacks it loose into ~/Applications, and runtime_program()
  looks for ~/Applications/Ollama.app/... -> Ollama never found, never started.
- After a reboot nothing starts Ollama on macOS (tarball install); the shortcut does not either.
- `nabu` is not on PATH after an install (private venv), yet README and installer messages tell
  users to run `nabu ...`.
- dist/release is from 2026-10-14 (stale); with git-clone delivery it is built on the teammate's
  machine instead.
- Model digests pinned 2026-10-14; a re-tagged model would download, mismatch and be deleted.

## 1. Start scripts (repo root)
- [ ] `start-nabu.ps1` (Windows) and `start-nabu.sh` (macOS; Linux kept working but untested).
      Steps: (a) system check: 64-bit, OS, RAM, free disk, print what was found; stop with a
      plain message if unsupported. (b) Not installed, or repo has a newer commit than the
      installed wheel -> build the release from the clone (pinned uv, UI build) and run the
      existing install script. (c) Installed -> `nabu.app` (start Ollama if needed, open window).
- [ ] Build from a clone needs the UI built (Node) -> see open question Q1.

## 2. Installer fixes
- [ ] macOS: unpack Ollama into Nabu's own folder (`~/Library/Application Support/Nabu App/ollama`),
      and look for it there; test with the real archive's file list.
- [ ] Finish by opening Nabu (not only "open it from the shortcut"), unless `--no-launch`.
- [ ] `nabu.app` (shortcut + start script): if Ollama is installed but not answering, start it
      and wait up to 60 s; if it still does not answer, open Nabu anyway (no-model reads + a
      message), never hang.
- [ ] Messages that say `nabu ...` print the full path of the installed program instead.

## 3. Model handling (verified here)
- [ ] Check the pinned digests of qwen3.5 0.8b/2b/4b/9b/27b against the registry today.
- [ ] Real pull through a second Ollama server (own port, temp OLLAMA_MODELS) with the smallest
      model: download, digest match, config written, sample read, then re-run downloads nothing.
- [ ] Mismatch path for real: a wrong pin -> model removed, no-model mode, clear message.
- [ ] Declined download -> no-model mode, Nabu still opens.

## 4. README
- [ ] New top section "Try the beta": prerequisites (OS, RAM, disk, first-run download sizes and
      time), clone + one command per OS, what the script asks, how to open it later, where
      things are, uninstall (Nabu folder, shortcut, store; Ollama and models are separate).
- [ ] Troubleshooting: Ollama not answering, digest mismatch, proxy, no GPU (slow), Korean pack.

## 5. Verification
- [ ] Tests for the new behaviour (macOS unpack target + lookup, launch step, runtime start in
      nabu.app); full suite, ruff, tsc.
- [ ] Windows end to end from a fresh clone in temp LOCALAPPDATA/APPDATA/NABU_HOME (Ollama
      present here, so the Ollama-install step is the owner's clean-laptop check).
- [ ] macOS: not testable here; needs a teammate's Mac run (owner).

## Review (2026-11-12)
- Owner answers: Node required (script checks), rebuild when the clone changes.
- Built: start-nabu.ps1 / start-nabu.sh (repo root); install.ps1 -UvOnly / install.sh --uv-only;
  `python -m nabu.install --check` (exit 3 = run setup); nabu.app starts a stopped Ollama (20 s
  max, never blocks); macOS Ollama unpacked to "Nabu App/ollama" and found there; .gitattributes
  keeps *.sh LF; README "Try the beta (team)". Installer launch step dropped: the script opens Nabu.
- Bugs found only by running: `PS` is a PowerShell alias of Get-Process (helper never ran);
  interactive children now run via Start-Process -NoNewWindow so y/N prompts are not held in a pipe.
- Model, real Ollama (second server :11500, empty model folder): declined -> no-model mode and
  check passes; pull qwen3.5:0.8b 15 min (slow line), digest match, timed 9 s, sample read;
  re-run downloads nothing; wrong pin -> model deleted, check exit 3. All 5 pins match the
  registry today.
- Windows e2e from this clone (temp LOCALAPPDATA/APPDATA/NABU_HOME, existing Ollama): first start
  231 s exit 0; second start 4 s, no rebuild.
- 419 passed, 4 skipped; ruff, tsc clean.
- Not verified: Ollama install on a clean machine (owner's laptop); macOS at all; whether the y/N
  prompt is visible in a real console (this shell has no TTY); the browser actually opening from
  the script (M4 verified the shortcut path).
- Open: repo URL for the README (no git remote set).
- Finding 3 (2026-11-12, deck screenshots, no-model mode): a template made only of hand-drawn
  fields linked the next card (1.25x closer) and placed all 5 fields, but 2 values came back
  with their printed label ("ID: ...", "DOB: ..."). Drawn fields store no printed_label, so the
  label-word skip in template read never applies to them. Without a model every value also gets
  a "not translated" chip. Not fixed; owner to rank.
- CPU-only first read (2026-11-12): second Ollama with CUDA and Vulkan hidden (log: library=cpu),
  qwen3.5:4b, synthetic SAMPLE STATE card, no template: 190 s and 155 s, 12/12 values right
  (checked by hand). 28-core CPU, so an ordinary laptop will be slower. In the deck (slides 4, 5, 20).

# M6 Real-document trial (2026-10-30) - decisions made; task 0 approved

Goal: find where Nabu fails on documents users will bring, before planning release work. Every
M3 bug came from a real card, and only PAN and Aadhaar have been tried. Output: a ranked M6
backlog, not fixes. The trial changes no reading code.

Constraint: no CLI reads documents (FR-12.2), so every document goes through the review window by
hand. The server log has only the link score and outcome; the rest is counted by hand unless
task 0 is approved.

## 0. Value-free trial metrics (approved 2026-10-30)
- [x] On Verify, one log line of counts only: pages, read seconds, link outcome, fields by source
      (template / model / rules / user-added), edited, removed, needs_review and not_found at read
      and at Verify. No names, labels or values (FR-11.5).
- [x] Test: tests/test_trial_metrics.py (3). The line matches a strict key=number pattern;
      no value, typed value, label or file name appears; one line per Verify.
- Why: about 20 documents x about 10 fields is too many edits to count reliably by hand.
- Result: 403 passed, 4 skipped; ruff clean. The line goes to <NABU_HOME>/logs/nabu.log.
- Not counted: accepting a "suggested" field with one click (no edit flag), and an edit to a
  field that was later removed. Wrong boxes are not visible in counts; note them by hand.

## Finding 1 (2026-10-30): one-landmark template misplaces fields on a zoomed photo (approved fix 1+2)
PAN card, nabu-m6: v1 saved with 1 landmark (the old nabu-test one had 3). Docs 2 and 3 linked
at 1.00, but 3 of 4 boxes were on the wrong lines (metrics: removed=3 added=3).
- Root cause: align.fit with one anchor returns scale 1.0 (shift only), and link score is
  found/total = 1/1. Doc 2 was about 1.57x zoomed (v1 vs v2 box spacing 122 -> 191 grid units).
  Update keeps only landmarks seen again, so the template can never gain a second one.
- Not confirmed: why v1 got one landmark. Likely the removed model field's box covered the
  other lines (removed fields block landmarks, write.py:164).
- [x] align.Placement.zoom_known: at least 2 agreeing anchors, spread enough to measure zoom
      (the same 50-unit rule fit() uses, now one helper `_spread`).
- [x] read.py: a label-less value counts as confirmed only when zoom is known; otherwise
      needs_review, plus one message (ONE_ANCHOR) saying why and how to fix it.
- [x] Save dialog: a second warning when labels + kept landmarks == 1. Count-based: two kept
      lines too close together get no dialog warning, only the read-time message.
- [x] Tests (test_landmarks.py +3): unit (1 anchor, 2 close, 3 spread); one-landmark template +
      zoomed card -> linked, all needs review, message once (failed before the fix); spread
      landmarks + zoomed card -> no review, no message.
- Changed: test_label_less_card_links_and_reads now expects needs_review. Its template keeps
  only two top lines 40 pt apart, which could never measure zoom (already a documented limit).
- Result: 406 passed, 4 skipped; ruff, tsc clean; UI rebuilt. Not verified in a browser: the
  new dialog warning and the message in the window.
- Owner retest (2026-10-30 09:12-09:15, nabu-m6, template deleted first): re-saved PAN template
  has 3 landmarks (y 360, 571, 716); the next PAN card linked at 1.00 and kept all 4 template
  fields with 0 edits, 0 removed, 0 needs review. This time no field was removed before saving,
  which supports (not proves) the removed-field explanation for the old single landmark.
- Not in scope: estimating zoom from one landmark's size (fix 3, optional).

## Finding 2 (2026-10-30): model discovery finds nothing usable on a PAN card - root cause found
- Two first reads with no template, qwen3.5:9b: 45.2 s, 1 field (removed by the owner), and
  46.2 s, 0 fields kept from the model (all 4 drawn by hand). Metrics lines in nabu-m6 log.
- Probe (scratchpad f2_*.py; synthetic PAN-style cards as PNG, real OCR + qwen3.5:9b, no
  owner documents). The answers were valid JSON every time; no field was lost to parsing.
  | layout                  | as sent today          | thinking on        | new prompt+schema |
  | no labels (PAN)         | 7 echoes label==value, | 7 echoes, 90 s     | 4/4 fields, 3     |
  |                         | all dropped -> 0       |                    | fixed_text, 25 s  |
  | "Label: value" per line | 1/4 (3/3 runs), 3.8 s  | 4/4 but 65 s       | 4/4 + 3 fixed     |
  | small label above value | 4/4 + headings         |                    | 4/4 + 3 fixed     |
  New prompt: 6/6 runs identical and correct, thinking off.
- Root cause: the prompt asks only for "printed label and its value". (1) A label-less value
  has no answer but an echo, which prompt.py:57 rightly drops. (2) With thinking off,
  qwen3.5:9b stops after the first field. (3) Headings are returned as values, so they are
  registered with the session (AR-7) and can never become landmarks: this is the likely
  cause of finding 1's single landmark.
- Side finding (not in this fix): qwen3.5 returns boxes on a 0-1000 grid, but the profile reads
  them as pixels, so boxes past the image edge become None. Grounding on OCR hides it.

### Fix (owner go 2026-10-30) - done, awaiting owner check
- [x] Discovery prompt (client._DISCOVERY_SYSTEM): list every field in reading order; a value
      with no printed label is still a field (printed_label null, name = short English name);
      fixed printed text is listed as kind fixed_text with value null.
- [x] Schema per field: kind (field | fixed_text), name, printed_label (nullable), value,
      value_type, bbox, confidence. An answer in the earlier shape (`label`) still parses.
- [x] Parsing: fixed_text items are dropped in client.discover_page, before any value is
      registered, so the text can become a landmark. A printed_label equal to the value counts
      as no label (prompt.py). The echo rule stays.
      Privacy: a value the model wrongly calls fixed_text is unregistered, which is the same as
      the model missing it today; the save dialog still lists every landmark with an opt-out.
- [x] Field: printed_label = the printed label or None. Name: unchanged rule (FR-9), the printed
      label (translated) names the field; the model's name is used only without one.
- [x] Found while verifying: the model wrote type_guess "null" as a string, which would have
      pre-filled the document type with "null". "null", "none", "unknown", "n/a" -> None.
- [x] Tests: test_pipeline (fixed_text dropped and unregistered, printed == value -> None,
      label-less kept); test_model_layer (type_guess words, 5 cases). Both failed first.
      412 passed, 4 skipped; ruff clean.
- [x] Real model through Nabu's code (f2_probe.py, synthetic cards): 4/4 fields in the window on
      all three layouts, no headings, boxes on the values, 26-38 s.
- Known: on the label-less card the model swapped "Name" and "Father's Name" in one of two
  runs (it names by position). The owner renames once; the template keeps the names.
- [ ] Owner check: a PAN card first read in nabu-m6 (the PAN template from 09:12 must be
      deleted first, or it links and the model is not asked).
- Not in scope: qwen3.5 box coordinates (grid_1000 read as pixels), the next change.
- Synthetic US licence probe (2026-11-06; scratchpad nycdl/make_dl.py + probe.py, review API,
  real OCR + qwen3.5:9b, fresh NABU_HOME). Made-up issuer "SAMPLE STATE" with SPECIMEN stamp,
  NYC holder addresses; 12 fields, 4 printed with no label (name x2, address x2).
  - First read, no template: 12/12 values in 3/3 runs (55-66 s); label-less ones kept with
    printed_label None; headings not returned as values; save kept 5 landmarks.
  - Template saved; same card for another holder at 1.25x and 0.8x zoom: linked 1.00, 12/12
    values, 6-8 s. One field (CLASS, a single letter) went to model re-read + needs_review once.
  - Seen: the model names label-less fields in snake_case (last_name, address_line_1). The user
    renames once; worth a prompt word ("in plain words, e.g. Last name") if it bothers the demo.
  - This is not the owner check above: a real PAN photo is still open.

## Fix (2026-11-06): test_install_sh_dry_run failed when pytest ran from PowerShell
- Cause: from PowerShell, `sh` is Git's launcher (Git\bin\sh.exe), which puts its /usr/bin
  ahead of the inherited PATH, so the real uname (MINGW64_NT) beat the test's uname shim.
  From Git Bash, `sh` is usr\bin\sh.exe and the shim won. Not order-dependent, not from M6.
- [x] The test now prepends the shim inside the shell (`PATH="$PWD/shim:$PATH" exec sh ...`,
      cwd = tmp_path). Passes from PowerShell and Git Bash. CI (Linux, macOS) not run here.

## 1. Document set (15-20, owner collects)
Each type at least twice, so the second copy tests linking.
- [ ] ID: PAN x3 (different photos), Aadhaar x2, driving licence x2, passport x2.
- [ ] Business: invoice x3 (2 from the same vendor; 1 digital PDF, 1 scan), a multi-page
      statement x1, an office file (xlsx or docx) x1.
- [ ] Language: at least 2 non-English documents, one of them Korean (needs `nabu langs pull ko`).
- [ ] Capture: flat scan, good phone photo, bad phone photo (angle, glare, low light), digital PDF.
- [ ] Error inputs: encrypted PDF, unsupported type (e.g. HEIC). Check that each gets a named message.

## 2. Setup
- [ ] Scratch store: NABU_HOME=%LOCALAPPDATA%\Temp\nabu-m6, export off, no existing templates.
- [ ] Documents in a local folder outside the repo; never copied into fixtures/ or tasks/.
- [ ] Record `nabu doctor` (tier, model, GPU), because read times only mean something for that machine.

## 3. Per document (fixed order)
1. Upload and time the read.
2. Note link outcome and score.
3. Review: count correct untouched, corrected, missed (added), spurious (removed), wrong box,
   and translation problems.
4. Verify, then save. Use a new template for the first copy of a type, and update for later copies.
5. Write one row in tasks/m6-trial.md.

## 4. Trial sheet (tasks/m6-trial.md), value-free
- Columns: id (D01...), type, capture, language, pages, read s, link outcome/score, fields on
  paper, correct untouched, corrected, missed, spurious, wrong box, translation issues, notes.
- Notes name the field, never the value: "DOB took the name line", not the date or the name.
- [ ] Checked before commit: grep the sheet for digits runs and names; no screenshots in the repo.

## 5. Results
- [ ] Per type: share of fields right without an edit; second-copy link rate; read s per page.
- [ ] Spot-check 3 documents' counts by hand against the screen (ledger 2026-10-06).
- [ ] Backlog: each failure with type, frequency, cost to the user (one edit / re-draw box /
      unusable), and a value-free way to reproduce it; ranked by frequency x cost.
- [ ] Owner picks what goes into M6. Pass bars stay provisional until the data exists.
- [ ] Cleanup: `nabu forget` on the scratch store; delete the document folder if the owner wants.

## Decisions (owner, 2026-10-30)
- Q1 Documents: the owner's own, family and colleagues' with their consent, and published
  specimen images. Not company business documents, so invoices and statements come from
  personal purchases or specimens.
- Q2 First users' document types are not known yet, so all types are weighted equally.
- Q3 Task 0 (metrics line) approved.
- Q4 This machine only; read times describe this tier alone.

# M5 Product page + clickable demo (approved 2026-10-29) - done, owner reviewed 2026-10-30

Spec: LocalLens FRD §16 M5 (owner, 2026-10-29; Nabu FRD v1.1 not on disk). "Product page on the
team site, an embedded demo of the review window on a sample licence; acceptance: published URL
rendering the demo." Owner decisions: build locally only (owner publishes); name "Nabu", marked as
a codename, no download or licence claims.

Starting point: fixture mode (ui/src/backend.ts fixtureBackend) is already a no-network review
window. Gaps: its sample is an invoice, not a licence, and pageImage() returns null (no page shown).

## 1. Synthetic specimen licence
- [x] fixtures/demo/licence.svg: a fictional driving licence, "SPECIMEN - synthetic" printed on it,
      a made-up issuer and person, no real format, number scheme or emblem copied.
- [x] fixtures/demo/working_result.licence.json: DD-1 working result for it. Fields cover every
      status the window shows (from template, suggested, needs review, not found, not translated)
      and one non-English label so the translation UI shows.
- [x] Test: each field box encloses the text the SVG prints for that value (same 0-1000 grid), so
      highlights land on the right words.

## 2. Demo build (ui)
- [x] `vite build --mode demo` -> dist/site/demo/, base "./", the licence fixture, pageImage()
      returns the bundled SVG. The dev and server builds stay unchanged (invoice fixture,
      ui_dist).
- [x] The demo banner says: "Demo · synthetic sample · nothing is read or sent". Upload, Quit and
      templates are disabled with a note, not broken.

## 3. Product page
- [x] dist/site/index.html + css, no JS needed: what Nabu does, how a document flows (read ->
      review -> JSON), the privacy rules that are enforced today (from the README table),
      status (M1-M4 done, Windows tested, Linux/macOS dry-run only), "Nabu is a working name".
      The demo is embedded in an iframe, with an "open full screen" link.
- [x] No remote fonts, scripts or images; no download link, price or licence claim.
- [x] install/build_site.py (or an npm script) builds both into dist/site in one command.

## 4. Verification
- [x] Tests: build output has no http(s) references to other hosts; fixture box test; existing
      suite and ruff stay green.
- [x] Real browser run (lesson 2026-10-14): serve dist/site over a local static server, click
      through select field, edit, translate, verify, save; check for console errors and confirm
      network requests stay on the same origin; screenshots of the page and the demo.
- [x] README: M5 section (how to build and publish dist/site), roadmap status.

## Not in scope
- Publishing to a team site (owner does it). Trademark (Q10) and licence choice.

## Review (2026-10-29)
- Built: `python install/build_site.py` -> dist/site (index.html, site.css, demo/). The demo is the
  real review window in fixture mode, on the licence sample, with Start over in place of upload.
  Its download is the real output shape (port of json_out.build), validated against
  output.schema.json from a browser capture.
- Browser run (Chrome, served by `python -m http.server`): page and embedded demo render; select
  highlight, translate Conditions, accept Licence Number, Verify (10 fields, 1 not found, 1 needs
  review, 0 not translated), Save, download, Start over, Templates. No console errors; every
  request is same-origin (plus the browser extension's own). Page fits 390px with no horizontal
  scroll (measured in a 390px iframe; window resize did not apply).
- Found in the browser, fixed: (1) the window's field-name labels covered the card's printed
  labels; the card now prints labels left of values, rows 58 units apart. (2) The save dialog
  marked the disabled "new template" option as suggested; fixture Verify no longer suggests.
- Tests: tests/test_demo_site.py (14): sample matches its generator, boxes enclose the SVG's text
  (mutation-checked), statuses covered, no remote loads in page/demo sources, no release claims.
  Full suite 400 passed, 4 skipped; ruff and tsc clean.
- Server build unchanged: it still carries only the invoice fixture and no CSP meta (checked).
- Not verified: Safari/Firefox; light theme; the page on the real team site.

# M3.3 Owner retest fixes (2026-10-28) - done, owner retest passed 2026-10-30

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

# M3.2 Linking on real photos, template folder, export folder (approved 2026-10-21) - done, owner retest passed 2026-10-30

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
