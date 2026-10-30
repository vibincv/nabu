"""Build the product page with its clickable demo (developer tool, M5).

    python install/build_site.py [--npm PATH] [--out dist/site]

Writes: the page (site/index.html, site/site.css) and the review window demo on the synthetic
specimen licence (ui, `vite build --mode demo`) under demo/. Every file is static and nothing
loads from another site; serve the folder from any static web host. Opening index.html from
disk does not run the demo (browsers do not run module scripts from file:// URLs).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_OUT = ROOT / "dist" / "site" / "demo"  # fixed in ui/vite.config.ts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--npm", default=shutil.which("npm") or "npm")
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "site")
    args = ap.parse_args()

    subprocess.run([args.npm, "run", "build:demo"], cwd=ROOT / "ui", check=True)  # noqa: S603
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    if out.resolve() != DEMO_OUT.parent.resolve():
        shutil.copytree(DEMO_OUT, out / "demo", dirs_exist_ok=True)
    for name in ("index.html", "site.css"):
        shutil.copy2(ROOT / "site" / name, out / name)
    for p in sorted(q for q in out.rglob("*") if q.is_file()):
        print(f"{p.stat().st_size:>10}  {p.relative_to(out).as_posix()}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
