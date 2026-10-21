"""Download one pinned artefact and check its sha256 (FR-1.12).

Runs as its own process (`python -m nabu.install.fetch <key> <dest>`), started by the
installer, so the installer process itself keeps the egress guard. It takes a key from
pins.ARTEFACTS, never a URL. The file is written as <dest>.part and renamed only after the
checksum matches; on a mismatch the partial file is deleted and the exit code is 3.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from nabu.install.pins import ARTEFACTS, Artefact

EXIT_OK, EXIT_FAIL, EXIT_MISMATCH = 0, 1, 3


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(a: Artefact, dest: Path, out=print) -> int:  # type: ignore[no-untyped-def]
    name = a.url.rsplit("/", 1)[-1]
    if dest.is_file() and sha256_file(dest) == a.sha256:
        out(f"{name}: already downloaded and checked")
        return EXIT_OK
    import httpx

    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    try:
        with httpx.stream("GET", a.url, follow_redirects=True, trust_env=True,
                          timeout=httpx.Timeout(60.0, connect=15.0)) as r:
            r.raise_for_status()
            done, step = 0, max(a.size_bytes // 20, 1)
            part.unlink(missing_ok=True)  # a leftover from a stopped run
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) \
                | getattr(os, "O_BINARY", 0)
            with os.fdopen(os.open(part, flags, 0o600), "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    h.update(chunk)
                    if (done + len(chunk)) // step != done // step:
                        out(f"{name}: {(done + len(chunk)) * 100 // a.size_bytes}%")
                    done += len(chunk)
    except (httpx.HTTPError, OSError) as e:
        part.unlink(missing_ok=True)
        out(f"could not download {name} ({type(e).__name__}); check the internet connection")
        return EXIT_FAIL
    if h.hexdigest() != a.sha256:
        part.unlink(missing_ok=True)
        out(f"{name} does not match the checksum shipped with Nabu; it was deleted and nothing "
            "was installed")
        return EXIT_MISMATCH
    part.replace(dest)
    out(f"{name}: downloaded, checksum matches")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in ARTEFACTS:
        print(f"usage: python -m nabu.install.fetch <{'|'.join(ARTEFACTS)}> <dest>")  # noqa: T201
        return EXIT_FAIL
    return fetch(ARTEFACTS[args[0]], Path(args[1]), out=lambda s: print(s, flush=True))  # noqa: T201


if __name__ == "__main__":
    raise SystemExit(main())
