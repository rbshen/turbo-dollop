import asyncio
from datetime import date

import httpx
import pandas as pd
import pytest

import data.chart_events_data as ced
from data.chart_events_data import (
    ChartEvents,
    DividendEvent,
    EarningsEvent,
    fetch_chart_events,
    normalize_fmp_dividends,
    normalize_fmp_earnings,
    normalize_yahoo_dividends,
    normalize_yahoo_earnings,
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
def test_fmp_non_list_body_raises_so_the_caller_falls_back(normalizer):
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


def test_yahoo_earnings_uses_local_calendar_date_and_skips_unreported():
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-10-29 16:00", tz="America/New_York"),  # scheduled
            pd.Timestamp("2026-07-30 16:00", tz="America/New_York"),
        ]
    )
    frame = pd.DataFrame({"EPS Estimate": [1.9, 1.7], "Reported EPS": [float("nan"), 1.8], "Surprise(%)": [None, 5.9]}, index=idx)

    # A 16:00 ET stamp is 20:00 UTC -- the local date must survive, not roll.
    assert normalize_yahoo_earnings(frame) == [EarningsEvent(date(2026, 7, 30), 1.8, 1.7)]


def test_yahoo_earnings_handles_empty_and_missing_estimate_column():
    assert normalize_yahoo_earnings(pd.DataFrame()) == []
    idx = pd.DatetimeIndex([pd.Timestamp("2026-07-30", tz="America/New_York")])
    frame = pd.DataFrame({"Reported EPS": [2.0]}, index=idx)

    assert normalize_yahoo_earnings(frame) == [EarningsEvent(date(2026, 7, 30), 2.0, None)]


def test_yahoo_dividends_normalize_and_drop_non_positive():
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-05-11", tz="America/New_York"), pd.Timestamp("2026-08-10", tz="America/New_York"), pd.Timestamp("2026-09-01", tz="America/New_York")]
    )
    series = pd.Series([0.27, 0.27, 0.0], index=idx)

    assert normalize_yahoo_dividends(series) == [DividendEvent(date(2026, 5, 11), 0.27), DividendEvent(date(2026, 8, 10), 0.27)]
    assert normalize_yahoo_dividends(pd.Series(dtype=float)) == []


# ---------------------------------------------------------------- fetch/fallback

_FMP_EARNINGS = [{"date": "2026-07-30", "epsActual": 1.8, "epsEstimated": 1.7, "revenueActual": 1.0}]
_FMP_DIVS = [{"date": "2026-08-10", "dividend": 0.27, "adjDividend": 0.27}]


def _yahoo_frames():
    e_idx = pd.DatetimeIndex([pd.Timestamp("2026-07-30 16:00", tz="America/New_York")])
    d_idx = pd.DatetimeIndex([pd.Timestamp("2026-08-10", tz="America/New_York")])
    return (
        pd.DataFrame({"EPS Estimate": [1.7], "Reported EPS": [1.8]}, index=e_idx),
        pd.Series([0.27], index=d_idx),
    )


def _patch_fmp(monkeypatch, *, earnings=_FMP_EARNINGS, dividends=_FMP_DIVS, error: Exception | None = None):
    calls = {"earnings": 0, "dividends": 0}

    async def fake_earnings(ticker, limit=40):
        calls["earnings"] += 1
        if error:
            raise error
        return earnings

    async def fake_dividends(ticker, limit=400):
        calls["dividends"] += 1
        if error:
            raise error
        return dividends

    monkeypatch.setattr(ced.fmp_client, "get_earnings_history", fake_earnings)
    monkeypatch.setattr(ced.fmp_client, "get_dividends", fake_dividends)
    return calls


def _patch_yahoo(monkeypatch, *, earnings_error: Exception | None = None, dividends_error: Exception | None = None):
    calls = {"earnings": 0, "dividends": 0}
    e_frame, d_series = _yahoo_frames()

    async def fake_earnings(ticker, limit=40):
        calls["earnings"] += 1
        if earnings_error:
            raise earnings_error
        return e_frame

    async def fake_dividends(ticker):
        calls["dividends"] += 1
        if dividends_error:
            raise dividends_error
        return d_series

    monkeypatch.setattr(ced.yahoo_client, "get_earnings_dates", fake_earnings)
    monkeypatch.setattr(ced.yahoo_client, "get_dividends", fake_dividends)
    return calls


def test_uses_fmp_when_enabled_and_never_touches_yahoo(monkeypatch):
    monkeypatch.setattr(ced.settings, "fmp_enabled", True)
    fmp_calls = _patch_fmp(monkeypatch)
    yahoo_calls = _patch_yahoo(monkeypatch)

    out = asyncio.run(fetch_chart_events("AAPL"))

    assert out.source == "fmp"
    assert out.earnings == [EarningsEvent(date(2026, 7, 30), 1.8, 1.7)]
    assert out.dividends == [DividendEvent(date(2026, 8, 10), 0.27)]
    assert fmp_calls == {"earnings": 1, "dividends": 1}
    assert yahoo_calls == {"earnings": 0, "dividends": 0}


def test_fmp_disabled_goes_straight_to_yahoo_with_zero_fmp_calls(monkeypatch):
    monkeypatch.setattr(ced.settings, "fmp_enabled", False)
    fmp_calls = _patch_fmp(monkeypatch)
    _patch_yahoo(monkeypatch)

    out = asyncio.run(fetch_chart_events("AAPL"))

    assert out.source == "yahoo"
    assert out.earnings == [EarningsEvent(date(2026, 7, 30), 1.8, 1.7)]
    assert out.dividends == [DividendEvent(date(2026, 8, 10), 0.27)]
    assert fmp_calls == {"earnings": 0, "dividends": 0}


def test_fmp_http_error_falls_back_to_yahoo(monkeypatch):
    monkeypatch.setattr(ced.settings, "fmp_enabled", True)
    _patch_fmp(monkeypatch, error=httpx.HTTPError("402 Payment Required"))
    _patch_yahoo(monkeypatch)

    out = asyncio.run(fetch_chart_events("AAPL"))

    assert out.source == "yahoo"
    assert len(out.earnings) == 1 and len(out.dividends) == 1


def test_fmp_error_payload_falls_back_to_yahoo(monkeypatch):
    monkeypatch.setattr(ced.settings, "fmp_enabled", True)
    _patch_fmp(monkeypatch, earnings={"Error Message": "bad"})
    _patch_yahoo(monkeypatch)

    assert asyncio.run(fetch_chart_events("AAPL")).source == "yahoo"


def test_fmp_empty_lists_are_a_real_answer_not_a_reason_to_fall_back(monkeypatch):
    # TSLA-shape: no dividends. An empty FMP result is authoritative -- calling
    # Yahoo for every non-payer would just double the calls.
    monkeypatch.setattr(ced.settings, "fmp_enabled", True)
    _patch_fmp(monkeypatch, dividends=[])
    yahoo_calls = _patch_yahoo(monkeypatch)

    out = asyncio.run(fetch_chart_events("TSLA"))

    assert out.source == "fmp"
    assert out.dividends == []
    assert yahoo_calls == {"earnings": 0, "dividends": 0}


def test_yahoo_tolerates_one_kind_failing(monkeypatch):
    monkeypatch.setattr(ced.settings, "fmp_enabled", False)
    _patch_yahoo(monkeypatch, earnings_error=RuntimeError("no earnings calendar"))

    out = asyncio.run(fetch_chart_events("SPY"))

    assert out.source == "yahoo"
    assert out.earnings == []
    assert out.dividends == [DividendEvent(date(2026, 8, 10), 0.27)]


def test_every_source_failing_yields_source_none_and_never_raises(monkeypatch):
    monkeypatch.setattr(ced.settings, "fmp_enabled", True)
    _patch_fmp(monkeypatch, error=httpx.ConnectError("boom"))
    _patch_yahoo(monkeypatch, earnings_error=RuntimeError("x"), dividends_error=RuntimeError("y"))

    out = asyncio.run(fetch_chart_events("AAPL"))

    assert out == ChartEvents(earnings=[], dividends=[], source=None)


def test_a_hung_source_is_cut_off_by_the_timeout(monkeypatch):
    monkeypatch.setattr(ced.settings, "fmp_enabled", True)
    monkeypatch.setattr(ced, "EVENTS_FETCH_TIMEOUT_SECONDS", 0.05)

    async def hang(ticker, limit=40):
        await asyncio.sleep(5)

    monkeypatch.setattr(ced.fmp_client, "get_earnings_history", hang)
    monkeypatch.setattr(ced.fmp_client, "get_dividends", hang)

    out = asyncio.run(fetch_chart_events("AAPL"))

    assert out.source is None


def test_failure_log_never_includes_the_exception_message(monkeypatch, caplog):
    # httpx error messages embed the request URL (apikey included).
    monkeypatch.setattr(ced.settings, "fmp_enabled", True)
    _patch_fmp(monkeypatch, error=httpx.HTTPError("https://x/earnings?apikey=SECRET"))
    _patch_yahoo(monkeypatch)

    with caplog.at_level("WARNING"):
        asyncio.run(fetch_chart_events("AAPL"))

    assert "SECRET" not in caplog.text
