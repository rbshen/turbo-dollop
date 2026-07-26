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
