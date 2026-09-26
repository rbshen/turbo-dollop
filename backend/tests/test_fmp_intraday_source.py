"""P4: FMP `/historical-chart/1hour` as the primary 60m source for Warren/BB+RSI --
FMPIntradaySource / FMPIntradayWithFallback and their wiring into the shared bars cache."""

import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.daily_bar_sources as dbs
import clients.shared_bars_cache as cache
import core.data_groups as dg
from clients.daily_bar_sources import (
    FMPIntradaySource,
    FMPIntradayWithFallback,
    FallbackTickers,
    find_short_sessions,
    fmp_intraday_rows_to_frame,
)
from core.models import SharedBarsCache

# Friday 2026-09-25, 17:00 ET: the whole session is complete (last bar 15:30).
REF = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 25)
HOURS = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]


@pytest.fixture(autouse=True)
def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(dbs, "engine", engine)
    monkeypatch.setattr(cache, "engine", engine)
    return engine


def _sessions(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _bars(start: date, end: date, base: float = 100.0, bars_per_day: int = 7) -> list[tuple[datetime, float]]:
    out, i = [], 0
    for d in _sessions(start, end):
        for h, m in HOURS[:bars_per_day]:
            out.append((datetime(d.year, d.month, d.day, h, m), base + i * 0.01))
            i += 1
    return out


class FakeChart:
    """Serves FMP-shaped pages: newest first, capped at `page` rows, filtered by from/to (dates,
    inclusive)."""

    def __init__(self, bars, page=100, fail=False):
        self.bars, self.page, self.fail = bars, page, fail
        self.calls: list[tuple[str, str, str]] = []

    async def get_historical_chart_1hour(self, ticker, from_date, to_date):
        self.calls.append((ticker, from_date, to_date))
        if self.fail:
            raise httpx.ConnectError("boom")
        lo, hi = date.fromisoformat(from_date), date.fromisoformat(to_date)
        rows = [
            {"date": ts.strftime("%Y-%m-%d %H:%M:%S"), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000}
            for ts, c in self.bars
            if lo <= ts.date() <= hi
        ]
        return sorted(rows, key=lambda r: r["date"], reverse=True)[: self.page]


def _seed(engine, ticker, bars, source):
    with Session(engine) as session:
        for ts, c in bars:
            session.add(SharedBarsCache(
                ticker=ticker, interval="60m", bar_time=ts, open=c, high=c, low=c, close=c, volume=1,
                fetched_at=datetime(2026, 9, 25), source=source,
            ))
        session.commit()


def _run(source, tickers, **kw):
    return asyncio.run(source.get_intraday_bars(tickers, reference=REF, **kw))


# ---- registry / canary ----

def test_intraday_group_is_wired_mapped_and_has_a_canary():
    meta = dg.GROUPS["intraday_bars"]
    assert meta.live and meta.falls_back and meta.default_enabled
    assert dg.ENDPOINT_GROUP["/historical-chart/1hour"] == "intraday_bars"
    assert dg.PROBE_ENDPOINTS["intraday_bars"][0] == "/historical-chart/1hour"
    assert dg.PROBE_ENDPOINTS["intraday_bars"][1]["symbol"] == "AAPL"


# ---- row parsing ----

def test_rows_to_frame_keeps_rth_weekday_bars_only_and_drops_partial_and_dupes():
    def row(ts, c=10.0):
        return {"date": ts, "open": c, "high": c, "low": c, "close": c, "volume": 5}

    rows = [
        row("2026-09-25 15:30:00"), row("2026-09-25 15:30:00"),  # duplicate
        row("2026-09-25 16:30:00"), row("2026-09-25 08:30:00"),  # extended hours
        row("2026-09-26 10:30:00"),                                # Saturday
        row("2026-09-24 09:30:00"),
    ]
    frame = fmp_intraday_rows_to_frame(rows)
    assert list(frame.index) == [pd.Timestamp("2026-09-24 09:30"), pd.Timestamp("2026-09-25 15:30")]
    assert frame.index.tz is None and list(frame.columns) == ["open", "high", "low", "close", "volume"]
    partial = fmp_intraday_rows_to_frame(rows, completed_bar_start=datetime(2026, 9, 24, 15, 30))
    assert list(partial.index) == [pd.Timestamp("2026-09-24 09:30")]


def test_rows_to_frame_tolerates_junk_payloads():
    assert fmp_intraday_rows_to_frame({"Error Message": "x"}).empty
    assert fmp_intraday_rows_to_frame([]).empty


# ---- completeness check ----

def test_short_sessions_expect_7_bars_and_4_on_half_days():
    full = _bars(date(2026, 11, 23), date(2026, 11, 24))
    half = [(datetime(2026, 11, 27, h, m), 1.0) for h, m in HOURS[:4]]  # day after Thanksgiving
    short = [(datetime(2026, 11, 25, h, m), 1.0) for h, m in HOURS[:3]]
    frame = pd.DataFrame({"close": [c for _, c in full + short + half]}, index=pd.DatetimeIndex([t for t, _ in full + short + half]))
    assert find_short_sessions(frame) == [(date(2026, 11, 25), 3, 7)]


def test_in_progress_session_is_not_flagged_but_a_finished_short_one_is():
    frame = pd.DataFrame({"close": [1.0] * 3}, index=pd.DatetimeIndex([datetime(2026, 9, 25, h, m) for h, m in HOURS[:3]]))
    assert find_short_sessions(frame, completed_bar_start=datetime(2026, 9, 25, 11, 30)) == []
    assert find_short_sessions(frame, completed_bar_start=datetime(2026, 9, 25, 15, 30)) == [(date(2026, 9, 25), 3, 7)]


# ---- FMPIntradaySource ----

def test_cold_ticker_pages_back_until_the_window_is_covered_and_is_replaced():
    bars = _bars(date(2026, 6, 1), TODAY)
    fake = FakeChart(bars, page=100)
    replace: list[str] = []
    out = _run(FMPIntradaySource(client=fake), {"AAPL": 90}, replace_tickers=replace)
    assert len(fake.calls) > 2  # genuinely paginated
    in_window = [b for b in bars if b[0].date() >= TODAY - timedelta(days=90)]
    assert len(out["AAPL"]) == len(in_window) > 300  # nothing lost between pages
    assert out["AAPL"].index[0] == pd.Timestamp(in_window[0][0])
    assert replace == ["AAPL"]


def test_pagination_stops_at_the_window_edge_not_one_page_later():
    # A window that fits one page must cost exactly one call (nightly incremental cost).
    fake = FakeChart(_bars(date(2026, 9, 1), TODAY), page=1000)
    _run(FMPIntradaySource(client=fake), {"AAPL": 30})
    assert len(fake.calls) == 1


def test_incremental_is_one_overlapping_call_and_does_not_replace(_engine):
    feed = _bars(date(2026, 6, 1), TODAY)
    _seed(_engine, "AAPL", [b for b in feed if date(2026, 6, 20) <= b[0].date() <= date(2026, 9, 24)], "fmp")
    fake = FakeChart(feed)
    replace: list[str] = []
    out = _run(FMPIntradaySource(client=fake), {"AAPL": 90}, replace_tickers=replace)
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == (date(2026, 9, 24) - timedelta(days=3)).isoformat()
    assert replace == [] and out["AAPL"].index[-1] == pd.Timestamp("2026-09-25 15:30")


def test_restated_overlap_triggers_a_full_refetch_and_replace(_engine):
    feed = _bars(date(2026, 6, 1), TODAY)
    _seed(_engine, "AAPL", [b for b in feed if date(2026, 6, 20) <= b[0].date() <= date(2026, 9, 24)], "fmp")
    fake = FakeChart([(t, c * 2) for t, c in _bars(date(2026, 6, 1), TODAY)], page=1000)  # e.g. a split
    replace: list[str] = []
    out = _run(FMPIntradaySource(client=fake), {"AAPL": 90}, replace_tickers=replace)
    assert replace == ["AAPL"] and len(fake.calls) == 2
    assert out["AAPL"].index[0] < pd.Timestamp("2026-06-25")


@pytest.mark.parametrize("source", [None, "yahoo"])
def test_non_fmp_history_is_fully_replaced_never_layered(_engine, source):
    _seed(_engine, "AAPL", _bars(date(2026, 6, 20), date(2026, 9, 24)), source)
    fake = FakeChart(_bars(date(2026, 6, 1), TODAY), page=1000)
    replace: list[str] = []
    _run(FMPIntradaySource(client=fake), {"AAPL": 90}, replace_tickers=replace)
    assert replace == ["AAPL"]
    assert fake.calls[0][1] == "2026-06-20" or fake.calls[0][1] < "2026-06-27"  # a full-window start, not last-bar-3d


def test_full_fetch_never_starts_after_the_cached_first_bar(_engine):
    _seed(_engine, "AAPL", _bars(date(2026, 3, 2), date(2026, 9, 24)), "yahoo")  # held more than asked
    fake = FakeChart(_bars(date(2026, 1, 1), TODAY), page=2000)
    _run(FMPIntradaySource(client=fake), {"AAPL": 90})
    assert fake.calls[0][1] == "2026-03-02"


def test_full_refresh_ignores_a_healthy_fmp_cache(_engine):
    _seed(_engine, "AAPL", _bars(date(2026, 6, 20), date(2026, 9, 24)), "fmp")
    replace: list[str] = []
    _run(FMPIntradaySource(client=FakeChart(_bars(date(2026, 6, 1), TODAY), page=1000)), {"AAPL": 90},
         replace_tickers=replace, full_refresh=True)
    assert replace == ["AAPL"]


def test_group_off_returns_nothing_without_calling_fmp():
    dg.set_group_enabled("intraday_bars", False)
    fake = FakeChart(_bars(date(2026, 9, 1), TODAY))
    assert _run(FMPIntradaySource(client=fake), {"AAPL": 30}) == {}
    assert fake.calls == []


def test_error_thin_and_empty_answers_leave_the_ticker_out():
    assert _run(FMPIntradaySource(client=FakeChart([], fail=True)), {"AAPL": 30}) == {}
    assert _run(FMPIntradaySource(client=FakeChart([])), {"AAPL": 30}) == {}
    thin = FakeChart(_bars(TODAY, TODAY, bars_per_day=2))
    assert _run(FMPIntradaySource(client=thin), {"AAPL": 30}) == {}


def test_a_partial_live_bar_is_never_returned():
    ref = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)  # 11:00 ET: 09:30 bar done, 10:30 in progress
    fake = FakeChart(_bars(date(2026, 9, 21), TODAY), page=1000)
    out = asyncio.run(FMPIntradaySource(client=fake).get_intraday_bars({"AAPL": 30}, reference=ref))
    assert out["AAPL"].index[-1] == pd.Timestamp("2026-09-25 09:30")


def test_short_sessions_are_recorded_per_ticker():
    bars = _bars(date(2026, 9, 21), date(2026, 9, 22)) + _bars(date(2026, 9, 23), date(2026, 9, 23), bars_per_day=3) + _bars(date(2026, 9, 24), TODAY)
    src = FMPIntradaySource(client=FakeChart(bars, page=1000))
    _run(src, {"AAPL": 30})
    assert src.short_sessions == {"AAPL": [(date(2026, 9, 23), 3, 7)]}


# ---- fallback wrapper ----

def _yahoo_frame():
    idx = pd.DatetimeIndex([datetime(2026, 9, 25, h, m) for h, m in HOURS])
    return pd.DataFrame({k: [1.0] * 7 for k in ("open", "high", "low", "close")} | {"volume": [1] * 7}, index=idx)


def test_wrapper_sends_only_what_fmp_missed_to_yahoo_and_reports_it():
    asked = {}

    async def yahoo(tw, auto_adjust):
        asked.update(tw)
        return {t: _yahoo_frame() for t in tw}

    class Half:
        async def get_intraday_bars(self, tw, reference=None, replace_tickers=None, full_refresh=False):
            return {"AAPL": _yahoo_frame()}

    served: set[str] = set()
    fb = FallbackTickers()
    out = asyncio.run(FMPIntradayWithFallback(fallback=yahoo, fmp=Half()).get_intraday_bars(
        {"AAPL": 30, "MSFT": 30}, False, fallback_tickers=fb, fmp_served=served))
    assert set(out) == {"AAPL", "MSFT"} and asked == {"MSFT": 30}
    assert served == {"AAPL"} and list(fb) == ["MSFT"] and fb.yahoo == ["MSFT"]


def test_wrapper_survives_the_fmp_source_blowing_up():
    async def yahoo(tw, auto_adjust):
        return {t: _yahoo_frame() for t in tw}

    class Boom:
        async def get_intraday_bars(self, *a, **k):
            raise RuntimeError("x")

    out = asyncio.run(FMPIntradayWithFallback(fallback=yahoo, fmp=Boom()).get_intraday_bars({"AAPL": 30}, False))
    assert "AAPL" in out


# ---- cache wiring ----

def _patch_chain(monkeypatch, fake, yahoo_calls):
    monkeypatch.setattr(dbs, "fmp_client", fake)
    monkeypatch.setattr(dbs.FMPIntradaySource.__init__, "__defaults__", (fake,))

    async def fake_yahoo(group, period, interval, auto_adjust):
        yahoo_calls.append((sorted(group), period))
        return {t: _yahoo_frame().rename(columns=str.capitalize) for t in group}

    monkeypatch.setattr(cache.yahoo_client, "get_history", fake_yahoo)


def _sources(engine, ticker):
    with Session(engine) as session:
        return set(session.exec(select(SharedBarsCache.source).where(SharedBarsCache.ticker == ticker)).all())


def test_cache_60m_is_fmp_first_and_tags_rows(monkeypatch, _engine):
    yahoo_calls: list = []
    _patch_chain(monkeypatch, FakeChart(_bars(date(2026, 6, 1), TODAY), page=1000), yahoo_calls)
    out = asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    assert yahoo_calls == [] and len(out["AAPL"]) > 300
    assert out["AAPL"].index.tz is not None  # still handed back tz-aware ET
    assert _sources(_engine, "AAPL") == {"fmp"}


def test_cache_60m_group_off_falls_through_to_yahoo_and_tags_yahoo(monkeypatch, _engine):
    dg.set_group_enabled("intraday_bars", False)
    yahoo_calls: list = []
    fake = FakeChart(_bars(date(2026, 6, 1), TODAY))
    _patch_chain(monkeypatch, fake, yahoo_calls)
    fb = FallbackTickers()
    asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF, fallback_tickers=fb))
    assert fake.calls == [] and yahoo_calls and list(fb) == ["AAPL"]
    assert _sources(_engine, "AAPL") == {"yahoo"}


def test_cache_60m_cutover_replaces_yahoo_history_with_fmp(monkeypatch, _engine):
    _seed(_engine, "AAPL", _bars(date(2026, 6, 20), date(2026, 9, 24), base=500.0), None)  # Yahoo-era rows
    yahoo_calls: list = []
    _patch_chain(monkeypatch, FakeChart(_bars(date(2026, 6, 1), TODAY), page=1000), yahoo_calls)
    out = asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    assert _sources(_engine, "AAPL") == {"fmp"}
    assert out["AAPL"]["close"].max() < 200  # none of the 500-based Yahoo-era bars survive


def test_cache_60m_non_us_ticker_gets_no_bars_at_all(monkeypatch, _engine):
    """Phase 6a: non-US support is dropped, so the old Yahoo-only non-US 60m path is gone --
    neither FMP nor Yahoo is asked and nothing is cached."""
    yahoo_calls: list = []
    fake = FakeChart(_bars(date(2026, 6, 1), TODAY))
    _patch_chain(monkeypatch, fake, yahoo_calls)
    out = asyncio.run(cache.get_or_fetch_bars_batch(["0005.HK"], "60m", 90, reference=REF))
    assert fake.calls == [] and yahoo_calls == []
    assert _sources(_engine, "0005.HK") == set()
    assert "0005.HK" not in out or out["0005.HK"].empty


# ---- provenance trigger in the cache's fetch selection (fix to the P4 cutover) ----

def _fresh_wide_cache(engine, ticker, source):
    feed = _bars(date(2026, 6, 1), TODAY)
    _seed(engine, ticker, feed, source)
    return feed


@pytest.mark.parametrize("source", [None, "yahoo"])
def test_fresh_wide_non_fmp_history_is_still_fetched_and_replaced(monkeypatch, _engine, source):
    feed = _fresh_wide_cache(_engine, "AAPL", source)  # fresh AND wide: the old selection skipped this
    yahoo_calls: list = []
    fake = FakeChart(feed, page=1000)
    _patch_chain(monkeypatch, fake, yahoo_calls)
    asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    assert fake.calls and yahoo_calls == []
    assert _sources(_engine, "AAPL") == {"fmp"}


def test_once_tagged_fmp_a_second_run_makes_no_fetch_at_all(monkeypatch, _engine):
    feed = _fresh_wide_cache(_engine, "AAPL", None)
    yahoo_calls: list = []
    fake = FakeChart(feed, page=1000)
    _patch_chain(monkeypatch, fake, yahoo_calls)
    asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    calls_after_first = len(fake.calls)
    asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    assert len(fake.calls) == calls_after_first and yahoo_calls == []


def test_a_single_yahoo_tagged_row_among_fmp_rows_triggers_a_replace(monkeypatch, _engine):
    feed = _fresh_wide_cache(_engine, "AAPL", "fmp")
    with Session(_engine) as session:  # what a temporary Yahoo fallback write leaves behind
        row = session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == "AAPL")).first()
        row.source = "yahoo"
        session.add(row)
        session.commit()
    fake = FakeChart(feed, page=1000)
    _patch_chain(monkeypatch, fake, [])
    asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    assert fake.calls and _sources(_engine, "AAPL") == {"fmp"}


def test_trigger_is_skipped_while_the_group_is_off(monkeypatch, _engine):
    dg.set_group_enabled("intraday_bars", False)
    feed = _fresh_wide_cache(_engine, "AAPL", None)
    yahoo_calls: list = []
    fake = FakeChart(feed)
    _patch_chain(monkeypatch, fake, yahoo_calls)
    asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    assert fake.calls == [] and yahoo_calls == []  # fresh + wide + group off: cache served as-is


def test_trigger_never_reselects_a_non_us_ticker(monkeypatch, _engine):
    feed = _fresh_wide_cache(_engine, "0005.HK", "yahoo")
    yahoo_calls: list = []
    fake = FakeChart(feed)
    _patch_chain(monkeypatch, fake, yahoo_calls)
    asyncio.run(cache.get_or_fetch_bars_batch(["0005.HK"], "60m", 90, reference=REF))
    assert fake.calls == [] and yahoo_calls == []


def test_a_ticker_fmp_cannot_serve_is_retried_each_run_via_yahoo(monkeypatch, _engine):
    _fresh_wide_cache(_engine, "AAPL", "yahoo")
    yahoo_calls: list = []
    fake = FakeChart([])  # empty answers
    _patch_chain(monkeypatch, fake, yahoo_calls)
    for _ in range(2):
        asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 90, reference=REF))
    assert len(yahoo_calls) == 2 and _sources(_engine, "AAPL") == {"yahoo"}  # accepted recurring cost


def test_source_labels_reflect_the_cached_provenance(_engine):
    _seed(_engine, "AAPL", _bars(TODAY, TODAY), "fmp")
    _seed(_engine, "MSFT", _bars(TODAY, TODAY), None)
    _seed(_engine, "NVDA", _bars(TODAY, TODAY), "fmp")
    _seed(_engine, "NVDA", [(datetime(2026, 9, 24, 9, 30), 1.0)], "yahoo")
    assert cache.intraday_source_labels(["AAPL", "MSFT", "NVDA", "NONE"]) == {
        "AAPL": "fmp", "MSFT": "yahoo", "NVDA": "yahoo", "NONE": "yahoo"}
