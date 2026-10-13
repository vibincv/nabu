"""Machine report (FR-1.1). Detects, never installs. GPU and OCR detection land in M1/M4."""

from __future__ import annotations

import os
import platform
import shutil
import sys

from nabu.config import Config
from nabu.errors import ModelUnavailable
from nabu.model.profiles import resolve_profile
from nabu.model.runtime import make_runtime, same_model
from nabu.model.tiers import recommend
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


def total_ram_gb() -> float | None:
    ram = _total_ram_bytes()
    return round(ram / 2**30, 1) if ram else None


def report(cfg: Config, paths: StorePaths) -> dict:
    disk_root = paths.data_dir if paths.data_dir.exists() else paths.data_dir.anchor or "/"
    runtime = make_runtime(cfg, timeout_s=3.0)
    try:
        present = runtime.available()
        try:
            models = runtime.models() if present else []
        except ModelUnavailable:
            models = []
    finally:
        runtime.close()
    ram_gb = total_ram_gb()
    tier = recommend(ram_gb)
    return {
        "os": platform.system(),
        "os_version": platform.release(),
        "arch": platform.machine(),
        "cpu_cores": os.cpu_count(),
        "ram_total_gb": ram_gb,
        "disk_free_gb": round(shutil.disk_usage(disk_root).free / 2**30, 1),
        "runtime": {"kind": cfg.model_runtime, "endpoint": cfg.model_endpoint,
                    "present": present, "models": models},
        "configured_model": cfg.model,
        "model_installed": bool(cfg.model) and any(same_model(m, cfg.model) for m in models),
        "model_profile": resolve_profile(cfg.model, cfg.model_profile, cfg.model_profiles).name
                         if cfg.model else None,
        "recommended_model": tier.model,
        "recommended_for": tier.hardware,
        "store": {"config": str(paths.config_file), "data": str(paths.data_dir)},
    }
