from helpers.shares import compute_shares_outstanding


def test_prefers_market_cap_over_price():
    quote = {"marketCap": 3_000_000_000_000, "price": 190.5}
    shares, source = compute_shares_outstanding(quote, [])
    assert shares == 3_000_000_000_000 / 190.5
    assert source == "marketCap / price (latest quote)"


def test_falls_back_to_weighted_average_shares_when_quote_incomplete():
    quote = {"marketCap": None, "price": 190.5}
    income_quarterly = [{"weightedAverageShsOutDil": 15_000_000_000}]
    shares, source = compute_shares_outstanding(quote, income_quarterly)
    assert shares == 15_000_000_000
    assert source == "weightedAverageShsOutDil (latest quarter, diluted)"


def test_returns_none_when_neither_source_available():
    assert compute_shares_outstanding({}, []) == (None, None)


def test_falls_back_when_price_is_zero():
    quote = {"marketCap": 3_000_000_000_000, "price": 0}
    income_quarterly = [{"weightedAverageShsOutDil": 15_000_000_000}]
    shares, source = compute_shares_outstanding(quote, income_quarterly)
    assert shares == 15_000_000_000
    assert source == "weightedAverageShsOutDil (latest quarter, diluted)"
