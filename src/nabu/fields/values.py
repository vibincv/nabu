"""Value shapes: type inference from the value alone, and the FR-9.6 conversions. M1.

Inference looks only at the value's shape (dates, amounts, numbers, IDs). It never looks at field
names: no code names a document type or field (NFR-10). Names and addresses cannot be told from
shape; digital discovery calls them "text", and the translation step keeps short text as printed
(see nabu.lang.translate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from nabu.model.types import ValueType

# Currency marks -> ISO 4217. Only marks that name one currency; "$" alone is ambiguous and is
# resolved by region.
_SYMBOLS = {"€": "EUR", "£": "GBP", "₩": "KRW", "¥": "JPY", "₹": "INR", "₽": "RUB", "₺": "TRY",
            "₫": "VND", "₪": "ILS", "฿": "THB", "원": "KRW", "円": "JPY", "元": "CNY", "zł": "PLN",
            "kr": None, "Fr.": "CHF", "CHF": "CHF"}
_DOLLAR_BY_REGION = {"US": "USD", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "SG": "SGD", "HK": "HKD",
                     "MX": "MXN"}
_KR_BY_REGION = {"SE": "SEK", "NO": "NOK", "DK": "DKK"}
_ISO = re.compile(r"\b([A-Z]{3})\b")
_KNOWN_ISO = frozenset("EUR USD GBP KRW JPY CNY CHF CAD AUD NZD SGD HKD INR RUB TRY VND ILS THB PLN "
                       "SEK NOK DKK CZK HUF MXN BRL ZAR AED SAR".split())
_NUM = r"[-+]?\d[\d.,'   ]*\d|[-+]?\d"
_AMOUNT = re.compile(
    rf"^\s*(?P<pre>[^\d\s+-]{{1,3}}|[A-Z]{{3}})?\s*(?P<num>{_NUM})\s*(?P<post>[^\d\s]{{1,3}}|[A-Z]{{3}})?\s*$")
_NUMBER = re.compile(rf"^\s*(?:{_NUM})\s*%?\s*$")

# Dates. Order matters: unambiguous year-first forms before day/month forms.
_YMD = re.compile(r"^\s*(\d{4})[-./](\d{1,2})[-./](\d{1,2})\.?\s*$")
_KO = re.compile(r"^\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*$")
_DMY = re.compile(r"^\s*(\d{1,2})[-./](\d{1,2})[-./](\d{2}|\d{4})\.?\s*$")
# Regions that write month first (en-US style). Everyone else is day first.
MONTH_FIRST = frozenset({"US", "PH", "FM", "MH", "PW", "GU", "AS", "MP", "PR", "VI", "BZ"})
# Languages whose regions all write day first: with no region set, the language decides the order
# (owner decision 2026-10-14). English is not here (US is month first), so it stays ambiguous.
DAY_FIRST_LANGS = frozenset({"de", "fr", "es", "it", "pt", "nl"})

_ID = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9/._#-]*$")


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if len(y) == 2 and n < 70 else n + 1900 if len(y) == 2 else n


def _valid(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


@dataclass(frozen=True)
class DateParse:
    iso: str | None  # None when the date cannot be resolved
    ambiguous: bool  # day-month order unknown (FR-9.6: keep printed form, needs review)


def _month_first(region: str | None, lang: str | None) -> bool | None:
    """The day-month order: the region decides, else the language; None when unknown."""
    if region is not None:
        return region in MONTH_FIRST
    if lang in DAY_FIRST_LANGS:
        return False
    return None


def parse_date(text: str, region: str | None, lang: str | None = None) -> DateParse | None:
    """None when `text` is not a date. Otherwise the ISO form, or ambiguous."""
    for rx in (_YMD, _KO):
        m = rx.match(text)
        if m:
            d = _valid(int(m[1]), int(m[2]), int(m[3]))
            return DateParse(d.isoformat(), False) if d else None
    m = _DMY.match(text)
    if not m:
        return None
    a, b, y = int(m[1]), int(m[2]), _year(m[3])
    as_dmy, as_mdy = _valid(y, b, a), _valid(y, a, b)
    if not as_dmy and not as_mdy:
        return None
    month_first = _month_first(region, lang)
    if as_dmy and as_mdy:
        if as_dmy == as_mdy:  # 05.05.2026 reads the same both ways
            return DateParse(as_dmy.isoformat(), False)
        if month_first is None:
            return DateParse(None, True)
        chosen = as_mdy if month_first else as_dmy
        return DateParse(chosen.isoformat(), False)
    one = as_dmy or as_mdy
    assert one is not None
    if month_first is not None and (as_mdy if month_first else as_dmy) is None:
        # the only valid reading contradicts the known order: a misprint or a wrong region/language
        return DateParse(None, True)
    return DateParse(one.isoformat(), False)


@dataclass(frozen=True)
class AmountParse:
    number: str | None  # "1428.00"
    currency: str | None  # ISO 4217


def _currency(mark: str | None, region: str | None) -> str | None:
    if not mark:
        return None
    mark = mark.strip()
    if mark in _KNOWN_ISO:
        return mark
    if mark in ("$", "US$"):
        return "USD" if mark == "US$" else _DOLLAR_BY_REGION.get(region or "")
    if mark == "kr":
        return _KR_BY_REGION.get(region or "")
    return _SYMBOLS.get(mark)


def parse_number(num: str) -> str | None:
    """Decimal string from a printed number, honouring the source's separators (FR-9.6).

    The last separator followed by 1-2 digits (or exactly 3 with another separator kind before it)
    is the decimal mark; the others group thousands. "1.428,00" -> "1428.00", "1,428.00" ->
    "1428.00", "1 428" -> "1428". A lone separator followed by exactly 3 digits ("1.428") is a
    thousands group, the common reading for amounts.
    """
    s = re.sub(r"[ '  ]", "", num.strip())
    sign = ""
    if s[:1] in "+-":
        sign, s = ("-" if s[0] == "-" else ""), s[1:]
    if not s or not re.fullmatch(r"\d[\d.,]*", s):
        return None
    seps = [(i, c) for i, c in enumerate(s) if c in ".,"]
    if not seps:
        return sign + s
    last_i, last_c = seps[-1]
    tail = s[last_i + 1:]
    kinds = {c for _, c in seps}
    if len(kinds) == 2 or (len(tail) in (1, 2)) or (len(seps) == 1 and len(tail) != 3):
        decimal = last_c
    else:
        decimal = None  # all separators group thousands
    if decimal and sum(1 for _, c in seps if c == decimal) > 1:
        return None  # "1.2.3" style: not a number
    intpart = s[:last_i] if decimal else s
    frac = tail if decimal else ""
    groups = re.split(r"[.,]", intpart)
    if len(groups) > 1 and any(len(g) != 3 for g in groups[1:]):
        return None  # separators in odd places: not a clean number
    digits = "".join(groups)
    if not digits:
        return None
    return sign + digits + ("." + frac if frac else "")


def parse_amount(text: str, region: str | None) -> AmountParse | None:
    """None when `text` is not an amount (a number with a currency mark)."""
    m = _AMOUNT.match(text)
    if not m or not (m["pre"] or m["post"]):
        return None
    pre, post = m["pre"], m["post"]
    cur = _currency(pre, region) or _currency(post, region)
    if (pre and _currency(pre, region) is None and pre not in ("$", "kr")) and \
            (post and _currency(post, region) is None and post not in ("$", "kr")):
        return None
    if cur is None and not any(x in ("$", "kr") for x in (pre, post)):
        return None
    number = parse_number(m["num"])
    if number is None:
        return None
    if "." in number and len(number.split(".")[1]) == 1:
        number += "0"
    elif "." not in number and cur not in ("KRW", "JPY", "VND", None):
        number += ".00"
    return AmountParse(number, cur)


def infer(value: str | None) -> ValueType:
    """Value type from the value's shape alone (FR-4.1)."""
    if not value or not value.strip():
        return "text"
    v = value.strip()
    if parse_date(v, None) is not None:
        return "date"
    if parse_amount(v, None) is not None:
        return "amount"
    if _NUMBER.match(v):
        return "number"
    if _ID.match(v) and len(v) >= 3:
        return "id"
    return "text"
