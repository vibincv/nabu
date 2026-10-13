"""The store: the only module that writes to disk (AR-2).

Writes: config, templates (+ previous versions), translation memory, logs (via logging).
Never writes: uploads, page images, working results, values (AD-8, AR-7).
The output JSON is not written by Nabu at all: the browser downloads it (FR-8.5).
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from nabu.errors import NabuError
from nabu.session import Session
from nabu.store.guard import assert_no_values
from nabu.store.paths import StorePaths, atomic_write_bytes, default_paths, secure_mkdir

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_REGION = re.compile(r"^[A-Z]{2}$")
NO_REGION_DIR = "_none"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")


class Store:
    def __init__(self, paths: StorePaths | None = None) -> None:
        self.paths = paths or default_paths()

    # ---- sessions (memory only) -------------------------------------------------------
    def new_session(self) -> Session:
        return Session()

    def end_session(self, s: Session) -> None:
        s.close()

    # ---- templates ----------------------------------------------------------------------
    def _template_path(self, header: dict) -> Path:
        key = header.get("document_type_key", "")
        region = header.get("region")
        fmt_id = (header.get("format") or {}).get("id", "")
        if not _SLUG.match(key) or not _SLUG.match(fmt_id):
            raise NabuError("template key or format id is not a valid slug")
        if region is not None and not _REGION.match(region):
            raise NabuError("region must be an ISO 3166-1 alpha-2 code in capitals, or null")
        return self.paths.templates_dir / key / (region or NO_REGION_DIR) / f"{fmt_id}.json"

    def save_template(self, t: dict, session: Session | None) -> Path:
        """Save a template. Refuses if any string in it matches a value from the session
        (AR-7). Keeps the previous version under versions/ (DD-2.6). Atomic write (Section 14).
        """
        if session is None:
            raise NabuError("templates are saved only from a review session (FR-7.6)")
        assert_no_values(t, session.values(), "template")
        header = t.get("template") or {}
        path = self._template_path(header)
        if path.exists():
            prev = json.loads(path.read_text(encoding="utf-8"))
            prev_ver = (prev.get("template") or {}).get("version", 0)
            vdir = path.parent / "versions"
            secure_mkdir(vdir)
            atomic_write_bytes(vdir / f"{path.stem}.v{prev_ver}.json", _dump(prev))
        header.setdefault("created_at", _now())
        header["updated_at"] = _now()
        atomic_write_bytes(path, _dump(t))
        return path

    def templates(self) -> list[dict]:
        root = self.paths.templates_dir
        if not root.exists():
            return []
        out = []
        for p in sorted(root.glob("*/*/*.json")):
            out.append(json.loads(p.read_text(encoding="utf-8")))
        return out

    def find_template(self, template_id: str) -> Path | None:
        for t in self.templates():
            h = t.get("template", {})
            if h.get("id") == template_id:
                return self._template_path(h)
        return None

    def delete_template(self, template_id: str) -> list[str]:
        path = self.find_template(template_id)
        if path is None:
            raise NabuError(f"no template with id {template_id}")
        removed = [str(path)]
        path.unlink()
        vdir = path.parent / "versions"
        for v in sorted(vdir.glob(f"{path.stem}.v*.json")) if vdir.exists() else []:
            v.unlink()
            removed.append(str(v))
        return removed

    def history(self, template_id: str) -> list[int]:
        path = self.find_template(template_id)
        if path is None:
            raise NabuError(f"no template with id {template_id}")
        vdir = path.parent / "versions"
        versions = []
        if vdir.exists():
            for v in vdir.glob(f"{path.stem}.v*.json"):
                versions.append(int(v.stem.rsplit(".v", 1)[1]))
        current = json.loads(path.read_text(encoding="utf-8"))["template"]["version"]
        return sorted(versions) + [current]

    # ---- translation memory -------------------------------------------------------------
    def translations(self) -> dict:
        p = self.paths.translations_file
        if not p.exists():
            return {"schema_version": "1.0", "entries": []}
        return json.loads(p.read_text(encoding="utf-8"))

    def remember_translation(self, entry: dict, session: Session) -> None:
        """Labels and fixed terms only, never values (FR-9.8, DD-4.1)."""
        assert_no_values(entry, session.values(), "translation")
        tm = self.translations()
        entry = {**entry, "added_at": _now()}
        tm["entries"].append(entry)
        atomic_write_bytes(self.paths.translations_file, _dump(tm))

    # ---- forget (FR-11.4) -------------------------------------------------------------
    def forget(self, scope: Literal["templates", "translations", "all"]) -> list[str]:
        removed: list[str] = []
        if scope in ("templates", "all") and self.paths.templates_dir.exists():
            removed += [str(p) for p in self.paths.templates_dir.rglob("*") if p.is_file()]
            shutil.rmtree(self.paths.templates_dir)
        if scope in ("translations", "all") and self.paths.translations_file.exists():
            removed.append(str(self.paths.translations_file))
            self.paths.translations_file.unlink()
        if scope == "all" and self.paths.logs_dir.exists():
            removed += [str(p) for p in self.paths.logs_dir.rglob("*") if p.is_file()]
            shutil.rmtree(self.paths.logs_dir)
        return removed
