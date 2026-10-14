"""Machine report (FR-1.1). Detects, never installs.

GPU memory is read from nvidia-smi when it exists (a local program, no network, 2 s limit).
Other GPUs are reported as unknown rather than guessed.
"""

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


def _win_memory():  # type: ignore[no-untyped-def]
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
        return st
    return None


def _total_ram_bytes() -> int | None:
    if sys.platform == "win32":
        st = _win_memory()
        return int(st.ullTotalPhys) if st else None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def total_ram_gb() -> float | None:
    ram = _total_ram_bytes()
    return round(ram / 2**30, 1) if ram else None


def free_ram_gb() -> float | None:
    if sys.platform == "win32":
        st = _win_memory()
        return round(st.ullAvailPhys / 2**30, 1) if st else None
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) * 1024 / 2**30, 1)
    except OSError:
        pass
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return None


def gpus() -> list[dict]:
    """NVIDIA GPUs and their memory, or [] when none can be detected."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    import subprocess

    try:
        out = subprocess.run(  # noqa: S603  (fixed local program, fixed arguments, no shell)
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        name, _, mem = line.rpartition(",")
        try:
            found.append({"name": name.strip(), "vram_gb": round(int(mem.strip()) / 1024, 1)})
        except ValueError:
            continue
    return found


def ocr_report(paths: StorePaths) -> dict:
    from nabu.ocr import engine, packs

    present = engine.available()
    have = packs.installed(paths.ocr_langs_dir)
    return {
        "engine": "rapidocr" if present else None,
        "present": present,
        "languages": sorted({*packs.BUILTIN_LANGS, *have}) if present else [],
        "packs_available": {lang: {"language": p.language, "installed": lang in have,
                                   "size_mb": p.size_mb} for lang, p in packs.PACKS.items()},
    }


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
    gpu = gpus()
    vram = max((g["vram_gb"] for g in gpu), default=None)
    tier = recommend(ram_gb, vram)
    return {
        "os": platform.system(),
        "os_version": platform.release(),
        "arch": platform.machine(),
        "cpu_cores": os.cpu_count(),
        "ram_total_gb": ram_gb,
        "ram_free_gb": free_ram_gb(),
        "gpus": gpu,
        "disk_free_gb": round(shutil.disk_usage(disk_root).free / 2**30, 1),
        "runtime": {"kind": cfg.model_runtime, "endpoint": cfg.model_endpoint,
                    "present": present, "models": models},
        "configured_model": cfg.model,
        "model_installed": bool(cfg.model) and any(same_model(m, cfg.model) for m in models),
        "model_profile": resolve_profile(cfg.model, cfg.model_profile, cfg.model_profiles).name
                         if cfg.model else None,
        "recommended_model": tier.model,
        "recommended_for": tier.hardware,
        "ocr": ocr_report(paths),
        "store": {"config": str(paths.config_file), "data": str(paths.data_dir)},
    }
