"""Build the release folder the install scripts run from (developer tool, M4).

    python install/build_release.py [--uv PATH] [--out dist/release]

Writes: the nabu wheel (with the built review UI), requirements.txt (every dependency pinned
with sha256 hashes, exported from uv.lock), install.ps1, install.sh and SHA256SUMS. Build the UI
first (cd ui && npm run build).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--uv", default=shutil.which("uv") or "uv")
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "release")
    args = ap.parse_args()

    if not (ROOT / "src" / "nabu" / "server" / "ui_dist" / "index.html").is_file():
        print("build the review UI first: cd ui && npm run build", file=sys.stderr)  # noqa: T201
        return 1
    out: Path = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    subprocess.run([args.uv, "build", "--wheel", "--out-dir", str(out)], cwd=ROOT,  # noqa: S603
                   check=True)
    subprocess.run([args.uv, "export", "--frozen", "--extra", "read", "--no-dev",  # noqa: S603
                    "--no-emit-project", "--format", "requirements-txt",
                    "-o", str(out / "requirements.txt")], cwd=ROOT, check=True)
    for script in ("install.ps1", "install.sh"):
        shutil.copy2(ROOT / "install" / script, out / script)
    listed = sorted([*out.glob("nabu-*.whl"), out / "requirements.txt"])
    (out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in listed),
                                    encoding="ascii", newline="\n")
    for p in sorted(out.iterdir()):
        print(f"{p.stat().st_size:>10}  {p.name}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
