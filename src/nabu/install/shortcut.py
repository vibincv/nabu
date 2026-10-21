"""The Nabu shortcut (FR-1.11): Start menu on Windows, Applications on macOS, the application
menu on Linux. It runs `python -m nabu.app`, which opens the review window."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def location(system: str) -> Path | None:
    home = Path.home()
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Nabu.lnk"
    if system == "Darwin":
        return home / "Applications" / "Nabu.app"
    if system == "Linux":
        data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        return data / "applications" / "nabu.desktop"
    return None


def launcher(system: str) -> list[str]:
    """The program the shortcut starts: this Python, without a console window on Windows."""
    exe = Path(sys.executable)
    if system == "Windows":
        windowless = exe.with_name("pythonw.exe")
        if windowless.is_file():
            exe = windowless
    return [str(exe), "-m", "nabu.app"]


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def windows_command(path: Path, cmd: list[str]) -> list[str]:
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(str(path))}); "
              f"$s.TargetPath = {_ps_quote(cmd[0])}; "
              f"$s.Arguments = {_ps_quote(' '.join(cmd[1:]))}; "
              "$s.Description = 'Nabu: read documents on this machine'; $s.Save()")
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]


def create(system: str, path: Path) -> None:
    cmd = launcher(system)
    path.parent.mkdir(parents=True, exist_ok=True)
    if system == "Windows":
        subprocess.run(windows_command(path, cmd), check=True, capture_output=True)  # noqa: S603
    elif system == "Darwin":
        macos = path / "Contents" / "MacOS"
        macos.mkdir(parents=True, exist_ok=True)
        (path / "Contents" / "Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
            "<key>CFBundleName</key><string>Nabu</string>"
            "<key>CFBundleExecutable</key><string>Nabu</string>"
            "<key>CFBundleIdentifier</key><string>local.nabu</string>"
            "<key>CFBundlePackageType</key><string>APPL</string></dict></plist>\n",
            encoding="utf-8")
        run = macos / "Nabu"
        run.write_text("#!/bin/sh\nexec " + " ".join(f"'{c}'" for c in cmd) + "\n", encoding="utf-8")
        run.chmod(0o755)
    else:
        path.write_text("[Desktop Entry]\nType=Application\nName=Nabu\n"
                        "Comment=Read documents on this machine\n"
                        "Exec=" + " ".join(f'"{c}"' for c in cmd) + "\nTerminal=false\n"
                        "Categories=Office;\n", encoding="utf-8")
