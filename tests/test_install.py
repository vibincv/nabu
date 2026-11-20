"""M4 installer (FR-1.2 to FR-1.12, §7.6, MH-2 to MH-6, FR-1.11, UX-2.14). Offline: the
runtime is the stub, downloads come from a loopback server, nothing is installed."""

import dataclasses
import hashlib
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from stub_ollama import StubOllama

from nabu.config import Config
from nabu.install import __main__ as installer
from nabu.install import fetch, shortcut
from nabu.install.pins import MODELS, Artefact, runtime_artefact
from nabu.install.plan import GB, Choices, Facts, make_plan, render
from nabu.lang.memory import TranslationMemory
from nabu.pipeline import Readers
from nabu.server.app import create_app
from nabu.server.documents import DocumentService
from nabu.store.paths import default_paths
from nabu.store.store import Store

ROOT = Path(__file__).resolve().parent.parent
NINE = "qwen3.5:9b"


def facts(**kw) -> Facts:
    base = dict(system="Windows", arch="AMD64", cpu_cores=8, ram_gb=31.7, vram_gb=8.0,
                disk_free_bytes=200 * GB, runtime_answers=True, runtime_program=None,
                models={NINE: MODELS[NINE].digest}, configured_model=NINE, ocr_present=True,
                ocr_langs=("ko",), pack_sizes_mb={"ko": 12.9}, shortcut=Path("Nabu.lnk"),
                shortcut_exists=True, model_store="~/.ollama/models",
                download_dir=Path("dl"))
    base.update(kw)
    return Facts(**base)


def kinds(plan) -> list[str]:
    return [s.kind for s in plan.steps]


# ---- plan (pure) --------------------------------------------------------------------------

def test_rerun_downloads_nothing():  # FR-1.2, FR-1.3, MH-3
    plan = make_plan(facts(), Choices())
    assert plan.model == NINE and plan.reuse_model and plan.runtime is None
    assert sum(s.download_bytes for s in plan.steps) == 0
    assert "consent" not in kinds(plan) and "lang-pack" not in kinds(plan)
    assert kinds(plan)[:2] == ["runtime", "model-reuse"]


def test_fresh_machine_plan_shows_sizes_and_asks():  # FR-1.4, MH-2, FR-1.6, FR-1.12
    f = facts(runtime_answers=False, models={}, configured_model=None, ocr_langs=(),
              shortcut_exists=False)
    plan = make_plan(f, Choices())
    assert plan.model == NINE and not plan.reuse_model
    assert kinds(plan)[:5] == ["consent", "runtime-download", "runtime-install", "runtime-health",
                               "model-pull"]
    consent = plan.steps[0].consent
    assert "6.6 GB on disk" in consent and "~/.ollama/models" in consent and "Free disk" in consent
    install = next(s for s in plan.steps if s.kind == "runtime-install")
    assert install.command[1:] == ["/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"]
    assert "lang-pack" in kinds(plan) and kinds(plan)[-1] == "sample"
    text = "\n".join(render(f, plan))
    assert "sha256" in text and "Add the Nabu shortcut" in text


def test_existing_runtime_not_running_is_started_not_reinstalled():  # FR-1.3
    plan = make_plan(facts(runtime_answers=False, runtime_program="C:/Ollama/ollama.exe",
                           models={}), Choices())
    assert "runtime-start" in kinds(plan) and "runtime-download" not in kinds(plan)


def test_declined_model_is_no_model_mode():  # FR-1.5
    plan = make_plan(facts(models={}), Choices(model=None))
    assert plan.model is None and "no-model" in kinds(plan)
    assert sum(s.download_bytes for s in plan.steps) == 0


def test_low_disk_refuses_download_and_shows_numbers():  # MH-4
    plan = make_plan(facts(runtime_answers=False, models={}, disk_free_bytes=5 * GB), Choices())
    assert plan.model is None and plan.runtime is None
    low = next(s for s in plan.steps if s.kind == "disk-low")
    assert "needs" in low.text and "5.0 GB free" in low.text
    assert not any(k.startswith("runtime") for k in kinds(plan))


def test_small_machine_gets_no_model_and_an_offer():  # tier table, MH-1
    plan = make_plan(facts(ram_gb=4.0, vram_gb=None, models={}), Choices())
    assert plan.model is None and any("qwen3.5:0.8b" in n for n in plan.notes)


def test_unpinned_model_is_not_pulled():  # FR-1.12
    plan = make_plan(facts(models={}), Choices(model="someone/else:7b"))
    assert plan.model is None and "model-unpinned" in kinds(plan)


def test_reused_model_with_other_digest_is_kept_and_reported():  # FR-1.3
    plan = make_plan(facts(models={NINE: "0" * 64}), Choices())
    assert plan.reuse_model and "digest differs" in plan.steps[1].text


def test_platform_without_pin_gives_manual_steps():
    plan = make_plan(facts(system="Windows", arch="ARM64", runtime_answers=False, models={}),
                     Choices())
    assert "runtime-manual" in kinds(plan) and plan.model is None
    assert runtime_artefact("Linux", "aarch64").key == "ollama-linux-arm64"


def test_render_is_deterministic():  # FR-1.8 acceptance: two dry runs print the same
    f = facts(runtime_answers=False, models={}, ocr_langs=())
    assert render(f, make_plan(f, Choices())) == render(f, make_plan(f, Choices()))


# ---- pinned download (FR-1.12) --------------------------------------------------------------

@pytest.fixture
def file_server():
    payload = b"pretend runtime installer" * 1000

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/OllamaSetup.exe", payload
    srv.shutdown()
    srv.server_close()


def test_fetch_checks_sha256(tmp_path, file_server):
    url, payload = file_server
    good = Artefact("x", url, hashlib.sha256(payload).hexdigest(), len(payload))
    dest = tmp_path / "OllamaSetup.exe"
    lines: list[str] = []
    assert fetch.fetch(good, dest, out=lines.append) == fetch.EXIT_OK
    assert dest.read_bytes() == payload and "checksum matches" in lines[-1]
    assert fetch.fetch(good, dest, out=lines.append) == fetch.EXIT_OK  # FR-1.2: no second download
    assert lines[-1].endswith("already downloaded and checked")

    bad = dataclasses.replace(good, sha256="0" * 64)
    other = tmp_path / "other.exe"
    assert fetch.fetch(bad, other, out=lines.append) == fetch.EXIT_MISMATCH
    assert not other.exists() and not (tmp_path / "other.exe.part").exists()
    assert "OllamaSetup.exe does not match the checksum" in lines[-1]


def test_fetch_takes_a_pin_key_never_a_url(capsys):
    assert fetch.main(["https://example.com/evil.exe", "x"]) == fetch.EXIT_FAIL


def test_pulled_model_with_wrong_digest_is_removed():  # FR-1.12
    with StubOllama(models=[NINE]) as stub:
        cfg = Config(model_endpoint=stub.url)
        stub.digests[NINE] = "f" * 64
        assert installer.pull_model(cfg, NINE) is False
        assert ("DELETE", "/api/delete", {"model": NINE}) in stub.calls and NINE not in stub.models

        stub.models.append(NINE)
        stub.digests[NINE] = MODELS[NINE].digest
        assert installer.pull_model(cfg, NINE) is True


# ---- whole installer, dry run (FR-1.8) ------------------------------------------------------

def tree(p: Path) -> list[tuple[str, int]]:
    return sorted((str(f.relative_to(p)), f.stat().st_size) for f in p.rglob("*")) if p.exists() else []


def test_dry_run_changes_nothing_and_repeats_exactly(nabu_home, tmp_path, monkeypatch, capsys):
    with StubOllama(models=[NINE]) as stub:
        stub.digests[NINE] = MODELS[NINE].digest
        monkeypatch.setenv("NABU_MODEL_ENDPOINT", stub.url)
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        before = tree(tmp_path)
        assert installer.main(["--dry-run"]) == 0
        first = capsys.readouterr().out
        assert installer.main(["--dry-run"]) == 0
        second = capsys.readouterr().out
    assert first == second and "Dry run: nothing was changed." in first
    assert "Model qwen3.5:9b is already installed: no download." in first
    assert tree(tmp_path) == before and not nabu_home.exists()
    assert [c for c in stub.calls if c[0] != "GET"] == []  # no pull, no delete, no chat


def test_unanswered_question_ends_its_line_and_says_no(monkeypatch, capsys):
    def no_input(prompt):
        print(prompt, end="")  # noqa: T201 - input() writes the prompt before it hits EOF
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    assert installer.ask("Download it?", yes=False) is False
    assert capsys.readouterr().out == "? Download it? [y/N] no (no answer could be read)\n"


def test_declined_lang_pack_is_reported_as_skipped(nabu_home, monkeypatch, capsys):
    pytest.importorskip("pypdfium2")
    plan = make_plan(facts(ocr_langs=(), models={}), Choices(model=None))
    assert "ko" in plan.lang_packs
    monkeypatch.setattr(installer, "ask", lambda q, yes: False)
    pulled = []
    monkeypatch.setattr(installer, "child", lambda a: pulled.append(a) or 0)
    store = Store(default_paths())
    installer.execute(plan, facts(ocr_langs=(), models={}), Config(), store, False, None)
    out = capsys.readouterr().out
    assert pulled == []
    assert "Skipped: the ko OCR pack. Add it later with: nabu langs pull ko\n" in out


def test_sample_is_bundled_and_reads_without_a_model(nabu_home):  # FR-1.10
    pytest.importorskip("pypdfium2")
    assert installer.sample_bytes().startswith(b"%PDF")
    assert installer.sample_read(Config(), Store(default_paths())) is True


# ---- shortcut (FR-1.11) ---------------------------------------------------------------------

def test_linux_shortcut_runs_nabu_app(tmp_path):
    path = tmp_path / "applications" / "nabu.desktop"
    shortcut.create("Linux", path)
    text = path.read_text(encoding="utf-8")
    assert "Name=Nabu" in text and '"-m" "nabu.app"' in text and "Terminal=false" in text


def test_windows_shortcut_command_quotes_paths():
    cmd = shortcut.windows_command(Path("C:/Users/O'Neil/Nabu.lnk"), ["C:/py/pythonw.exe", "-m",
                                                                      "nabu.app"])
    assert cmd[:3] == ["powershell", "-NoProfile", "-NonInteractive"]
    assert "'C:\\Users\\O''Neil\\Nabu.lnk'" in cmd[-1] or "'C:/Users/O''Neil/Nabu.lnk'" in cmd[-1]
    assert "$s.Arguments = '-m nabu.app'" in cmd[-1]


def _answering(status: str, body: bytes):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(int(status))
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_shortcut_finds_a_running_nabu_only():
    from nabu.app import running_port

    nabu = _answering("401", b'{"error":"missing or wrong token"}')
    other = _answering("200", b'{"ok":true}')
    try:
        assert running_port(nabu.server_address[1], tries=1) == nabu.server_address[1]
        assert running_port(other.server_address[1], tries=1) is None
    finally:
        for s in (nabu, other):
            s.shutdown()
            s.server_close()


# ---- first run (UX-2.14) --------------------------------------------------------------------

def test_first_run_shown_once(nabu_home, tmp_path):
    store = Store(default_paths())
    store.save_config({"model": NINE, "model_seconds_per_page": 4.2})
    dist = tmp_path / "ui_dist"
    dist.mkdir()
    (dist / "index.html").write_text('<html><head><meta name="nabu-token" content=""></head></html>')
    cfg = Config(model=NINE, model_seconds_per_page=4.2)
    service = DocumentService(cfg, lambda: Readers(None, None, TranslationMemory({})), store)
    app, _ = create_app(8765, token="t" * 43, ui_dist=dist, documents=service)
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    c.get("/")
    assert c.get("/api/first-run").status_code == 401  # token required, like every /api call
    c.headers["x-nabu-token"] = "t" * 43
    info = c.get("/api/first-run").json()
    assert info == {"show": True, "model": NINE, "model_size_gb": 6.6, "seconds_per_page": 4.2,
                    "store": str(nabu_home)}
    assert c.post("/api/first-run").json() == {"ok": True}
    assert c.get("/api/first-run").json()["show"] is False
    assert store.config_data()["first_run_done"] is True and store.config_data()["model"] == NINE


# ---- install scripts, dry run ---------------------------------------------------------------

def fake_release(d: Path) -> Path:
    d.mkdir()
    (d / "nabu-0.1.0.dev0-py3-none-any.whl").write_bytes(b"wheel")
    (d / "requirements.txt").write_text("x==1 --hash=sha256:00\n")
    (d / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256((d / n).read_bytes()).hexdigest()}  {n}\n"
        for n in ("nabu-0.1.0.dev0-py3-none-any.whl", "requirements.txt")), newline="\n")
    for s in ("install.ps1", "install.sh"):
        shutil.copy2(ROOT / "install" / s, d / s)
    return d


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_install_sh_dry_run(tmp_path):  # FR-1.8 acceptance, on a faked Linux x86_64
    rel = fake_release(tmp_path / "release")
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "uname").write_text('#!/bin/sh\n[ "$1" = -s ] && echo Linux || echo x86_64\n',
                                newline="\n")
    (shim / "uname").chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(home / "data")}
    # The shim goes on PATH inside the shell, not in env: on Windows, `sh` found from PowerShell
    # is Git's launcher (Git\bin\sh.exe), which puts its own /usr/bin ahead of the inherited
    # PATH, so the real uname won and the test failed there. "$PWD/shim" is in the shell's own
    # path form on every platform.
    cmd = ["sh", "-c", 'PATH="$PWD/shim:$PATH" exec sh "$0" --dry-run', str(rel / "install.sh")]

    def dry_run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, env=env, cwd=tmp_path, capture_output=True, text=True,
                              timeout=60)

    runs = [dry_run() for _ in range(2)]
    assert [r.returncode for r in runs] == [0, 0], runs[0].stderr
    assert runs[0].stdout == runs[1].stdout
    out = runs[0].stdout
    assert "Release files checked against SHA256SUMS." in out
    assert "uv-x86_64-unknown-linux-gnu.tar.gz" in out and "--require-hashes" in out
    assert "Dry run: nothing was changed." in out
    assert list(home.rglob("*")) == []

    (rel / "requirements.txt").write_text("tampered\n")
    bad = dry_run()
    assert bad.returncode == 1 and "requirements.txt does not match its checksum" in bad.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
def test_install_ps1_dry_run(tmp_path):
    rel = fake_release(tmp_path / "release")
    local = tmp_path / "local"
    local.mkdir()
    env = {**os.environ, "LOCALAPPDATA": str(local)}
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
           str(rel / "install.ps1"), "-DryRun"]
    runs = [subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
            for _ in range(2)]
    assert [r.returncode for r in runs] == [0, 0], runs[0].stdout + runs[0].stderr
    assert runs[0].stdout == runs[1].stdout
    assert "uv-x86_64-pc-windows-msvc.zip" in runs[0].stdout
    assert "Dry run: nothing was changed." in runs[0].stdout
    assert list(local.rglob("*")) == []


def test_shortcut_start_survives_missing_console(monkeypatch):  # pythonw: no stdout/stderr
    from nabu import app

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    app._windowless_stdio()
    assert sys.stdout is not None and sys.stderr is not None
    import uvicorn

    uvicorn.Config(lambda *a: None, log_level="warning").configure_logging()  # failed before


def test_runtime_download_stays_in_a_user_only_folder(nabu_home, monkeypatch, tmp_path):
    # Security review: never the shared temp dir; re-checked before it runs; removed after.
    f = installer.detect(Config(model_endpoint="http://127.0.0.1:9"), default_paths())
    assert f.download_dir == default_paths().data_dir / "downloads"

    art = Artefact("ollama-windows", "https://x/OllamaSetup.exe", "a" * 64, 1)
    plan = make_plan(facts(runtime_answers=False, models={}), Choices())
    plan.runtime = art
    swapped = dataclasses.replace(facts(), download_dir=tmp_path / "downloads")

    def fake_child(args):  # download "succeeds" but the file differs from the pin
        (tmp_path / "downloads" / "OllamaSetup.exe").write_bytes(b"swapped")
        return 0

    ran = []
    monkeypatch.setattr(installer, "child", fake_child)
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: ran.append(a))
    assert installer.install_runtime(plan, swapped, Config()) is False
    assert ran == [] and not (tmp_path / "downloads").exists()


# ---- beta start scripts (2026-11-12) ---------------------------------------------------------

def test_macos_runtime_unpacks_into_nabus_folder_and_is_found_there(tmp_path, monkeypatch):
    # The pinned ollama-darwin.tgz is a bare `ollama` binary plus libraries (no Ollama.app), so
    # it was unpacked loose into ~/Applications and then looked for as Ollama.app: never found.
    from nabu.install.plan import mac_runtime_dir, runtime_install_command

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)
    target = mac_runtime_dir()
    assert target == tmp_path / "Library" / "Application Support" / "Nabu App" / "ollama"
    assert runtime_install_command("Darwin", Path("ollama-darwin.tgz"))[-2:] == ["-C", str(target)]
    if not (Path("/Applications") / "Ollama.app").exists():
        assert installer.runtime_program("Darwin") is None
    target.mkdir(parents=True)
    (target / "ollama").write_bytes(b"")
    assert installer.runtime_program("Darwin") == str(target / "ollama")


def test_quick_check_ready_missing_model_and_no_model_mode(monkeypatch, capsys):
    assert installer.quick_check(Config(model=None)) == installer.EXIT_OK
    with StubOllama(models=[NINE]) as stub:
        assert installer.quick_check(Config(model=NINE, model_endpoint=stub.url)) == installer.EXIT_OK
        assert installer.quick_check(Config(model="qwen3.5:4b", model_endpoint=stub.url)) \
            == installer.EXIT_SETUP
    monkeypatch.setattr(installer, "runtime_program", lambda system: None)  # no Ollama at all
    assert installer.quick_check(Config(model=NINE, model_endpoint="http://127.0.0.1:9")) \
        == installer.EXIT_SETUP
    out = capsys.readouterr().out
    assert "no-model mode" in out and "qwen3.5:4b is not installed" in out
    assert "does not answer" in out


def test_quick_check_starts_a_stopped_runtime(monkeypatch):
    started = []
    monkeypatch.setattr(installer, "runtime_program", lambda system: "ollama")
    monkeypatch.setattr(installer, "start_runtime", started.append)
    with StubOllama(models=[NINE]) as stub:
        cfg = Config(model=NINE, model_endpoint=stub.url)
        # Stopped until start_runtime ran, then answering (the stub serves the model list).
        monkeypatch.setattr(installer, "wait_for_runtime", lambda c, s=60.0: bool(started))
        assert installer.quick_check(cfg) == installer.EXIT_OK
    assert started == ["ollama"]


def test_check_flag_runs_only_the_quick_check(nabu_home, monkeypatch):
    seen = []
    monkeypatch.setattr(installer, "quick_check", lambda cfg: seen.append(cfg.model) or 3)
    monkeypatch.setattr(installer, "detect", lambda *a: pytest.fail("full install ran"))
    assert installer.main(["--check"]) == installer.EXIT_SETUP and seen == [None]


@pytest.mark.parametrize("model, expect", [(NINE, [NINE]), (None, [])])
def test_shortcut_starts_a_stopped_runtime_before_serving(nabu_home, monkeypatch, model, expect):
    import nabu.cli
    from nabu import app

    Store(default_paths()).save_config({"model": model})
    started = []
    monkeypatch.setattr(app, "running_port", lambda port: None)
    monkeypatch.setattr(installer, "ensure_runtime", lambda cfg, s: started.append(cfg.model))
    monkeypatch.setattr(nabu.cli, "main", lambda argv: 0)
    assert app.main() == 0 and started == expect


def test_start_scripts_parse():
    if shutil.which("sh"):
        r = subprocess.run(["sh", "-n", str(ROOT / "start-nabu.sh")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert b"\r\n" not in (ROOT / "start-nabu.sh").read_bytes()
    if sys.platform == "win32":
        script = ("$e = $null; [System.Management.Automation.Language.Parser]::ParseFile("
                  f"'{ROOT / 'start-nabu.ps1'}', [ref]$null, [ref]$e) | Out-Null; $e.Count")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, timeout=60)
        assert r.stdout.strip() == "0", r.stdout + r.stderr
