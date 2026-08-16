# Reverse splits on major exchanges essentially never exceed low-double-
# digit ratios (even distressed penny stocks rarely go beyond ~1:100) -- a
# magnitude shift past this multiple in a shares/market-cap/enterprise-value
# field is the signature of an FMP freshly-filed-quarter units defect
# (confirmed real cases: TEAM, FLY -- both ~1000x on their latest quarter,
# 2026-08-16 investigation), not a plausible corporate action.
MAGNITUDE_SHIFT_RATIO_THRESHOLD = 100.0


def is_implausible_magnitude_shift(current: float | None, reference: float | None) -> bool:
    """True when `current` differs from `reference` by more than
    MAGNITUDE_SHIFT_RATIO_THRESHOLD in either direction. Used to guard
    shares-outstanding/market-cap/enterprise-value fields against FMP's
    freshly-filed-quarter units defect -- never used to auto-correct
    (auto-scaling risks misfiring on a genuine, if rare, reverse split),
    only to suppress display of an untrustworthy value."""
    if not current or not reference:
        return False
    ratio = current / reference
    return ratio > MAGNITUDE_SHIFT_RATIO_THRESHOLD or ratio < 1 / MAGNITUDE_SHIFT_RATIO_THRESHOLD


def compute_shares_outstanding(quote: dict, income_quarterly: list[dict]) -> tuple[float | None, str | None]:
    """Prefers marketCap/price (both instant quote-level figures, per Step 3
    spec gotcha #2's "most recent instant" rule) over the income statement's
    weightedAverageShsOutDil, which is a period-average flow figure, not an
    instant share count -- used only as a fallback when quote data is
    incomplete. Shared by Step 3 (step3_data.py) and the ticker header
    (ticker_summary.py) so the two can never disagree -- /stable/profile has
    no sharesOutstanding field on our FMP plan (confirmed empirically), so
    this derivation is the only source either call site has."""
    market_cap, price = quote.get("marketCap"), quote.get("price")
    if market_cap and price:
        return market_cap / price, "marketCap / price (latest quote)"
    latest_quarter = income_quarterly[0] if income_quarterly else {}
    shares = latest_quarter.get("weightedAverageShsOutDil")
    if shares:
        return shares, "weightedAverageShsOutDil (latest quarter, diluted)"
    return None, None
