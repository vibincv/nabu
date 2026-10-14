"""FR-9.6 value-type rules, value-type inference (FR-4.1) and language detection (FR-9.1, 9.2)."""

import pytest

from nabu.fields import values
from nabu.lang import detect


@pytest.mark.parametrize("text, region, iso, ambiguous", [
    ("2026-10-01", None, "2026-10-01", False),
    ("2026년 10월 1일", None, "2026-10-01", False),
    ("01.10.2026", "DE", "2026-10-01", False),
    ("10/01/2026", "US", "2026-10-01", False),
    ("01/02/2026", None, None, True),  # FR-9.6: no region, cannot tell -> needs review
    ("15.10.2026", None, "2026-10-15", False),  # only one valid reading
    ("05.05.2026", "US", "2026-05-05", False),  # same both ways
    ("13/10/2026", "US", None, True),  # contradicts the region's order
    ("01.10.26", "DE", "2026-10-01", False),
])
def test_dates(text, region, iso, ambiguous):
    d = values.parse_date(text, region)
    assert d is not None and d.iso == iso and d.ambiguous == ambiguous


@pytest.mark.parametrize("text", ["RE-2026-0412", "31.02.2026", "hello", "2026"])
def test_not_dates(text):
    assert values.parse_date(text, "DE") is None


@pytest.mark.parametrize("text, region, number, currency", [
    ("1.428,00 €", "DE", "1428.00", "EUR"),
    ("1,428.00 EUR", None, "1428.00", "EUR"),
    ("€ 12,5", None, "12.50", "EUR"),
    ("$1,234.56", "US", "1234.56", "USD"),
    ("$1,234.56", None, "1234.56", None),  # "$" alone needs the region
    ("₩50,000", None, "50000", "KRW"),
    ("50,000원", None, "50000", "KRW"),
    ("1 428,00 EUR", "FR", "1428.00", "EUR"),
    ("CHF 1'428.50", None, "1428.50", "CHF"),
])
def test_amounts(text, region, number, currency):
    a = values.parse_amount(text, region)
    assert a is not None and (a.number, a.currency) == (number, currency)


@pytest.mark.parametrize("text", ["1428", "RE-2026-0412", "Total EUR", "1.2.3 EUR"])
def test_not_amounts(text):
    assert values.parse_amount(text, None) is None


@pytest.mark.parametrize("value, kind", [
    ("01.10.2026", "date"), ("1.428,00 €", "amount"), ("1428", "number"), ("12,5 %", "number"),
    ("RE-2026-0412", "id"), ("010-0000-0000", "id"), ("Beispiel GmbH", "text"), ("", "text"),
    (None, "text"),
])
def test_infer(value, kind):
    assert values.infer(value) == kind


@pytest.mark.parametrize("text, lang", [
    ("Rechnungsnummer und Datum der Rechnung", "de"),
    ("The invoice number and the date", "en"),
    ("성명 생년월일 주소", "ko"),
    ("Numéro de facture et adresse du client", "fr"),
    ("Номер счёта", "ru"),
    ("RE-2026-0412", None),
    ("", None),
])
def test_detect(text, lang):
    assert detect.detect(text) == lang


def test_field_language_follows_the_page_for_short_latin_labels():
    assert detect.field_language("Name", "Kim", "de") == "de"
    assert detect.field_language("주소", "서울", "en") == "ko"  # mixed document (FR-9.2)
    assert detect.field_language("ID", "A-1", None) is None
