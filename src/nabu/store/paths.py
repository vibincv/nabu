"""Per-OS store locations (DD-5) and secure file creation (FR-11.7).

NABU_HOME overrides everything (tests, portable installs): config and data both live under it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


@dataclass(frozen=True)
class StorePaths:
    config_file: Path
    data_dir: Path

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def translations_file(self) -> Path:
        return self.data_dir / "translations.json"

    @property
    def ocr_langs_dir(self) -> Path:
        return self.data_dir / "ocr-langs"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def default_paths() -> StorePaths:
    home_override = os.environ.get("NABU_HOME")
    if home_override:
        base = Path(home_override)
        return StorePaths(config_file=base / "config.json", data_dir=base)

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Nabu"
        return StorePaths(config_file=base / "config.json", data_dir=base)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Nabu"
        return StorePaths(config_file=base / "config.json", data_dir=base)

    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return StorePaths(config_file=config_home / "nabu" / "config.json", data_dir=data_home / "nabu")


def secure_mkdir(path: Path) -> None:
    """Create a directory (and parents) readable only by the user. On Windows, the per-user
    %APPDATA% ACL already restricts access; chmod is a no-op there."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, DIR_MODE)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, then rename (Section 14: disk full keeps the
    previous version intact). The temp file is created 0600 from the start, never world-readable."""
    secure_mkdir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    if os.name == "posix":
        os.chmod(path, FILE_MODE)
