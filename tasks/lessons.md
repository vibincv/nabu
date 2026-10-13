# Lessons

- **2026-10-13: Git Bash heredocs mangle backslash escapes.** A Python edit script passed through
  `python - <<'EOF'` turned `"\n"` into a real newline, so string replacements silently failed
  to match (once, an `assert` caught it; once, a helper was silently not inserted). Rule: for
  edits whose text contains backslashes, use the Edit tool, and always `assert old in s` before
  `replace` in scripted edits.
- **2026-10-13: Check tier tables against the hardware they will run on.** The FRD gave a 27b
  model to any >= 32 GB RAM machine; `doctor` on a real 64 GB CPU machine showed that means
  minutes per page. Run new defaults through `doctor` on a real machine before accepting them.
