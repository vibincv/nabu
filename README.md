# Nabu

Nabu reads documents on your own machine. You check every field it finds and correct anything wrong. It then gives you a JSON file. Nothing leaves the machine, and Nabu never stores the values it reads.

> **Status:** M5 product page. Done so far: the reading engine (M1), the review window and JSON output (M2), templates (M3), the per-user installer with model bootstrap (M4), and the product page with a clickable demo (M5). Windows is tested end to end. `install.sh` (Linux, macOS) is covered by dry-run tests only (see [Roadmap](#roadmap)).
>
> "Nabu" is a codename until the trademark search is done (FRD Q10).

The source of truth is the FRD: *Nabu — Functional Requirements Document v1.1*. Requirement IDs in the code (FR-x, AR-x, DD-x, API-x) refer to it.

## Try the beta (team)

One script checks your machine, installs Nabu, makes sure Ollama (the local model runtime) and a model are ready, and opens Nabu. Run the same script every time you want to use Nabu.

### What you need

| | Windows | macOS |
|---|---|---|
| System | Windows 10 or 11, 64-bit, Intel or AMD processor (not Windows on ARM) | Apple silicon or Intel Mac |
| Tools | [git](https://git-scm.com/downloads) and [Node.js](https://nodejs.org) 20 or newer (LTS). Node only builds Nabu's window; Nabu does not need it to run | same |
| Internet | Only for the first setup and for updates. Reading documents never uses the network | same |
| Admin rights | Not needed. Everything installs for your user only | same |

Python is not needed: the script fetches its own copy.

**Disk and download.** Nabu itself takes about 0.4 GB. If Ollama is not installed yet, it is downloaded too: 1.6 GB on Windows, 0.17 GB on macOS. The model depends on your machine's memory:

| Your machine | Model | Download |
|---|---|---|
| under 8 GB memory | none offered by default (no-model mode; `qwen3.5:0.8b` can be added) | — |
| 8–15 GB memory | `qwen3.5:2b` | 2.7 GB |
| 16–31 GB memory | `qwen3.5:4b` | 3.3 GB |
| 32 GB memory or more, or 16 GB with an NVIDIA GPU of 6 GB or more | `qwen3.5:9b` | 6.6 GB |
| NVIDIA GPU with 16 GB or more | `qwen3.5:27b` | 17.5 GB |

Only NVIDIA GPUs are detected. On a Mac, the model is chosen by memory alone. The installer shows the exact sizes and your free disk, and asks once before it downloads anything. Keep the download size plus 2 GB free.

### First start

```powershell
# Windows (PowerShell)
git clone <repo URL> nabu
cd nabu
powershell -ExecutionPolicy Bypass -File start-nabu.ps1
```

On Windows you can also double-click `start-nabu.cmd` in the cloned folder (or run `start-nabu.cmd -Setup` and so on). It runs the same script with the same options and keeps the window open if something fails.

```bash
# macOS (Terminal)
git clone <repo URL> nabu
cd nabu
sh start-nabu.sh
```

The script:

1. Checks the machine (system, memory, free disk) and stops with a plain message if something is missing.
2. Builds Nabu's window (`npm ci`, `npm run build`) and a release from your clone, then runs the installer. The installer:
   - reuses Ollama if it is installed, or offers to install a pinned, checksum-checked Ollama for your user;
   - picks the model for your machine and asks **once** before downloading Ollama and the model, showing sizes and free disk;
   - checks the downloaded model against the digest pinned in Nabu, and deletes it if they differ;
   - times the model on a synthetic sample, adds a **Nabu** shortcut, and reads a bundled synthetic sample to prove everything works.
3. Opens the review window in your browser.

The first start takes a few minutes plus the download. At 10 MB/s, the 6.6 GB model takes about 11 minutes.

If you answer **no** to the download, Nabu still installs and opens in no-model mode. Digital files (PDFs with text, office files) and saved templates still work; photos and scans of a kind of document with no template yet, and translation, need a model. To add the model later, run the script with `-Setup` (Windows) or `--setup` (macOS).

### Every later start

Run the same command, or use the **Nabu** shortcut (Start menu on Windows, Applications on macOS). Both start Ollama if it is stopped, for example after a reboot. The script also checks that the model is still installed and offers to download it again if it is not. Stop Nabu with **Quit Nabu** in the window, or Ctrl+C in the terminal.

### Getting updates

```bash
git pull
```

Then start Nabu with the script as usual. It notices that the code changed and reinstalls Nabu before it opens. This takes a minute or two and downloads no model. The shortcut does not update Nabu; only the script does.

### Options

| Windows | macOS | What it does |
|---|---|---|
| `-Setup` | `--setup` | Run the Ollama and model setup again, e.g. to add a model after answering no |
| `-Model qwen3.5:4b` | `--model qwen3.5:4b` | Use this model instead of the recommended one (`none` for no-model mode) |
| `-Reinstall` | `--reinstall` | Rebuild and reinstall Nabu even if the code did not change |
| `-NoLaunch` | `--no-launch` | Set everything up, but don't open Nabu |

### Where things go

| | Windows | macOS |
|---|---|---|
| Nabu (program) | `%LOCALAPPDATA%\Nabu` | `~/Library/Application Support/Nabu App` (also holds Nabu's own Ollama, if it installed one) |
| Settings and templates (never document values) | `nabu doctor` shows the folder | same |
| Log | `logs\nabu.log` in the settings folder (no document values) | same |
| Ollama | `%LOCALAPPDATA%\Programs\Ollama` (if Nabu installed it) | see above |
| Models | `%USERPROFILE%\.ollama\models` | `~/.ollama/models` |

The `nabu` command is not added to your PATH. To run it, use its full path: `%LOCALAPPDATA%\Nabu\app\Scripts\nabu.exe doctor` on Windows, or `~/Library/Application\ Support/Nabu\ App/app/bin/nabu doctor` on macOS.

### Remove Nabu

1. Run `nabu forget --all` (full path above) to delete templates and learned data.
2. Delete the Nabu program folder and the **Nabu** shortcut.
3. Ollama and its models are separate programs and other tools may use them. To remove them too: on Windows, uninstall Ollama from Settings > Apps and delete `%USERPROFILE%\.ollama`; on macOS, delete `~/.ollama`.

### If something goes wrong

| What you see | What to do |
|---|---|
| `Node.js 20 or newer is needed` | Install the LTS version from nodejs.org, open a **new** terminal, run the script again |
| `Ollama does not answer` | Start the Ollama app yourself, wait a few seconds, and run the script again. If Ollama is not installed, the script offers to install it |
| `does not match the digest shipped with Nabu; it was removed` | The model online changed since this Nabu version pinned it. Tell the Nabu owner; meanwhile Nabu works in no-model mode |
| `npm ci` or a download fails behind a company network or VPN | Run the first setup on another network, then go back. Proxy setups are not tested yet; report what you saw. Nabu never uses the network while reading |
| Reads are slow (a minute or more per page) | Expected on a machine without an NVIDIA GPU. Templates make later copies of the same form fast |
| Korean text is not read | Run `nabu langs pull ko` (full path above) |
| PowerShell says running scripts is disabled | Start it as shown, with `powershell -ExecutionPolicy Bypass -File start-nabu.ps1`, or double-click `start-nabu.cmd` |
| `A parameter cannot be found that matches parameter name` | An option is misspelled. Windows options use one dash: `-Setup`, not `--setup` |

When you report a problem, send the terminal output and `nabu doctor --json`. **Never send document images or values.** Notes like "the date field took the name line" are enough.

### Beta limits

- Windows is tested end to end. **macOS is not tested yet**: the first teammate on a Mac, please report how the first start went. Linux uses `start-nabu.sh` too but is untested.
- Ollama's own installer step on a machine without Ollama is being checked on a clean laptop.

## Install (users)

Build a release folder (developers: see below). Then, on the user's machine, run one of these from that folder:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun   # Windows: print the plan, change nothing
powershell -ExecutionPolicy Bypass -File install.ps1
```

```bash
sh install.sh --dry-run    # Linux / macOS
sh install.sh
```

The script first checks the release files against `SHA256SUMS` and fetches a pinned `uv` (checksum checked). Then it creates Nabu's own Python environment with hash-pinned packages. No admin rights or system Python are needed.

Next it runs `python -m nabu.install`, which:

- reuses a running Ollama and any installed models;
- otherwise offers the pinned Ollama build (sha256 checked) and the model for this machine's tier, showing size, disk needed and location first;
- checks a pulled model against its pinned digest;
- offers OCR language packs;
- writes the config and adds the **Nabu** shortcut;
- does a test read of a bundled synthetic sample.

Running it again downloads nothing. Options: `--model NAME|none`, `--yes`, `--no-shortcut`.

Where the app goes:

- Windows: `%LOCALAPPDATA%\Nabu\` (`uv`, `python`, `app`)
- Linux: `~/.local/share/nabu-app`
- macOS: `~/Library/Application Support/Nabu App`

The store (config, templates) stays where DD-5 puts it. To uninstall, delete that folder and the shortcut. Run `nabu forget --all` first to remove learned data.

### Templates folder

Templates go in `templates` under the store unless `config.json` names another folder:

```json
{ "templates_dir": "D:\\Nabu\\templates" }
```

The path must be absolute, and it can't be the store folder or a folder that contains it. Every command uses it, and so does the review window. `nabu doctor` shows which folder is in use. Nabu doesn't move existing templates. To keep them, copy the `templates` folder's contents into the new folder before you switch. A shared folder works for several machines, but two people saving the same template at the same moment is not guarded against. `nabu forget --templates` removes only Nabu's template files there, never other files.

### Export folder (for another service)

To have another program pick up each confirmed document, set an export folder in `config.json`:

```json
{ "export_dir": "D:\\Nabu\\outbox" }
```

Every Save after Verify writes the document's output JSON there, whichever save option you pick. The format is the same as the download. Files are named `<file name>.<UTC time>.<id>.nabu.json`, so a second scan with the same file name never overwrites the first. Each file is written whole before it appears. Ignore files that start with a dot: they are temporary files still being written.

**These files hold the document's values (names, numbers, dates) in plain text.** This is the one place Nabu writes values to disk, so it is off unless you set the folder. The folder can't overlap Nabu's store or templates folder, so those stay free of values. Nabu never deletes exported files: the program that reads them must remove them. Protect the folder as you would the documents themselves. On Linux and macOS the files are readable only by the user who runs Nabu.

If the folder can't be written, the save still succeeds. The window says why the export failed, and the JSON can still be downloaded.

To build the release folder you need `uv` and a built UI:

```bash
cd ui && npm ci && npm run build && cd ..
python install/build_release.py --out dist/release   # wheel, hashed requirements.txt, scripts, SHA256SUMS
```

## Quick start (development)

You need Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
uv sync --extra read         # Python deps + reading stack (OCR, PDF, office) + dev tools
uv run pytest                # offline test suite (reading tests skip without --extra read)
uv run ruff check .

cd ui && npm ci && npm run build && cd ..   # builds the UI into src/nabu/server/ui_dist
uv run nabu serve            # opens the review window on 127.0.0.1
uv run nabu doctor --json
```

To develop the UI on its own, run `cd ui && npm run dev`. It renders the bundled synthetic fixture, so you don't need a backend.

To keep test data away from your real store, set `NABU_HOME=/tmp/nabu-dev`.

## Product page and demo (M5)

```bash
python install/build_site.py      # needs npm; writes dist/site
```

`dist/site` holds the product page (`site/`) and, under `demo/`, the real review window built in demo mode (`vite build --mode demo`). The demo runs on a synthetic specimen licence (`fixtures/demo`, made by `make_licence.py`) and talks to no server: edits, Verify, Save and the JSON download all happen in the browser. Upload is not offered, and Start over reloads the sample.

Every file is static, and nothing loads from another site. Each page carries its Content-Security-Policy as a meta tag. Serve the folder from any static host; to look at it locally, run `python -m http.server -d dist/site`. Opening `index.html` straight from disk does not run the demo, because browsers do not run module scripts from `file://`.

Publishing it is a manual step. The page says Nabu is a working name, makes no download, price or licence claim, and states which installers are tested.

## What is enforced today

| Rule | Where | Test |
|---|---|---|
| Only loopback network. Every connect, datagram send and DNS lookup (forward and reverse) to anything else is refused at run time, including asyncio's Windows Proactor loop (AR-3, FR-11.2) | `nabu/netguard.py` | `tests/test_netguard.py` |
| The model endpoint must be localhost, or Nabu refuses to start (AR-3, FR-10.1) | `nabu/config.py` | `tests/test_config.py` |
| Model requests ignore proxy environment variables, never follow redirects and take relative paths only | `nabu/model/http.py` | `tests/test_model_layer.py` |
| Every model answer is schema-checked, with one repair attempt; values are clamped, never trusted (FR-3.5, AD-10) | `nabu/model/client.py` | `tests/test_model_layer.py` |
| The store is the only disk writer. It refuses any template or translation that contains a session value, also when punctuation or accents differ, and also inside slugs (AR-2, AR-7) | `nabu/store/` | `tests/test_store.py` |
| Store files are 0600 and folders 0700, written atomically (FR-11.7) | `nabu/store/paths.py` | `tests/test_store.py` |
| Session data lives only in memory and is released on close (AD-8) | `nabu/session.py` | `tests/test_store.py` |
| Logs show exception *types* only. No messages, no tracebacks (FR-11.5) | `nabu/hardening.py` | `tests/test_output_schema_and_logging.py` |
| Core dumps are off (POSIX) | `nabu/hardening.py` | — |
| Host and Origin checks, a per-run token sent only in a header, plus CSP, `no-store` and `no-referrer` (API-1, 3, 5, 6) | `nabu/server/app.py` | `tests/test_server.py` |
| The first browser to open the review window claims it (HttpOnly cookie); other programs and users get "already open", never the token. WebSockets are refused | `nabu/server/app.py` | `tests/test_server.py` |
| The UI turns off spell-check, autocomplete and translate (FR-6.18) and loads nothing remote | `ui/` | — |
| There is no CLI command that reads documents (FR-12.2) | `nabu/cli.py` | `tests/test_model_and_cli.py` |
| OCR models are always passed by path, so the OCR engine never downloads anything; it runs under the egress guard | `nabu/ocr/engine.py` | `tests/test_ocr.py` |
| `nabu langs pull` is the one command that uses the internet (AR-3 exception): pinned URLs, sha256 checked, refused inside any process that has the guard installed (the review server) | `nabu/ocr/packs.py`, `nabu/cli.py` | `tests/test_cli_m1.py` |
| File type by extension **and** content; unsupported, empty, encrypted, corrupt and mismatched files each get a named message (FR-2) | `nabu/router.py` | `tests/test_router.py` |
| Discovery never invents a value: a model value not found on the page as printed is marked "needs review"; a label with no value is kept empty (FR-4.5) | `nabu/pipeline.py`, `nabu/fields/grounding.py` | `tests/test_pipeline.py` |
| Names, IDs and numbers are never translated; a translation the model returns unchanged is "untranslated", never a guess (FR-9.6, 9.7) | `nabu/lang/translate.py` | `tests/test_translate.py` |
| Every value read is registered with the session, so the store refuses to write it anywhere (AR-7) | `nabu/pipeline.py` | `tests/test_pipeline.py` |

### Known residual risks (documented, not fixed)

- **Code outside Python's socket layer.** The egress guard covers the `socket.socket` class and asyncio's Windows Proactor only. A native extension opening its own sockets, a subprocess, or code using the C-level `_socket.socket` class directly would bypass it. Review every native dependency when you add it.
- **Windows crash dumps.** Windows Error Reporting may keep a minidump after a crash. Python has no per-process switch for this.
- **Browser extensions.** In a normal browser, extensions can read the review window. FRD Q21 decides whether to use a native window instead.
- **The no-values guard has blind spots.** It catches only values Nabu identified as field values in the current session. Identifying printed labels, such as a letterhead, are FRD Q22. A value rewritten in another format (a date stored as `2026-10-01` instead of `01.10.2026`) is not detected.
- **"Values never on disk" holds for Nabu's own process only.** The browser showing the review window can write what it shows to disk: session restore saves typed form text, and browser crash reports can hold page contents. The operating system can page memory to its swap or hibernation file. The model runtime is a separate program with its own logs. Nabu writes none of these and cannot prevent them.
- **`nabu langs pull` reaches the internet.** It downloads only the pinned pack files and checks their sha256 before installing, and it cannot run inside the review server's process. The download itself is visible to the network.
- **`doctor` runs `nvidia-smi`** when it exists, to read GPU memory. It is a local program with fixed arguments and a 2-second limit; nothing runs during reading.
- **The window cookie is not port-specific.** If the user opens, in the same browser, a page served by a hostile program on another local port, that program receives the window cookie and could open the review window. It needs a hostile local program and the user's click.

## Layout

```
src/nabu/
  cli.py            commands (FR-12); there is no read command
  config.py         config + loopback validation (DD-5, AR-3)
  netguard.py       run-time egress guard
  hardening.py      core dumps off, safe logging
  session.py        in-memory session (AD-8)
  doctor.py         machine report (FR-1.1)
  app.py            what the shortcut runs: open the window, start Nabu if needed (FR-1.11)
  install/          model bootstrap (§7.6): plan, pins, pinned fetcher, shortcut, sample
  store/            the only disk writer + no-values guard (AR-2, AR-7)
  model/            pluggable model layer (FR-10): client, runtimes, profiles, tiers, evaluate
  server/           review window API + UI host (10.2)
  schemas/          output JSON Schema (DD-3)
  pipeline.py       the reading flow (AR-1): route, read, OCR, discover, translate
  router.py         file type by extension and content (FR-2)
  extract/          PDF text layer, page rendering, office and text files (FR-3)
  ocr/              OCR engine, word/line/page types, language packs (AD-1)
  discovery/        fixed rules for digital files, model call for scans (FR-4)
  fields/           working result types, grounding on OCR words, value shapes (AD-2, FR-9.6)
  lang/             language detection, translation memory read path, translation (FR-9)
  templates/        linking, template read, template write (FR-5, FR-7)
  output/           output JSON (DD-3)
install/            install.ps1, install.sh, build_release.py (release folder), build_site.py (M5 page)
ui/                 Vite + TypeScript review UI; builds into src/nabu/server/ui_dist (demo mode: dist/site/demo)
site/               M5 product page (static HTML + CSS)
fixtures/           synthetic only, never real documents; demo/ is the M5 specimen licence
tests/              offline; tests/stub_ollama.py mimics the runtime
```

## Dependency rules

- **Reading stack.** It is the `read` extra (`uv sync --extra read`): 292 MB on Windows, against a 300 MB budget (NFR-2, owner decision 2026-10-13). OCR is `rapidocr` 3.10 (pinned minor: the adapter relies on its call flags and word boxes) with its bundled models. Korean needs `nabu langs pull ko` (13 MB). Measurements: `tasks/m0-ocr.md`.
- **Licences.** Check the licence of every new dependency. Do **not** add PyMuPDF/fitz, which is AGPL-3.0. Render PDFs with pypdfium2.
- **Model.** The model is a config value, never hard-coded (FR-10.2). The default family is **Qwen3.5** (Apache-2.0); the FRD's `qwen2.5vl:3b` is non-commercial only and is no longer recommended. The tier table is `nabu/model/tiers.py`.

## Models: plug and play

Any local vision model works. Switching is a config change; no code changes.

```bash
uv run nabu models list                 # installed models, the active one, the recommendation
uv run nabu models pull qwen3.5:4b      # download through Ollama (FR-10.5)
uv run nabu models use qwen3.5:4b       # make it active (writes config.json)
uv run nabu models use my-model --runtime openai_compat --endpoint http://127.0.0.1:8080
```

Two things can differ between models, and each has one place:

- **Runtime** (how Nabu talks to the model server): `ollama` or `openai_compat` (llama.cpp server, LM Studio, vLLM). A new runtime is one class in `nabu/model/` plus an entry in `RUNTIMES` (`nabu/model/runtime.py`). The endpoint must be on this machine.
- **Profile** (what differs between model families): box format, thinking on or off, structured output, image size. Built-in profiles are in `nabu/model/profiles.py`; a model with no profile gets `generic`, which works with any vision model. Add or override a profile in `config.json`:

```json
{"model": "brand-new-vlm:7b",
 "model_profiles": [{"name": "brand-new-vlm", "match": ["brand-new-vlm"], "coords": "grid_1000"}]}
```

Templates do not depend on the model: anchors come from OCR and printed labels, so switching models keeps everything Nabu has learned.

**Before switching the default, measure it.** Put synthetic page images and `<name>.expected.json` files in a folder, then run:

```bash
uv run python -m nabu.model.evaluate path/to/cases --model qwen3.5:4b
```

It reports JSON validity, label recall, value accuracy, seconds per page and which box format fits the model (`suggested_coords`). It prints metrics only, never document values.

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
