# Nabu

Nabu reads documents on your own machine. You check every field it finds and correct anything wrong. It then gives you a JSON file. Nothing leaves the machine, and Nabu never stores the values it reads.

> **Status:** M1 foundation. This version has the privacy guards, the store, the CLI, the review server and a review-UI shell that runs on a synthetic fixture. Reading documents comes next (see [Roadmap](#roadmap)).
>
> "Nabu" is a codename until the trademark search is done (FRD Q10).

The source of truth is the FRD: *Nabu — Functional Requirements Document v1.1*. Requirement IDs in the code (FR-x, AR-x, DD-x, API-x) refer to it.

## Quick start (development)

You need Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
uv sync                      # Python deps + dev tools
uv run pytest                # offline test suite
uv run ruff check .

cd ui && npm ci && npm run build && cd ..   # builds the UI into src/nabu/server/ui_dist
uv run nabu serve            # opens the review window on 127.0.0.1
uv run nabu doctor --json
```

To develop the UI on its own, run `cd ui && npm run dev`. It renders the bundled synthetic fixture, so you don't need a backend.

To keep test data away from your real store, set `NABU_HOME=/tmp/nabu-dev`.

## What is enforced today

| Rule | Where | Test |
|---|---|---|
| Only loopback network. Every connect and DNS lookup to anything else is refused at run time (AR-3, FR-11.2) | `nabu/netguard.py` | `tests/test_netguard.py` |
| The model endpoint must be localhost, or Nabu refuses to start (AR-3, FR-10.1) | `nabu/config.py` | `tests/test_config.py` |
| The model client ignores proxy environment variables and never follows redirects | `nabu/model/ollama.py` | `tests/test_model_and_cli.py` |
| The store is the only disk writer. It refuses any template or translation that contains a session value (AR-2, AR-7) | `nabu/store/` | `tests/test_store.py` |
| Store files are 0600 and folders 0700, written atomically (FR-11.7) | `nabu/store/paths.py` | `tests/test_store.py` |
| Session data lives only in memory and is released on close (AD-8) | `nabu/session.py` | `tests/test_store.py` |
| Logs show exception *types* only. No messages, no tracebacks (FR-11.5) | `nabu/hardening.py` | `tests/test_output_schema_and_logging.py` |
| Core dumps are off (POSIX) | `nabu/hardening.py` | — |
| Host and Origin checks, a per-run token sent only in a header, plus CSP, `no-store` and `no-referrer` (API-1, 3, 5, 6) | `nabu/server/app.py` | `tests/test_server.py` |
| The UI turns off spell-check, autocomplete and translate (FR-6.18) and loads nothing remote | `ui/` | — |
| There is no CLI command that reads documents (FR-12.2) | `nabu/cli.py` | `tests/test_model_and_cli.py` |

### Known residual risks (documented, not fixed)

- **Code outside Python's socket layer.** The egress guard covers Python sockets only. A native extension opening its own sockets, or a subprocess, would bypass it. Review every native dependency when you add it.
- **Windows crash dumps.** Windows Error Reporting may keep a minidump after a crash. Python has no per-process switch for this.
- **Browser extensions.** In a normal browser, extensions can read the review window. FRD Q21 decides whether to use a native window instead.
- **The no-values guard has blind spots.** It catches only values Nabu identified as field values in the current session. Identifying printed labels, such as a letterhead, are FRD Q22.

## Layout

```
src/nabu/
  cli.py            commands (FR-12); there is no read command
  config.py         config + loopback validation (DD-5, AR-3)
  netguard.py       run-time egress guard
  hardening.py      core dumps off, safe logging
  session.py        in-memory session (AD-8)
  doctor.py         machine report (FR-1.1)
  store/            the only disk writer + no-values guard (AR-2, AR-7)
  model/            Ollama client (FR-10)
  server/           review window API + UI host (10.2)
  schemas/          output JSON Schema (DD-3)
  pipeline.py router.py extract/ ocr/ lang/ discovery/ fields/ templates/ output/
                    stubs, one docstring each, filled in M1–M3
ui/                 Vite + TypeScript review UI; builds into src/nabu/server/ui_dist
fixtures/           synthetic only, never real documents
tests/              offline; tests/stub_ollama.py mimics the runtime
```

## Dependency rules

- **Reading stack.** It is the `read` extra (`uv sync --extra read`). It stays optional until M0 confirms install size against NFR-2.
- **Licences.** Check the licence of every new dependency. Do **not** add PyMuPDF/fitz, which is AGPL-3.0. Render PDFs with pypdfium2.
- **Model.** The model is a config value, never hard-coded (FR-10.2). The FRD's default `qwen2.5vl:3b` is under the Qwen Research License, which is **non-commercial only**. M0 must pick a licensable default.

## Roadmap

| Milestone | Scope |
|---|---|
| M0 | Spike: model choice (licence and speed), anchor linking on phone photos, OCR size and Korean, memory-only readers |
| M1 | Reading engine: router, extractors, OCR, discovery, translation rules, full `doctor` |
| M2 | Review window on live data, Verify, output JSON |
| M3 | Templates: linking, save dialog, template manager, translation memory |
| M4 | Installer |
| M5 | Static demo page |

## Licence

Not chosen yet. Decide before the first external release.
