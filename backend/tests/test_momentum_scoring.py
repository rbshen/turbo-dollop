import pandas as pd
import pytest

from scoring.momentum import compute_momentum_ranking

ANCHOR = pd.Timestamp("2026-08-31")


def _series(start: str, end: str, start_price: float, end_price: float) -> pd.DataFrame:
    """Linearly-interpolated daily close series between two prices, for
    predictable, hand-checkable returns in tests."""
    index = pd.bdate_range(start=start, end=end)
    prices = pd.Series(
        [start_price + (end_price - start_price) * i / (len(index) - 1) for i in range(len(index))],
        index=index,
    )
    return pd.DataFrame({"Close": prices})


def test_composite_is_simple_average_of_three_raw_returns():
    # Flat $100 for 2 years, then a step up to $200 exactly at the anchor
    # date -- so 3mo/6mo/12mo trailing returns are all identical (100%),
    # and the composite must equal that same 100%.
    df = _series("2024-08-01", "2026-08-28", 100.0, 100.0)
    df.loc[ANCHOR] = 200.0
    df = df.sort_index()

    result = compute_momentum_ranking({"FLAT": df}, ANCHOR)

    assert len(result) == 1
    row = result[0]
    assert row.return_3mo == pytest.approx(1.0, abs=1e-6)
    assert row.return_6mo == pytest.approx(1.0, abs=1e-6)
    assert row.return_12mo == pytest.approx(1.0, abs=1e-6)
    assert row.composite_score == pytest.approx(1.0, abs=1e-6)
    assert row.rank == 1


def test_ticker_missing_12mo_history_is_dropped():
    # Only ~7 months of history -- can't compute a 12mo trailing return.
    df = _series("2026-02-01", "2026-08-31", 50.0, 60.0)

    result = compute_momentum_ranking({"THIN": df}, ANCHOR)

    assert result == []


def test_ticker_with_no_data_on_or_before_anchor_is_dropped():
    # Every row postdates the anchor -- e.g. a ticker whose price history
    # starts after the month this snapshot is for.
    df = _series("2026-09-01", "2026-09-30", 100.0, 110.0)

    result = compute_momentum_ranking({"GAP": df}, ANCHOR)

    assert result == []


def test_ranking_order_descending_with_alphabetical_tiebreak():
    high = _series("2024-08-01", "2026-08-31", 100.0, 300.0)  # strong growth
    low = _series("2024-08-01", "2026-08-31", 100.0, 110.0)  # weak growth
    tie_a = _series("2024-08-01", "2026-08-31", 100.0, 150.0)
    tie_b = _series("2024-08-01", "2026-08-31", 100.0, 150.0)  # identical composite to tie_a

    result = compute_momentum_ranking({"ZEBRA": tie_b, "ALPHA": tie_a, "HIGH": high, "LOW": low}, ANCHOR)

    tickers_in_order = [row.ticker for row in result]
    assert tickers_in_order == ["HIGH", "ALPHA", "ZEBRA", "LOW"]
    assert [row.rank for row in result] == [1, 2, 3, 4]


def test_empty_input_returns_empty_list():
    assert compute_momentum_ranking({}, ANCHOR) == []
