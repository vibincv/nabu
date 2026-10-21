"""Model bootstrap (§7.6, FR-1): `python -m nabu.install [--dry-run] [--yes] [--model NAME|none]`.

Started by install.ps1 / install.sh once Nabu itself is installed, and safe to run again: a
second run detects everything and downloads nothing (FR-1.2).

This process keeps the egress guard. The only internet downloads (the pinned runtime and OCR
packs) run in child processes that take a pinned key, not a URL. Model weights are downloaded by
the runtime itself; their digest is checked here afterwards (FR-1.12).
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

from nabu import netguard

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def _out(s: str = "") -> None:
    print(s, flush=True)  # noqa: T201


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m nabu.install", description="Set up the local model runtime, a model, "
        "OCR language packs and the Nabu shortcut. Asks before every download.",
        epilog="example: python -m nabu.install --dry-run")
    p.add_argument("--dry-run", action="store_true",
                   help="print every detection and every command, change nothing (FR-1.8)")
    p.add_argument("--yes", action="store_true", help="answer yes to every download question")
    p.add_argument("--model", default="auto",
                   help="model to use instead of the recommended one, or 'none' for no-model mode")
    p.add_argument("--langs", default=None,
                   help="OCR packs to offer, comma-separated (default: en,ko); 'none' for none")
    p.add_argument("--no-shortcut", action="store_true", help="do not add the Nabu shortcut")
    return p.parse_args(argv)


def model_store() -> str:
    return os.environ.get("OLLAMA_MODELS") or str(Path.home() / ".ollama" / "models")


def runtime_program(system: str) -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = {
        "Windows": Path(os.environ.get("LOCALAPPDATA") or "") / "Programs" / "Ollama" / "ollama.exe",
        "Darwin": Path.home() / "Applications" / "Ollama.app" / "Contents" / "Resources" / "ollama",
        "Linux": Path.home() / ".local" / "bin" / "ollama",
    }
    c = candidates.get(system)
    return str(c) if c and c.is_file() else None


def detect(cfg, paths):  # type: ignore[no-untyped-def]
    from nabu.doctor import gpus, total_ram_gb
    from nabu.errors import ModelUnavailable
    from nabu.install import shortcut
    from nabu.install.plan import Facts
    from nabu.model.ollama import OllamaRuntime
    from nabu.ocr import engine, packs

    system = platform.system()
    rt = OllamaRuntime(cfg, 3.0)
    try:
        answers = rt.available()
        try:
            models = rt.digests() if answers else {}
        except ModelUnavailable:
            models = {}
    finally:
        rt.close()
    disk_root = paths.data_dir if paths.data_dir.exists() else Path(paths.data_dir.anchor or "/")
    where = shortcut.location(system)
    return Facts(
        system=system, arch=platform.machine(), cpu_cores=os.cpu_count(), ram_gb=total_ram_gb(),
        vram_gb=max((g["vram_gb"] for g in gpus()), default=None),
        disk_free_bytes=shutil.disk_usage(disk_root).free,
        runtime_answers=answers, runtime_program=None if answers else runtime_program(system),
        models=models, configured_model=cfg.model, ocr_present=engine.available(),
        ocr_langs=tuple(sorted(packs.installed(paths.ocr_langs_dir))),
        pack_sizes_mb={k: p.size_mb for k, p in packs.PACKS.items()},
        shortcut=where, shortcut_exists=bool(where and where.exists()),
        model_store=model_store(), download_dir=paths.data_dir / "downloads")


def ask(question: str, yes: bool) -> bool:
    if yes:
        _out(f"? {question} yes (--yes)")
        return True
    try:
        return input(f"? {question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def show_command(cmd: list[str]) -> None:
    _out("  $ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))


def child(args: list[str]) -> int:
    """A Nabu child process that may use the internet (pinned downloads only)."""
    return subprocess.run([sys.executable, "-m", *args], check=False).returncode  # noqa: S603


def wait_for_runtime(cfg, seconds: float = 60.0) -> bool:  # type: ignore[no-untyped-def]
    from nabu.model.ollama import OllamaRuntime

    rt = OllamaRuntime(cfg, 3.0)
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if rt.available():
                return True
            time.sleep(1.0)
        return False
    finally:
        rt.close()


def start_runtime(program: str) -> None:
    show_command([program, "serve"])
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    subprocess.Popen([program, "serve"], stdin=subprocess.DEVNULL,  # noqa: S603
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
                     start_new_session=sys.platform != "win32")


MANUAL = ("Install Ollama yourself from https://ollama.com/download, start it, then run this "
          "installer again. Nabu works in no-model mode meanwhile.")


def install_runtime(plan, facts, cfg) -> bool:  # type: ignore[no-untyped-def]
    from nabu.install.fetch import sha256_file
    from nabu.install.plan import runtime_install_command
    from nabu.store.paths import secure_mkdir

    art = plan.runtime
    folder: Path = facts.download_dir
    # A user-only folder in Nabu's own data dir, never the shared temp dir: another local user
    # must not be able to plant or swap the file between the checksum and running it.
    if folder.is_symlink():
        _out(f"{folder} is a symbolic link; remove it and run the installer again.")
        return False
    secure_mkdir(folder)
    dest = folder / art.url.rsplit("/", 1)[-1]
    try:
        if child(["nabu.install.fetch", art.key, str(dest)]) != 0:
            return False
        # Checked again here, in the process that runs it, right before running it.
        if dest.is_symlink() or sha256_file(dest) != art.sha256:
            _out(f"{dest.name} changed after download; nothing was installed.")
            return False
        cmd = runtime_install_command(facts.system, dest)
        if facts.system == "Darwin":
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        _out("Installing Ollama:")
        show_command(cmd)
        if subprocess.run(cmd, check=False).returncode != 0:  # noqa: S603
            _out("The Ollama installer failed. " + MANUAL)
            return False
    finally:
        dest.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
    if not wait_for_runtime(cfg, 20.0):
        program = runtime_program(facts.system)
        if program:
            start_runtime(program)
    if not wait_for_runtime(cfg, 60.0):
        _out("Ollama was installed but does not answer at " + cfg.model_endpoint + ". " + MANUAL)
        return False
    _out("Ollama answers.")
    return True


def pull_model(cfg, name: str) -> bool:  # type: ignore[no-untyped-def]
    """Pull by tag, then check the digest against the pin (FR-1.12)."""
    from nabu.install.pins import MODELS
    from nabu.model.ollama import OllamaRuntime
    from nabu.model.runtime import same_model

    rt = OllamaRuntime(cfg, 30.0)
    try:
        last = ""
        for p in rt.pull(name):
            pct = f" {p.completed * 100 // p.total}%" if p.total and p.completed else ""
            line = f"  {p.status}{pct}"
            if line != last and (not pct or pct.endswith("0%")):
                _out(line)
            last = line
        got = next((d for m, d in rt.digests().items() if same_model(m, name)), None)
        if got != MODELS[name].digest:
            rt.delete(name)
            _out(f"{name} does not match the digest shipped with Nabu; it was removed. "
                 "Nothing else was changed.")
            return False
        _out(f"{name}: downloaded, digest matches.")
        return True
    finally:
        rt.close()


def check_model(cfg) -> float | None:  # type: ignore[no-untyped-def]
    """One timed page through the model on the bundled sample (FR-1.7 'accepts an image', MH-6).
    Returns seconds, or None if the model could not read the image."""
    from nabu.errors import NabuError
    from nabu.extract.raster import open_pdf, render_pdf_page
    from nabu.model.client import ModelClient

    page = render_pdf_page(open_pdf(sample_bytes(), "sample.pdf"), 0, cfg.dpi, "sample.pdf")
    client = ModelClient(cfg)
    try:
        t0 = time.monotonic()
        client.discover_page(page, "")
        return time.monotonic() - t0
    except NabuError as e:
        _out(f"The model did not read the sample page: {e.message}")
        return None
    finally:
        client.close()


def sample_bytes() -> bytes:
    return resources.files("nabu.install").joinpath("sample.pdf").read_bytes()


def sample_read(cfg, store) -> bool:  # type: ignore[no-untyped-def]
    """FR-1.10. The sample is synthetic, so printing its values is fine; nothing is written."""
    from nabu import pipeline
    from nabu.errors import NabuError
    from nabu.router import Upload
    from nabu.server.run import readers_factory

    session = store.new_session()
    try:
        result = pipeline.run([Upload("sample.pdf", sample_bytes())], cfg, session,
                              readers_factory(cfg, store)())
    except NabuError as e:
        _out(f"The test read failed: {e.message}")
        return False
    finally:
        store.end_session(session)
    _out(f"Test read of the bundled sample: {len(result.fields)} fields")
    for f in result.fields:
        _out(f"  {f.name}: {f.value or '(not found)'}")
    return bool(result.fields)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse(argv)
    except SystemExit as e:
        return EXIT_OK if e.code == 0 else EXIT_USAGE
    netguard.install()
    from nabu.config import load_config
    from nabu.errors import NabuError
    from nabu.install import shortcut
    from nabu.install.plan import Choices, make_plan, render
    from nabu.store.paths import default_paths
    from nabu.store.store import Store

    paths = default_paths()
    try:
        cfg = load_config(paths.config_file)
        choices = Choices(
            model=None if args.model == "none" else args.model,
            langs=None if args.langs is None else tuple(
                x for x in args.langs.split(",") if x and args.langs != "none"),
            shortcut=not args.no_shortcut)
        facts = detect(cfg, paths)
        plan = make_plan(facts, choices)
        for line in render(facts, plan):
            _out(line)
        if args.dry_run:
            _out("")
            _out("Dry run: nothing was changed.")
            return EXIT_OK
        _out("")
        return execute(plan, facts, cfg, Store(paths), args.yes, shortcut)
    except NabuError as e:
        _out(f"nabu install: {e.message}")
        return EXIT_FAIL
    except KeyboardInterrupt:
        _out("Stopped. Run the installer again to finish; finished steps are not repeated.")
        return EXIT_FAIL


def execute(plan, facts, cfg, store, yes: bool, shortcut) -> int:  # type: ignore[no-untyped-def]
    model = plan.model
    for step in plan.steps:
        if step.kind == "consent" and not ask(step.consent, yes):
            _out("Download declined: installing in no-model mode (FR-1.5).")
            model = None
            plan.runtime = None
    ok = True
    if model is not None:
        if plan.runtime is not None:
            if not install_runtime(plan, facts, cfg):
                model, ok = None, False
        elif not facts.runtime_answers and facts.runtime_program:
            start_runtime(facts.runtime_program)
            if not wait_for_runtime(cfg):
                _out("Ollama does not answer. " + MANUAL)
                model, ok = None, False
        if model is not None and not plan.reuse_model and not pull_model(cfg, model):
            model, ok = None, False

    for lang in plan.lang_packs:
        step = next(s for s in plan.steps if s.kind == "lang-pack" and s.command[-1] == lang)
        if ask(step.consent, yes):
            show_command(step.command)
            if child(["nabu", "langs", "pull", lang]) != 0:
                ok = False

    data = store.config_data()
    if data.get("model") != model:
        data["model_seconds_per_page"] = None
    data["model"] = model
    from nabu.ocr import packs

    data["ocr_languages"] = sorted({"en", *packs.installed(store.paths.ocr_langs_dir)})
    store.save_config(data)
    from nabu.config import load_config

    cfg = load_config(store.paths.config_file)
    _out(f"Config written: {store.paths.config_file} (model: {model or 'none, no-model mode'})")

    if model is not None:
        secs = check_model(cfg)
        if secs is None:
            ok = False
        else:
            _out(f"{model} read the sample page in {secs:.0f} s"
                 + ("" if facts.vram_gb else " on CPU (MH-6)") + ".")
            data["model_seconds_per_page"] = round(secs, 1)
            store.save_config(data)

    if any(s.kind == "shortcut" for s in plan.steps) and facts.shortcut is not None:
        if facts.shortcut_exists:
            _out(f"Shortcut already in place: {facts.shortcut}")
        else:
            try:
                shortcut.create(facts.system, facts.shortcut)
                _out(f"Shortcut added: {facts.shortcut}")
            except (OSError, subprocess.CalledProcessError):
                _out("Could not add the shortcut; start Nabu with: nabu serve")
                ok = False

    if not sample_read(cfg, store):
        ok = False
    _out("")
    _out("Nabu is installed. Open it from the Nabu shortcut." if ok else
         "Nabu is installed, with the problems listed above. Run the installer again after "
         "fixing them; finished steps are not repeated.")
    return EXIT_OK if ok else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
