"""A review session (Section 5): everything lives in process memory, nothing on disk (AD-8).

The session also keeps the set of document values seen so far, which the store uses to refuse
any write that contains one of them (AR-7).
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field

from nabu.store.guard import normalise


@dataclass
class Session:
    id: str = field(default_factory=lambda: secrets.token_urlsafe(12))
    # Uploaded file bytes and rendered page images. Never written to disk (FR-3.6, API-2).
    upload: bytes | None = None
    upload_name: str | None = None
    page_images: dict[int, bytes] = field(default_factory=dict)
    working_result: dict | None = None
    reading: object | None = field(default=None, repr=False)  # nabu.ocr.words.Reading, for drawn boxes
    _values: set[str] = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    closed: bool = False

    def __repr__(self) -> str:  # never print contents
        return f"Session(id={self.id!r}, pages={len(self.page_images)}, closed={self.closed})"

    def register_value(self, value: str | None) -> None:
        """Record a document value so the store can refuse to persist it."""
        if value is None:
            return
        n = normalise(value)
        if n:
            with self._lock:
                self._values.add(n)

    def values(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._values)

    def close(self) -> None:
        """Release all document data. Python cannot guarantee memory is zeroed; dropping the
        references lets it be reclaimed, and core dumps are off (hardening.py)."""
        with self._lock:
            self.upload = None
            self.page_images.clear()
            self.working_result = None
            self.reading = None
            self._values.clear()
            self.closed = True
