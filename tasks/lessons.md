# Lessons

- **2026-10-13: Git Bash heredocs mangle backslash escapes.** A Python edit script passed through
  `python - <<'EOF'` turned `"\n"` into a real newline, so string replacements silently failed
  to match (once, an `assert` caught it; once, a helper was silently not inserted). Rule: for
  edits whose text contains backslashes, use the Edit tool, and always `assert old in s` before
  `replace` in scripted edits.
  **Repeated 3 more times in the M1 session** (prompt text with `\n`, an RTF regex, byte
  literals in a test). Each time the assert stopped it, but each cost a round trip. Stricter
  rule: before writing a scripted edit, scan the old and new text for `\`; if there is one, use
  the Edit tool, no exceptions.
- **2026-10-13: Check tier tables against the hardware they will run on.** The FRD gave a 27b
  model to any >= 32 GB RAM machine; `doctor` on a real 64 GB machine showed that would be too
  slow. Run new defaults through `doctor` on a real machine before accepting them.
  Correction (M1): that machine also has an RTX 4060 Laptop GPU (8 GB). The earlier `doctor` could
  not detect GPUs, so "CPU machine" was wrong. Rule: a hardware claim needs a detector that can
  see the hardware; say "not detected", never "absent".
- **2026-10-14: A rule can pass its unit tests and still never run.** The day-first-by-language
  date rule passed 8 tests that set `lang` directly. On a real German invoice the detector returned
  None (every label a compound word), so the rule never fired. Rule: when a rule depends on an
  upstream value (language, region, type), run it once through the real pipeline on a realistic
  document and check the upstream value is actually set, not only the rule's output.
- **2026-10-14: The backslash rule was broken again.** A large route edit went into a Git Bash heredoc
  with `
` and `ÿ` in it; bash failed on quoting before Python ran. No damage, one round trip lost.
  Rule stays: scan the edit text for `\` first; if present, use the Edit tool.
- **2026-10-14: Tests passed; the browser found six bugs.** 28 API tests were green, yet one real run in
  Chrome found: page-level scroll hiding the header, a narrow picker, a reloaded window locked out,
  a stale "Verified" banner, closed-document text left in the DOM, no progress during translation.
  Rule: a UI milestone is not done until one real end-to-end run in a browser, checking the DOM after
  close, not only screenshots.

- **2026-10-14: Tolerances must match what is already compensated.** The template value box was
  widened vertically by the full anchor tolerance (30 grid units), but lines were 36 units apart, so
  every value took the next line's first word. The box was already placed from the label found on
  this document, so scan shift was compensated once already. Rule: when a position is derived from
  a matched anchor, size the slack to the remaining error (value length, line height), not the
  global tolerance; test with lines at normal spacing, not spread out.
- **2026-10-14: The heredoc rule, once more.** A Python edit in `python - <<'EOF'` with no
  backslash still failed on quoting (unexpected EOF). Writing the script to the scratchpad with the
  Write tool and running it worked first time. Rule: large scripted edits go into a file, always.

## 2026-10-14 M4: test the real launch path, not a simulation of it
- A Bash repro with `sys.stdout = None` passed, but the real `pythonw` start of the shortcut
  died in uvicorn's log setup. Only running the actual shortcut command showed it. For entry
  points that differ by host (pythonw, services, shortcuts), run the real binary and capture
  errors to a file before calling it working.
- Python heredocs that write shell or Python source turn `\n`/`\r` escapes into real line
  breaks (twice this session). Use the Edit tool for any text that contains escapes.
- An installer that skips by version string never installs a rebuilt wheel with the same
  version. Key "already installed" on the artefact hash.

## 2026-10-14 "Something went wrong" report
- On Windows a venv `python.exe` is a launcher that starts the real interpreter as a child.
  `Stop-Process` on the launcher leaves the server running; use `taskkill /PID <id> /T /F`.
  Killing a test server that way left a page open with no server behind it.
- The UI's catch-all message hid the cause (fetch rejects with TypeError when nothing answers),
  and `.catch(() => [])` made the template manager claim "No templates yet" with no server.
  Map transport failures to a message that says what to do; never read an error as "empty".

## 2026-10-14 PAN card template linked at 0.00
- M3 was designed and tested only on "Label: value" documents. An ID card prints values with no
  label, so the template stored no anchors and could never link, and saving accepted it
  silently. Test every learned artefact on the document shapes the product targets (ID cards,
  receipts), and make a save that cannot work say so.
- A plain least-squares fit made a different layout "the same form, moved"; the existing
  Format B test caught it. Keep negative tests (must NOT link) next to every looser matcher.

## 2026-10-21 Second PAN photo did not link
- Every test card was an A4 PDF page, so the photo's shape never changed and the page-shape gate,
  the per-axis grid and the one-factor offset scaling all looked correct. Real input is phone
  photos of any shape and zoom. Generate test inputs that vary every property real capture
  varies (page shape, zoom, position), not only the content.
- The owner's retest failed partly on a template saved before the fix. After a fix to a learned
  artefact, say which saved artefacts it cannot repair, and check the owner's store, not only
  the tests.

## 2026-10-29 M5 demo
- A synthetic sample laid out on its own looked fine; inside the window, the field-name label
  the window draws above every box covered the card's printed labels. Lay out a demo or test
  document against what the viewer overlays on it, and look at it in the real window first.
- A browser output check gave a wrong value because the page had reloaded between two JS calls
  (state kept in `window` was gone). Do the action and the capture in one call, and check a state
  marker (banner text) in the same call before trusting the result.
- An Edit that "inserts above a heading" by replacing the heading line dropped the heading
  (M3.3). When inserting before an anchor, put the anchor back in new_string and diff after.

## 2026-10-30 M6 trial, finding 1
- A template with one landmark linked every PAN photo at 1.00 and misplaced 3 of 4 boxes on a
  zoomed one. The score was found/total = 1/1, and every test template had 3 landmarks, so a
  ratio that means nothing at n = 1 looked like certainty. When a score is a ratio, test it at
  the smallest denominator real data can produce, and do not call a result confirmed when the
  evidence cannot measure the thing that varies (zoom needs two anchors spread apart).
- The earlier "it looks good" PAN retest ran with no model configured. Check what a run
  actually used (doctor: configured_model) before treating it as coverage of the model path.

## 2026-10-30 M6 trial, finding 2
- The discovery prompt was only ever run against stub answers, so its wording was never tested:
  the real model (thinking off) stopped after one field and could not express a label-less
  value. A prompt is code that only the real model executes. Probe each prompt change against
  the real model on synthetic pages of every layout the product claims (labels inline, above,
  none), more than one run each, before trusting stub tests.
- A model writes "null" as a string where JSON null was asked. Normalise words for "nothing"
  at every free-text field the model fills.

## 2026-11-06 install test "flaky in the full run"
- test_install_sh_dry_run failed in two full runs and passed alone, so I called it
  order-dependent and bisected test files for 20 minutes. The real variable was the shell:
  full runs were started from PowerShell, single runs from Git Bash, and Git\bin\sh.exe
  rewrites PATH. When a test passes "alone" and fails "together", first rerun both ways from
  the SAME shell before bisecting.
- Comparing against HEAD in a git worktree used the venv's editable install, so HEAD's tests
  ran against the modified src. Set PYTHONPATH=<worktree>/src and print `nabu.__file__` first.

## 2026-11-12 PowerShell helper names and console prompts
- A function named `PS` never ran: `PS` is a built-in alias of Get-Process, and aliases win over
  functions. Use Verb-Noun names for PowerShell helpers (Start-Child), never 2-letter names.
- A PowerShell function that runs a native program returns its output with the exit code, and
  a pipe holds a prompt that has no line end. Run interactive children with
  `Start-Process -NoNewWindow -Wait -PassThru` and return only `.ExitCode`.
- A start script parsed and its unit tests passed; only running it end to end found both.

## 2026-11-20 PowerShell scripts ignore unknown options
- A `param()` block without `[CmdletBinding()]` puts unknown options in `$args` and runs on. I
  "tested" start-nabu.cmd with `-NoSuchOption`, expecting a binding error; it did a full
  reinstall and launched Nabu. Every user-facing .ps1 now has `[CmdletBinding()]`.
- Never run a launcher or installer to test argument handling. Copy the file head up to the end
  of the param block (`$ast.ParamBlock.Extent.EndOffset`, which keeps the attributes) and add a
  stub body. `ParamBlock.Extent.Text` alone drops `[CmdletBinding()]`, so a stub built from it
  tests the old behaviour.
