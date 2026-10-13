"""Process hardening applied at start (FR-11.3, FR-11.5).

- Core dumps off, so a crash does not write process memory (which holds document values) to disk.
- Logging that can only carry safe, structured facts: file names, sizes, timings, error types.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def disable_core_dumps() -> bool:
    """Return True if core dumps are now disabled for this process.

    POSIX: RLIMIT_CORE = 0. Windows has no per-process equivalent in the standard library;
    Windows Error Reporting may still keep a minidump. Tracked as a residual risk (M1 task).
    """
    try:
        import resource  # POSIX only
    except ImportError:
        return False
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return True
    except (ValueError, OSError):
        return False


class SafeFormatter(logging.Formatter):
    """Never prints tracebacks or stack frames: only the exception type (FR-11.5).

    Exception *messages* can contain document text (a parser echoing a line it failed on),
    so they are dropped too. Nabu's own NabuError messages are written to be safe and are
    logged explicitly by the caller, not through exc_info.
    """

    def formatException(self, ei) -> str:  # type: ignore[no-untyped-def]  # noqa: N802
        exc_type = ei[0].__name__ if ei and ei[0] else "Exception"
        return f"[exception type: {exc_type}]"

    def formatStack(self, stack_info: str) -> str:  # noqa: N802
        return "[stack omitted]"


def configure_logging(log_dir: Path | None, verbose: bool = False) -> None:
    """Configure the root 'nabu' logger. Third-party loggers are capped at WARNING so that
    libraries (httpx, uvicorn) cannot log request bodies or URLs with document content."""
    fmt = SafeFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger("nabu")
    root.handlers.clear()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    if log_dir is not None:
        from nabu.store.paths import FILE_MODE, secure_mkdir

        secure_mkdir(log_dir)
        log_file = log_dir / "nabu.log"
        # Create it user-only before logging opens it (FR-11.7); the default umask gives 0644.
        os.close(os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, FILE_MODE))
        if os.name == "posix":
            os.chmod(log_file, FILE_MODE)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    for noisy in ("httpx", "httpcore", "uvicorn.access", "multipart", "PIL", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # uvicorn.access logs request paths; paths carry no values but keep it off anyway.
    logging.getLogger("uvicorn.access").disabled = True
