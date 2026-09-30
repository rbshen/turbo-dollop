"""helpers/trailing_pe.py -- the Screener/ticker-header trailing P/E rule (docs/specs/overview.md,
"P/E basis"). Pure function, so no engine/FMP isolation is needed; no dates involved."""

import pytest

from helpers.trailing_pe import compute_trailing_pe, is_adr_currency_mismatch

ROW = {"netIncomePerShareTTM": 8.0, "priceToEarningsRatioTTM": 41.0}


def test_normal_case_is_price_over_ttm_eps():
    assert compute_trailing_pe(ROW, 200.0, "USD", "USD") == pytest.approx(25.0)


def test_usd_reporter_with_matching_currencies_uses_the_standard_formula_not_fmps_ratio():
    # 200 / 8 = 25, not FMP's own 41.0 -- the ADR branch must not fire when the currencies match.
    assert compute_trailing_pe(ROW, 200.0, "USD", "USD") != ROW["priceToEarningsRatioTTM"]


@pytest.mark.parametrize("eps", [0, 0.0, -0.01, -3.5])
def test_zero_or_negative_eps_is_none(eps):
    assert compute_trailing_pe({"netIncomePerShareTTM": eps}, 200.0, "USD", "USD") is None


def test_missing_eps_is_none():
    assert compute_trailing_pe({}, 200.0, "USD", "USD") is None
    assert compute_trailing_pe({"netIncomePerShareTTM": None}, 200.0, "USD", "USD") is None


@pytest.mark.parametrize("price", [None, 0, -1.0])
def test_missing_or_non_positive_price_is_none(price):
    assert compute_trailing_pe(ROW, price, "USD", "USD") is None


def test_adr_uses_fmps_own_ttm_pe_and_ignores_price_and_eps():
    # Reported TWD, quoted USD: price/EPS would mix currencies, so FMP's ratio is used verbatim.
    row = {"netIncomePerShareTTM": 431.37, "priceToEarningsRatioTTM": 27.99}
    assert compute_trailing_pe(row, 452.88, "TWD", "USD") == 27.99


@pytest.mark.parametrize("fmp_pe", [-4.2, 0, 0.0, None])
def test_adr_fallback_that_is_negative_zero_or_missing_is_none(fmp_pe):
    row = {"netIncomePerShareTTM": 5.0, "priceToEarningsRatioTTM": fmp_pe}
    assert compute_trailing_pe(row, 100.0, "DKK", "USD") is None


def test_adr_with_no_ttm_row_at_all_is_none():
    assert compute_trailing_pe({}, 100.0, "CNY", "USD") is None


def test_adr_fallback_does_not_need_a_price():
    assert compute_trailing_pe(ROW, None, "EUR", "USD") == 41.0


@pytest.mark.parametrize("reported", [None, ""])
def test_unknown_reported_currency_uses_the_standard_formula(reported):
    assert compute_trailing_pe(ROW, 200.0, reported, "USD") == pytest.approx(25.0)


def test_unknown_quote_currency_uses_the_standard_formula():
    assert compute_trailing_pe(ROW, 200.0, "TWD", None) == pytest.approx(25.0)


@pytest.mark.parametrize(
    "reported, quote, expected",
    [
        ("TWD", "USD", True),
        ("EUR", "USD", True),
        ("USD", "USD", False),
        (None, "USD", False),
        ("TWD", None, False),
        (None, None, False),
    ],
)
def test_adr_detection_needs_both_currencies_known_and_different(reported, quote, expected):
    assert is_adr_currency_mismatch(reported, quote) is expected
