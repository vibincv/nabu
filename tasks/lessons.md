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
