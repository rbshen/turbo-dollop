"""Trailing P/E for TickerSummaryOut.pe_ratio / TickerScore.pe_ratio (docs/specs/overview.md,
"P/E basis"). Pure -- no DB, no FMP; data/ticker_summary.py feeds it already-loaded cache rows."""

TTM_EPS_FIELD = "netIncomePerShareTTM"
TTM_PE_FIELD = "priceToEarningsRatioTTM"


def is_adr_currency_mismatch(reported_currency: str | None, quote_currency: str | None) -> bool:
    """True when both currencies are known and differ (a US-listed ADR of a foreign reporter,
    e.g. TSM: reports TWD, quotes USD). Detected from the two fields, never a ticker list. A
    missing currency is NOT a mismatch -- the standard formula applies."""
    return bool(reported_currency) and bool(quote_currency) and reported_currency != quote_currency


def compute_trailing_pe(
    ratios_ttm: dict,
    price: float | None,
    reported_currency: str | None,
    quote_currency: str | None,
) -> float | None:
    """Trailing (TTM) P/E, or None when it has no meaningful value.

    Standard rule: `price` / FMP TTM EPS (`netIncomePerShareTTM` off the cached `ratios/ttm` row).
    None when EPS is missing, zero or negative, or there is no positive price -- a negative
    multiple is not a P/E (it let loss-makers pass a max-only P/E filter).

    ADR rule (reported_currency != quote_currency, both known): price over EPS would mix currencies
    (and possibly an ADR ratio), so FMP's own `priceToEarningsRatioTTM` is used instead; None if it
    is missing, zero or negative. If either currency is unknown the standard rule is used."""
    if is_adr_currency_mismatch(reported_currency, quote_currency):
        fmp_pe = ratios_ttm.get(TTM_PE_FIELD)
        return fmp_pe if isinstance(fmp_pe, (int, float)) and fmp_pe > 0 else None

    eps = ratios_ttm.get(TTM_EPS_FIELD)
    if not isinstance(eps, (int, float)) or eps <= 0:
        return None
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    return price / eps
