"""Machine report (FR-1.1). Detects, never installs. GPU, OCR and model tier land in M1/M4."""

from __future__ import annotations

import os
import platform
import shutil
import sys

from nabu.config import Config
from nabu.model.ollama import ModelClient
from nabu.store.paths import StorePaths


def _total_ram_bytes() -> int | None:
    if sys.platform == "win32":
        import ctypes

        class MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MemStatus()
        st.dwLength = ctypes.sizeof(MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
            return int(st.ullTotalPhys)
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def report(cfg: Config, paths: StorePaths) -> dict:
    disk_root = paths.data_dir if paths.data_dir.exists() else paths.data_dir.anchor or "/"
    client = ModelClient(cfg, timeout_s=3.0)
    try:
        present = client.available()
        models = client.models() if present else []
    finally:
        client.close()
    ram = _total_ram_bytes()
    return {
        "os": platform.system(),
        "os_version": platform.release(),
        "arch": platform.machine(),
        "cpu_cores": os.cpu_count(),
        "ram_total_gb": round(ram / 2**30, 1) if ram else None,
        "disk_free_gb": round(shutil.disk_usage(disk_root).free / 2**30, 1),
        "runtime": {"endpoint": cfg.model_endpoint, "present": present, "models": models},
        "configured_model": cfg.model,
        "store": {"config": str(paths.config_file), "data": str(paths.data_dir)},
    }
