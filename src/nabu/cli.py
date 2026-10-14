"""Command-line interface (FR-12). There is deliberately no command that reads documents (FR-12.2).

Exit codes: 0 success, 1 failure, 2 usage error (FR-12.3).
"""

from __future__ import annotations

import argparse
import json
import sys

from nabu import __version__, netguard
from nabu.errors import NabuError

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def _out(args: argparse.Namespace, text: str) -> None:
    if not getattr(args, "quiet", False):
        print(text)  # noqa: T201


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nabu",
        description="Nabu: read documents privately on this machine. Everyday use is the review "
                    "window (nabu serve); documents are never read from the command line.",
        epilog="Exit codes: 0 success, 1 failure, 2 usage error.",
    )
    p.add_argument("--quiet", action="store_true", help="print nothing on success")
    sub = p.add_subparsers(dest="cmd", required=True)

    def model_flags(sp: argparse.ArgumentParser) -> None:  # FR-10.1: flags beat env and config
        sp.add_argument("--model", default=None, help="local model name, e.g. qwen3.5:4b")
        sp.add_argument("--model-endpoint", default=None, help="must be on this machine")

    d = sub.add_parser("doctor", help="report OS, hardware and model runtime",
                       epilog="example: nabu doctor --json")
    d.add_argument("--json", action="store_true")
    model_flags(d)

    s = sub.add_parser("serve", help="open the review window on this machine",
                       epilog="example: nabu serve --port 8765")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--verbose", action="store_true")
    model_flags(s)

    m = sub.add_parser("models", help="list, choose or download local models",
                       epilog="example: nabu models use qwen3.5:4b")
    msub = m.add_subparsers(dest="mcmd", required=True)
    msub.add_parser("list", help="installed models, the active one and the recommendation",
                    epilog="example: nabu models list")
    u = msub.add_parser("use", help="make a model the active one",
                        epilog="example: nabu models use qwen3.5:4b --runtime ollama")
    u.add_argument("name")
    u.add_argument("--runtime", choices=["ollama", "openai_compat"], default=None)
    u.add_argument("--profile", default=None, help='profile name, or "auto" (default)')
    u.add_argument("--endpoint", default=None, help="runtime address; must be on this machine")
    pl = msub.add_parser("pull", help="download a model through the local runtime (FR-10.5)",
                         epilog="example: nabu models pull qwen3.5:4b")
    pl.add_argument("name", nargs="?", default=None,
                    help="default: the active model, else the recommended one")

    t = sub.add_parser("templates", help="list, show, delete, history",
                       epilog="example: nabu templates list")
    tsub = t.add_subparsers(dest="tcmd", required=True)
    tsub.add_parser("list")
    for name in ("show", "delete", "history"):
        tsub.add_parser(name).add_argument("template_id")

    f = sub.add_parser("forget", help="delete learned data and report what was removed",
                       epilog="example: nabu forget --all")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--templates", action="store_const", dest="scope", const="templates")
    g.add_argument("--translations", action="store_const", dest="scope", const="translations")
    g.add_argument("--all", action="store_const", dest="scope", const="all")

    tr = sub.add_parser("translations", help="list or delete remembered translations",
                        epilog="example: nabu translations list")
    trsub = tr.add_subparsers(dest="trcmd", required=True)
    trsub.add_parser("list", epilog="example: nabu translations list")
    trsub.add_parser("delete", epilog="example: nabu translations delete t1").add_argument("entry_id")

    la = sub.add_parser("langs", help="list or download OCR language packs",
                        epilog="example: nabu langs pull ko")
    lasub = la.add_subparsers(dest="lcmd", required=True)
    lasub.add_parser("list", help="languages OCR reads now, and packs you can add",
                     epilog="example: nabu langs list")
    lp = lasub.add_parser("pull", help="download a pack (internet; pinned file, checksum checked)",
                          epilog="example: nabu langs pull ko")
    lp.add_argument("lang", help="ISO 639-1 code, e.g. ko")

    sub.add_parser("version", help="print the version", epilog="example: nabu version")
    return p


def _models(args: argparse.Namespace, cfg, store) -> None:  # type: ignore[no-untyped-def]
    from nabu.doctor import total_ram_gb
    from nabu.model import manage

    if args.mcmd == "list":
        info = manage.listing(cfg, total_ram_gb())
        rec = info.recommended
        if not info.runtime_present:
            _out(args, f"runtime ({info.runtime}) is not answering at {cfg.model_endpoint}")
        for name in info.installed:
            mark = "*" if info.active and manage.same_model(name, info.active) else " "
            _out(args, f"{mark} {name}")
        _out(args, f"active: {info.active or 'none (no-model mode)'}"
                   + (f"  [profile: {info.active_profile}]" if info.active_profile else ""))
        _out(args, f"recommended for this machine ({rec.hardware}): {rec.model or 'none'}"
                   + (f", about {rec.download_gb} GB" if rec.download_gb else "")
                   + (f"; also offered: {rec.offered}" if rec.offered else ""))
    elif args.mcmd == "use":
        new_cfg, installed = manage.use(store, args.name, args.runtime, args.profile, args.endpoint)
        _out(args, f"active model: {new_cfg.model} ({new_cfg.model_runtime})")
        if installed is None:
            _out(args, "the runtime is not answering, so the model could not be checked")
        elif not installed:
            _out(args, f"not installed yet. Run: nabu models pull {new_cfg.model}")
    elif args.mcmd == "pull":
        name = args.name or cfg.model or manage.recommend(total_ram_gb()).model
        if not name:
            raise NabuError("this machine is below the minimum for a model; name one to pull")
        last = ""
        for p in manage.pull(cfg, name):
            pct = f" {100 * p.completed // p.total}%" if p.total and p.completed is not None else ""
            line = f"{p.status}{pct}"
            if line != last:
                _out(args, line)
                last = line
        _out(args, f"{name} is ready. Make it active with: nabu models use {name}")


def _langs(args: argparse.Namespace, store) -> None:  # type: ignore[no-untyped-def]
    from nabu.ocr import engine, packs

    if args.lcmd == "list":
        have = packs.installed(store.paths.ocr_langs_dir)
        if not engine.available():
            _out(args, "OCR engine: not installed (run: uv sync --extra read)")
        _out(args, "built in: " + ", ".join(packs.BUILTIN_LANGS))
        for lang, pack in sorted(packs.PACKS.items()):
            state = "installed" if lang in have else f"not installed, {pack.size_mb} MB"
            _out(args, f"{lang}  {pack.language}: {state}")
    elif args.lcmd == "pull":
        pack = packs.PACKS.get(args.lang)
        if pack is None:
            raise NabuError(f"no OCR language pack for '{args.lang}'. "
                            f"Available: {', '.join(sorted(packs.PACKS))}")
        _out(args, f"downloading the {pack.language} OCR pack ({pack.size_mb} MB)")
        d = store.install_ocr_pack(args.lang, packs.download(args.lang))
        _out(args, f"{pack.language} OCR pack installed in {d}")


def _translations(args: argparse.Namespace, store) -> None:  # type: ignore[no-untyped-def]
    if args.trcmd == "list":
        for e in store.translations()["entries"]:
            _out(args, f'{e.get("id", "?")}  [{e.get("lang", "?")}] {e.get("term", "")} -> '
                       f'{e.get("english", "")}' + (f'  ({e["scope"]})' if e.get("scope") else ""))
    elif args.trcmd == "delete":
        if not store.delete_translation(args.entry_id):
            raise NabuError(f"no remembered translation with id {args.entry_id}")
        _out(args, f"removed {args.entry_id}")


def _needs_internet(args: argparse.Namespace) -> bool:
    """`langs pull` is the one command allowed off this machine (AR-3 exception, owner decision
    2026-10-13). It runs in its own process, which never reads a document."""
    return args.cmd == "langs" and args.lcmd == "pull"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)  # opens no socket
    except SystemExit as e:
        return EXIT_OK if e.code == 0 else EXIT_USAGE
    # Order matters: the egress guard goes in before anything else can open a socket.
    if not _needs_internet(args):
        netguard.install()
    from nabu.hardening import configure_logging, disable_core_dumps

    disable_core_dumps()

    from nabu.config import load_config
    from nabu.store.paths import default_paths
    from nabu.store.store import Store

    paths = default_paths()
    try:
        configure_logging(paths.logs_dir if args.cmd == "serve" else None,
                          verbose=getattr(args, "verbose", False))
        cfg = load_config(paths.config_file, {
            "ui_port": getattr(args, "port", None),
            "model": getattr(args, "model", None),
            "model_endpoint": getattr(args, "model_endpoint", None),
        })
        store = Store(paths)

        if args.cmd == "version":
            _out(args, __version__)
        elif args.cmd == "doctor":
            from nabu.doctor import report

            r = report(cfg, paths)
            if args.json:
                _out(args, json.dumps(r, indent=2))
            else:
                _out(args, "\n".join(f"{k}: {v}" for k, v in r.items()))
        elif args.cmd == "serve":
            from nabu.server.run import serve

            serve(cfg, paths, open_browser=not args.no_browser)
        elif args.cmd == "templates":
            if args.tcmd == "list":
                for t in store.templates():
                    h = t["template"]
                    fmt = (h.get("format") or {}).get("name", "?")
                    _out(args, f'{h.get("id", "?")}  {h.get("document_type", "?")} · '
                               f'{h.get("region") or "No region"} · {fmt}  v{h["version"]}')
            elif args.tcmd == "show":
                path = store.find_template(args.template_id)
                if path is None:
                    raise NabuError(f"no template with id {args.template_id}")
                _out(args, path.read_text(encoding="utf-8"))
            elif args.tcmd == "delete":
                for r in store.delete_template(args.template_id):
                    _out(args, f"removed {r}")
            elif args.tcmd == "history":
                _out(args, " ".join(f"v{v}" for v in store.history(args.template_id)))
        elif args.cmd == "forget":
            removed = store.forget(args.scope)
            _out(args, "\n".join(f"removed {r}" for r in removed) or "nothing to remove")
        elif args.cmd == "models":
            _models(args, cfg, store)
        elif args.cmd == "langs":
            _langs(args, store)
        elif args.cmd == "translations":
            _translations(args, store)
        return EXIT_OK
    except NabuError as e:
        print(f"nabu: {e.message}", file=sys.stderr)  # noqa: T201
        return EXIT_FAIL
    except KeyboardInterrupt:
        return EXIT_FAIL
    except Exception as e:  # never a traceback: it could carry document text (FR-11.5)
        print(f"nabu: unexpected error ({type(e).__name__})", file=sys.stderr)  # noqa: T201
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
