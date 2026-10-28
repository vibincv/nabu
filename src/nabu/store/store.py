"""The store: the only module that writes to disk (AR-2).

Writes: config, templates (+ previous versions), translation memory, OCR language packs,
logs (via logging).
Never writes: uploads, page images, working results, values (AD-8, AR-7).
The output JSON is downloaded by the browser (FR-8.5). The one exception: with config
`export_dir` set, each saved document's output is also written there for another service
(owner decision 2026-10-21); that folder never overlaps the store, which stays value-free.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable
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


def _load_template(p: Path) -> dict:
    """Read a template file. A damaged file is named, never shown (it is the user's data)."""
    try:
        t = json.loads(p.read_text(encoding="utf-8"))
        header = t["template"]
        if not isinstance(header, dict) or not isinstance(header.get("version"), int):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise NabuError(f"template file is damaged: {p.name}. Delete it or restore it from "
                        "versions/.") from None
    return t


class Store:
    def __init__(self, paths: StorePaths | None = None) -> None:
        self.paths = paths or default_paths()

    # ---- config (DD-5) -----------------------------------------------------------------------
    def config_data(self) -> dict:
        """The raw config file, so an update keeps keys the caller does not touch."""
        p = self.paths.config_file
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            raise NabuError(f"config file is not valid JSON: {p.name}") from None
        if not isinstance(data, dict):
            raise NabuError(f"config file is not a JSON object: {p.name}")
        return data

    def save_config(self, data: dict) -> Path:
        """Validated before writing, so a bad value never reaches disk."""
        from nabu.config import parse_config

        parse_config(data)
        atomic_write_bytes(self.paths.config_file, _dump(data))
        return self.paths.config_file

    # ---- OCR language packs (FR-1.9) -----------------------------------------------------
    def install_ocr_pack(self, lang: str, files: dict[str, bytes]) -> Path:
        """Write a downloaded, checksum-verified pack. Files are model weights, never values."""
        from nabu.ocr.packs import PACKS

        pack = PACKS.get(lang)
        if pack is None or set(files) != {pack.model.name, pack.keys.name}:
            raise NabuError(f"not a known OCR language pack: {lang}")
        d = self.paths.ocr_langs_dir / lang
        for name, data in files.items():
            atomic_write_bytes(d / name, data)
        return d

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
        return self._save_template(t, session.values())

    def _save_template(self, t: dict, values: Iterable[str]) -> Path:
        assert_no_values(t, values, "template")
        header = t.get("template") or {}
        path = self._template_path(header)
        if path.exists():
            prev = _load_template(path)
            prev_header = prev["template"]
            if prev_header.get("id") != header.get("id"):
                raise NabuError("another template already uses this document type, region and "
                                "format; update that template or choose a different format name")
            prev_ver = prev_header["version"]
            if not isinstance(header.get("version"), int) or header["version"] <= prev_ver:
                raise NabuError(f"template version must be higher than the saved version {prev_ver}")
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
            out.append(_load_template(p))
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
        self._prune(path.parent)
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
        current = _load_template(path)["template"]["version"]
        return sorted(versions) + [current]

    def load_template(self, template_id: str) -> dict:
        path = self.find_template(template_id)
        if path is None:
            raise NabuError(f"no template with id {template_id}")
        return _load_template(path)

    def _version_file(self, path: Path, version: int) -> Path:
        return path.parent / "versions" / f"{path.stem}.v{version}.json"

    def history_entries(self, template_id: str) -> list[dict]:
        """Each version with its time and what changed: field names only (FR-7.12)."""
        path = self.find_template(template_id)
        if path is None:
            raise NabuError(f"no template with id {template_id}")
        out = []
        current = _load_template(path)["template"]["version"]
        for v in self.history(template_id):
            h = _load_template(path if v == current else self._version_file(path, v))["template"]
            out.append({"version": v, "updated_at": h.get("updated_at"),
                        "change": h.get("change"), "current": v == current})
        return out

    def rollback_template(self, template_id: str, version: int, values: Iterable[str]) -> Path:
        """Restore an earlier version's fields as a new version (FR-7.12). The header (names,
        region, format) stays as it is now, so a rename in between is kept."""
        path = self.find_template(template_id)
        if path is None:
            raise NabuError(f"no template with id {template_id}")
        current = _load_template(path)
        h = current["template"]
        old_file = self._version_file(path, version)
        if version == h["version"] or not old_file.exists():
            raise NabuError(f"template {template_id} has no earlier version {version}")
        old = _load_template(old_file)
        t = {**old, "template": {**h, "version": h["version"] + 1,
                                 "change": {"kind": "rolled_back", "to_version": version}}}
        return self._save_template(t, values)

    def move_template(self, template_id: str, changes: dict, note: dict,
                      values: Iterable[str]) -> Path:
        """Rename a template's document type or format (FR-7.11): a new version under the new
        name. Its earlier versions move with it."""
        old_path = self.find_template(template_id)
        if old_path is None:
            raise NabuError(f"no template with id {template_id}")
        t = _load_template(old_path)
        h = t["template"]
        new = {**t, "template": {**h, **changes, "version": h["version"] + 1, "change": note}}
        new_path = self._template_path(new["template"])
        if new_path == old_path:
            return self._save_template(new, values)
        if new_path.exists():
            raise NabuError("another template already uses this document type, region and "
                            "format; choose a different name")
        assert_no_values(new, values, "template")
        vdir = old_path.parent / "versions"
        for v in sorted(vdir.glob(f"{old_path.stem}.v*.json")) if vdir.exists() else []:
            n = int(v.stem.rsplit(".v", 1)[1])
            atomic_write_bytes(self._version_file(new_path, n), v.read_bytes())
        atomic_write_bytes(self._version_file(new_path, h["version"]), _dump(t))
        new["template"]["updated_at"] = _now()
        atomic_write_bytes(new_path, _dump(new))
        for v in sorted(vdir.glob(f"{old_path.stem}.v*.json")) if vdir.exists() else []:
            v.unlink()
        old_path.unlink()
        self._prune(old_path.parent)
        return new_path

    def _prune(self, folder: Path) -> None:
        """Remove empty folders left by a move or delete, up to the templates folder."""
        root = self.paths.templates_dir
        for d in (folder / "versions", folder, folder.parent):
            if d.exists() and d != root and root in d.parents and not any(d.iterdir()):
                d.rmdir()

    # ---- translation memory -------------------------------------------------------------
    def translations(self) -> dict:
        p = self.paths.translations_file
        if not p.exists():
            return {"schema_version": "1.0", "entries": []}
        try:
            tm = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(tm.get("entries"), list):
                raise ValueError
        except (OSError, ValueError, AttributeError):
            raise NabuError(f"translation memory is damaged: {p.name}. "
                            "Run: nabu forget --translations") from None
        return tm

    def remember_translation(self, entry: dict, session: Session) -> None:
        """Labels and fixed terms only, never values (FR-9.8, DD-4.1)."""
        assert_no_values(entry, session.values(), "translation")
        tm = self.translations()
        entry = {**entry, "added_at": _now()}
        tm["entries"].append(entry)
        atomic_write_bytes(self.paths.translations_file, _dump(tm))

    def delete_translation(self, entry_id: str) -> bool:
        tm = self.translations()
        kept = [e for e in tm["entries"] if not (isinstance(e, dict) and e.get("id") == entry_id)]
        if len(kept) == len(tm["entries"]):
            return False
        atomic_write_bytes(self.paths.translations_file, _dump({**tm, "entries": kept}))
        return True

    # ---- export folder (config `export_dir`) -----------------------------------------
    def export_output(self, name: str, data: bytes) -> Path | None:
        """Write one saved document's output for another service; None when export is off.
        The only write that holds document values (AR-7 exception, owner decision 2026-10-21).
        Atomic: a reader never sees half a file, and the temp file starts with a dot and does
        not end in .json. Files are never deleted by Nabu; the reading service removes them."""
        d = self.paths.export_dir
        if d is None:
            return None
        if Path(name).name != name or not name.endswith(".nabu.json"):
            raise NabuError("export file name is not valid")
        path = d / name
        try:
            atomic_write_bytes(path, data)
        except OSError as e:
            raise NabuError(f"could not write to the export folder ({type(e).__name__})") from None
        return path

    # ---- forget (FR-11.4) -------------------------------------------------------------
    def forget(self, scope: Literal["templates", "translations", "all"]) -> list[str]:
        removed: list[str] = []
        if scope in ("templates", "all"):
            removed += self._forget_templates()
        if scope in ("translations", "all") and self.paths.translations_file.exists():
            removed.append(str(self.paths.translations_file))
            self.paths.translations_file.unlink()
        if scope == "all" and self.paths.logs_dir.exists():
            removed += [str(p) for p in self.paths.logs_dir.rglob("*") if p.is_file()]
            shutil.rmtree(self.paths.logs_dir)
        return removed

    def _forget_templates(self) -> list[str]:
        """Nabu's template files only (<type>/<region>/<format>.json and versions/): the folder
        may be one the owner chose (config `templates_dir`) and hold other files."""
        root = self.paths.templates_dir
        if not root.exists():
            return []

        def ours(folder: Path) -> bool:  # <root>/<type key>/<region>
            key, region = folder.parent.name, folder.name
            return (folder.parent.parent == root and bool(_SLUG.match(key))
                    and (region == NO_REGION_DIR or bool(_REGION.match(region))))

        files = [p for p in root.glob("*/*/*.json") if ours(p.parent)]
        files += [p for p in root.glob("*/*/versions/*.json") if ours(p.parent.parent)]
        for p in files:
            p.unlink()
        for d in sorted({p.parent for p in files}, key=lambda d: len(d.parts), reverse=True):
            self._prune(d)
        return sorted(str(p) for p in files)
