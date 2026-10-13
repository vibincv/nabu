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

    d = sub.add_parser("doctor", help="report OS, hardware and model runtime",
                       epilog="example: nabu doctor --json")
    d.add_argument("--json", action="store_true")

    s = sub.add_parser("serve", help="open the review window on this machine",
                       epilog="example: nabu serve --port 8765")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--verbose", action="store_true")

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

    sub.add_parser("version", help="print the version", epilog="example: nabu version")
    return p


def main(argv: list[str] | None = None) -> int:
    # Order matters: the egress guard goes in before anything else can open a socket.
    netguard.install()
    from nabu.hardening import configure_logging, disable_core_dumps

    disable_core_dumps()

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code == 0 else EXIT_USAGE

    from nabu.config import load_config
    from nabu.store.paths import default_paths
    from nabu.store.store import Store

    paths = default_paths()
    try:
        configure_logging(paths.logs_dir if args.cmd == "serve" else None,
                          verbose=getattr(args, "verbose", False))
        cfg = load_config(paths.config_file, {"ui_port": getattr(args, "port", None)})
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

            serve(cfg.ui_port, open_browser=not args.no_browser)
        elif args.cmd == "templates":
            if args.tcmd == "list":
                for t in store.templates():
                    h = t["template"]
                    _out(args, f'{h["id"]}  {h["document_type"]} · {h.get("region") or "No region"}'
                               f' · {h["format"]["name"]}  v{h["version"]}')
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
        return EXIT_OK
    except NabuError as e:
        print(f"nabu: {e.message}", file=sys.stderr)  # noqa: T201
        return EXIT_FAIL
    except KeyboardInterrupt:
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
