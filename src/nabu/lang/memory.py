"""Translation memory read path; writes go through Store.remember_translation (M3, FR-9.8).

Entries: {"id", "lang", "term", "english", "scope"?}. A scoped entry (a document type) is used
before a global one (DD-4.2). Terms match on their normalised form.
"""

from __future__ import annotations

from nabu.store.guard import normalise


class TranslationMemory:
    def __init__(self, data: dict | None = None) -> None:
        self._by_key: dict[tuple[str, str, str | None], str] = {}
        for e in (data or {}).get("entries", []):
            if not isinstance(e, dict):
                continue
            term, english, lang = e.get("term"), e.get("english"), e.get("lang")
            if isinstance(term, str) and isinstance(english, str) and isinstance(lang, str):
                self._by_key[(lang, normalise(term), e.get("scope") or None)] = english

    def lookup(self, term: str, lang: str | None, doc_type: str | None = None) -> str | None:
        if not lang:
            return None
        key = normalise(term)
        if doc_type:
            hit = self._by_key.get((lang, key, doc_type))
            if hit is not None:
                return hit
        return self._by_key.get((lang, key, None))
