import asyncio
from datetime import date

import pytest

import data.chart_events_data as ced
from data.chart_events_data import (
    ChartEvents,
    DividendEvent,
    EarningsEvent,
    fetch_chart_events,
    normalize_fmp_dividends,
    normalize_fmp_earnings,
)

# ---------------------------------------------------------------- normalizers


def test_fmp_earnings_keeps_only_reported_rows_oldest_first():
    rows = [
        # next scheduled date: null actuals -> not a report that happened
        {"date": "2026-10-29", "epsActual": None, "epsEstimated": 1.9, "revenueActual": None},
        {"date": "2026-07-30", "epsActual": 1.8, "epsEstimated": 1.7, "revenueActual": 100.0},
        {"date": "2026-04-30", "epsActual": 1.5, "epsEstimated": None, "revenueActual": 90.0},
    ]

    out = normalize_fmp_earnings(rows)

    assert out == [
        EarningsEvent(date(2026, 4, 30), 1.5, None),
        EarningsEvent(date(2026, 7, 30), 1.8, 1.7),
    ]


def test_fmp_earnings_drops_all_null_placeholder_history_like_spy():
    rows = [{"date": f"{y}-02-15", "epsActual": None, "epsEstimated": None, "revenueActual": None} for y in range(2005, 2017)]

    assert normalize_fmp_earnings(rows) == []


def test_fmp_earnings_revenue_only_actual_still_counts_as_reported():
    rows = [{"date": "2026-01-20", "epsActual": None, "epsEstimated": 0.5, "revenueActual": 55.0}]

    assert normalize_fmp_earnings(rows) == [EarningsEvent(date(2026, 1, 20), None, 0.5)]


def test_fmp_earnings_skips_malformed_rows_without_raising():
    rows = [{"epsActual": 1.0}, {"date": "not-a-date", "epsActual": 1.0}, "junk", {"date": "2026-01-20", "epsActual": 2.0}]

    assert normalize_fmp_earnings(rows) == [EarningsEvent(date(2026, 1, 20), 2.0, None)]


@pytest.mark.parametrize("normalizer", [normalize_fmp_earnings, normalize_fmp_dividends])
def test_fmp_non_list_body_raises_so_it_is_not_read_as_no_events(normalizer):
    with pytest.raises(ValueError):
        normalizer({"Error Message": "Limit Reach"})


def test_fmp_dividends_prefer_split_adjusted_amount():
    rows = [
        {"date": "2019-08-09", "dividend": 0.77, "adjDividend": 0.1925},
        {"date": "2026-08-10", "dividend": 0.27, "adjDividend": 0.27},
    ]

    out = normalize_fmp_dividends(rows)

    assert out == [DividendEvent(date(2019, 8, 9), 0.1925), DividendEvent(date(2026, 8, 10), 0.27)]


def test_fmp_dividends_fall_back_to_declared_amount_and_drop_non_positive():
    rows = [
        {"date": "2026-01-05", "dividend": 0.4},  # no adjDividend at all
        {"date": "2026-02-05", "dividend": 0.0, "adjDividend": 0.0},
        {"date": "2026-03-05", "dividend": None, "adjDividend": None},
        {"date": "2026-04-05", "dividend": -1.0, "adjDividend": -1.0},
    ]

    assert normalize_fmp_dividends(rows) == [DividendEvent(date(2026, 1, 5), 0.4)]


def test_fmp_dividends_use_the_ex_date_field_and_keep_future_declared_rows():
    # `date` is the ex-date (not recordDate/paymentDate); future rows survive
    # normalization -- windowing is the marker builder's job.
    rows = [{"date": "2099-01-02", "recordDate": "2099-01-03", "paymentDate": "2099-01-20", "dividend": 1.0, "adjDividend": 1.0}]

    assert normalize_fmp_dividends(rows) == [DividendEvent(date(2099, 1, 2), 1.0)]


# ---------------------------------------------------------------- fetch (cache is the sole source)


def test_fetch_chart_events_returns_what_the_cache_holds(monkeypatch):
    cached = ChartEvents([EarningsEvent(date(2026, 7, 30), 1.8, 1.7)], [DividendEvent(date(2026, 8, 10), 0.27)], "fmp")
    monkeypatch.setattr("data.corporate_events_data.read_cached_chart_events", lambda ticker: cached)

    assert asyncio.run(fetch_chart_events("AAPL")) == cached


def test_an_uncached_ticker_reads_as_no_events_with_no_network_call(monkeypatch):
    monkeypatch.setattr("data.corporate_events_data.read_cached_chart_events", lambda ticker: None)

    out = asyncio.run(fetch_chart_events("UNCACHED"))

    assert out == ChartEvents(earnings=[], dividends=[], source=None)


def test_a_cache_read_error_yields_source_none_and_never_raises(monkeypatch, caplog):
    def broken(ticker):
        raise RuntimeError("db locked")

    monkeypatch.setattr("data.corporate_events_data.read_cached_chart_events", broken)

    with caplog.at_level("WARNING"):
        out = asyncio.run(fetch_chart_events("AAPL"))

    assert out == ChartEvents(earnings=[], dividends=[], source=None)
    assert "RuntimeError" in caplog.text


def test_the_module_has_no_yahoo_or_live_fmp_path_left():
    assert not hasattr(ced, "yahoo_client") and not hasattr(ced, "fmp_client")
    assert not hasattr(ced, "normalize_yahoo_earnings") and not hasattr(ced, "normalize_yahoo_dividends")
