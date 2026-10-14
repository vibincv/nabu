"""Language per page and per field, ISO 639-1 (FR-9.1, FR-9.2). M1.

No dependency: the script decides most languages (Hangul -> ko); Latin-script text is told apart
by common short words and letters. Text too short to tell (an ID, a date, a single name) returns
None, and the caller uses the page's language. Returning None is better than a confident guess.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from nabu.ocr.engine import script_of

# Script -> language when the script alone decides it.
_SCRIPT_LANG = {
    "Hangul": "ko", "Hiragana": "ja", "Katakana": "ja", "Thai": "th", "Greek": "el",
    "Hebrew": "he", "Armenian": "hy", "Georgian": "ka", "Khmer": "km", "Lao": "lo",
    "Myanmar": "my", "Ethiopic": "am", "Sinhala": "si", "Tamil": "ta", "Telugu": "te",
    "Kannada": "kn", "Malayalam": "ml", "Gujarati": "gu", "Gurmukhi": "pa", "Bengali": "bn",
    "Devanagari": "hi", "Arabic": "ar", "Cyrillic": "ru", "Han": "zh",
}

# Short, frequent words. Field labels are short, so single words count.
_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the and of to in for is on with by from date no number total name address "
                    "amount invoice due customer account phone email page tax".split()),
    "de": frozenset("der die das und von zu mit für ist auf nicht ein eine des dem den im "
                    "datum nr rechnung betrag kunde kundennr anschrift straße gesamt seite steuer "
                    "lieferant fällig am bis".split()),
    "fr": frozenset("le la les et de des du un une pour est sur avec par au aux date nom "
                    "adresse montant facture total client numéro téléphone".split()),
    "es": frozenset("el la los las y de del en un una para es con por al fecha nombre "
                    "dirección importe factura total cliente número teléfono".split()),
    "it": frozenset("il lo la gli le e di del della un una per è con da al data nome "
                    "indirizzo importo fattura totale cliente numero telefono".split()),
    "pt": frozenset("o a os as e de do da em um uma para é com por ao data nome endereço "
                    "valor fatura total cliente número telefone".split()),
    "nl": frozenset("de het een en van in op met voor is niet aan datum naam adres bedrag "
                    "factuur totaal klant nummer telefoon".split()),
}
_LETTERS = {"de": "äöüß", "fr": "éèêàçùœ", "es": "ñ¿¡áíóú", "pt": "ãõç", "it": "àèìòù",
            "nl": "ĳ"}
# German and Dutch labels are compounds ("Rechnungsdatum", "Klantnummer") that rarely match a whole
# word. A long word that starts or ends with a long vocabulary word counts half.
_STEMS = {lang: tuple(w for w in vocab if len(w) >= 5) for lang, vocab in _WORDS.items()}
_COMPOUND_MIN = 8
_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_UK = frozenset("іїєґ")  # letters Russian does not use


def scripts(text: str) -> Counter[str]:
    return Counter(s for s in (script_of(c) for c in text) if s)


def _word_score(word: str, lang: str) -> float:
    if word in _WORDS[lang]:
        return 1.0
    if len(word) >= _COMPOUND_MIN and any(word.startswith(s) or word.endswith(s) for s in _STEMS[lang]):
        return 0.5
    return 0.0


def detect(text: str) -> str | None:
    """ISO 639-1 code of `text`, or None when there is too little text to tell."""
    counts = scripts(text)
    if not counts:
        return None
    script, n = counts.most_common(1)[0]
    if script != "Latin":
        if script == "Han" and (counts.get("Hiragana") or counts.get("Katakana")):
            return "ja"
        if script == "Cyrillic" and any(c in _UK for c in text.lower()):
            return "uk"
        return _SCRIPT_LANG.get(script)
    # single letters ("a", "e", "y") are words in several languages and in every ID: ignored
    words = [unicodedata.normalize("NFC", w.lower()) for w in _TOKEN.findall(text) if len(w) > 1]
    scores = {lang: sum(_word_score(w, lang) for w in words) for lang in _WORDS}
    low = text.lower()
    for lang, letters in _LETTERS.items():
        scores[lang] += sum(low.count(c) for c in letters) * 0.5
    best = max(scores, key=lambda k: scores[k])
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < 1 or ranked[0] == ranked[1]:
        return None
    return best


def page_language(text: str) -> str | None:
    return detect(text)


def field_language(label: str, value: str | None, page_lang: str | None) -> str | None:
    """A field's language (FR-9.2). The label decides, since values are often IDs or names.

    A short Latin-script label ("Name", "Total") reads as several languages, so it takes the page's
    language when that is a Latin-script one. A label in another script decides on its own: that
    is how a Korean label on an English page gets "ko".
    """
    own = detect(label)
    latin_label = scripts(label).most_common(1)[0][0] == "Latin" if scripts(label) else True
    short = len(_TOKEN.findall(label)) <= 2
    if latin_label and short and page_lang in _WORDS:
        return page_lang
    return own or page_lang or detect(value or "")
