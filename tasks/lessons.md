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

