"""End-to-end integration test for the Massive daily-bar path: real
clients.shared_bars_cache.get_or_fetch_bars_batch -> real
clients.daily_bar_sources.MassiveWithYahooFallback/MassiveDailySource ->
real clients.massive_client.MassiveClient, with ONLY the HTTP transport
mocked (httpx.MockTransport, same technique tests/test_massive_client.py
already uses) -- nothing in between is stubbed out.

Why this file exists, not just the unit-level tests in
test_massive_client.py/test_daily_bar_sources.py/test_shared_bars_cache.py:
those all stub the layer directly below the one under test (a fake
DailyBarSource, a fake MassiveClient), so a bug in how one real layer's
output shape feeds the next real layer's input expectation -- exactly the
column-casing mismatch shipped in commit 2665cb9 (Massive/Yahoo's
lowercase frames vs. _write_rows' original assumption of yfinance's
capitalized columns) -- is invisible to any of them. That bug was only
ever caught by the one-time backfill script's own genuine end-to-end
run against the real Massive API (see CLAUDE.md's "Major bug" note) --
this file gives the ordinary test suite the same coverage, with
massive_enabled=True and settings.fmp_enabled left at its default,
so it runs on every `pytest`, not just a manual verification pass."""

import asyncio
from datetime import date, datetime

import httpx
from sqlmodel import Session, SQLModel, create_engine, select

import clients.daily_bar_sources as daily_bar_sources
import clients.massive_client as massive_client_module
import clients.shared_bars_cache as shared_bars_cache
from clients.shared_bars_cache import DAILY_INTERVAL, get_or_fetch_bars_batch
from core.config import settings
from core.models import SharedBarsCache


def _fresh_engine(monkeypatch):
    """Every module with its own `engine` import that this real call chain
    actually touches -- shared_bars_cache.py's own fetch/write step AND
    daily_bar_sources.py::MassiveDailySource._existing_span's independent
    query -- must be pointed at the SAME fresh in-memory engine, per
    CLAUDE.md's engine-isolation convention. Missing either half would
    silently write live Massive-shaped data into the real on-disk DB
    (caught immediately by conftest.py's session-scoped write-guard if
    missed, not just a style preference)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    monkeypatch.setattr(daily_bar_sources, "engine", engine)
    return engine


def _install_mock_massive_transport(monkeypatch, handler):
    """Same MockTransport-swap convention as tests/test_massive_client.py
    -- no actual HTTP call ever leaves the process."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(massive_client_module.httpx, "AsyncClient", factory)


def _bar(t_ms: int, o=100.0, h=101.0, l=99.0, c=234.56, v=1_000_000) -> dict:
    return {"t": t_ms, "o": o, "h": h, "l": l, "c": c, "v": v}


# 2026-09-22 00:00 America/New_York (EDT, UTC-4) as Unix ms UTC -- matching
# test_massive_client.py's own constant so a real trading-day date is used.
_SEPT_22_MS = 1790049600000


def _handler_for_range_request(request) -> httpx.Response:
    assert "apiKey=" in str(request.url)
    url = str(request.url)
    if "/v3/reference/splits" in url:
        return httpx.Response(200, json={"results": []})
    assert "/v2/aggs/ticker/AAPL/range/1/day/" in url
    return httpx.Response(200, json={"results": [_bar(_SEPT_22_MS)], "resultsCount": 1})


def test_never_cached_ticker_is_fetched_from_massive_and_written_with_correct_lowercase_columns(monkeypatch):
    """The real regression case for the column-casing bug (commit
    2665cb9): a brand-new ticker flows through the full real chain --
    MassiveClient's real _bars_to_frame -> MassiveDailySource's real
    backfill branch -> _write_rows' real lowercase-column read -- and the
    persisted SharedBarsCache row's OHLCV values must match what Massive's
    mocked response actually sent, not silently read as 0/garbage from a
    KeyError-swallowed or miscased column."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(settings, "massive_enabled", True)
    _install_mock_massive_transport(monkeypatch, _handler_for_range_request)

    result = asyncio.run(
        get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, 30, auto_adjust=False, reference=datetime(2026, 9, 23))
    )

    assert not result["AAPL"].empty
    assert result["AAPL"].iloc[-1]["close"] == 234.56

    with Session(engine) as session:
        rows = session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == "AAPL")).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.interval == DAILY_INTERVAL
    assert row.close == 234.56
    assert row.open == 100.0
    assert row.high == 101.0
    assert row.low == 99.0
    assert row.volume == 1_000_000
    assert row.bar_time.date() == date(2026, 9, 22)


def test_class_share_ticker_round_trips_through_the_massive_dot_symbol(monkeypatch):
    """BRK-B (Fathom's canonical hyphen form) must be requested from
    Massive as BRK.B (its dot notation, core/tickers.py::to_massive_symbol)
    and stored back under the hyphen form -- the real symbol-mapping layer,
    not a stub of it."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(settings, "massive_enabled", True)

    def handler(request):
        url = str(request.url)
        if "/v3/reference/splits" in url:
            return httpx.Response(200, json={"results": []})
        assert "/v2/aggs/ticker/BRK.B/range/1/day/" in url
        return httpx.Response(200, json={"results": [_bar(_SEPT_22_MS, c=555.0)], "resultsCount": 1})

    _install_mock_massive_transport(monkeypatch, handler)

    result = asyncio.run(
        get_or_fetch_bars_batch(["BRK-B"], DAILY_INTERVAL, 30, auto_adjust=False, reference=datetime(2026, 9, 23))
    )

    assert result["BRK-B"].iloc[-1]["close"] == 555.0
    with Session(engine) as session:
        rows = session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == "BRK-B")).all()
    assert len(rows) == 1


def test_non_us_ticker_never_reaches_massive_goes_straight_to_yahoo(monkeypatch):
    """0700.HK must never generate a Massive HTTP request at all -- the
    mock transport asserts on every real request it receives, so a
    misrouted call would fail the request assertion, not just be missed by
    a call-count check."""
    _fresh_engine(monkeypatch)
    monkeypatch.setattr(settings, "massive_enabled", True)

    def handler(request):
        raise AssertionError(f"0700.HK must never reach Massive, but got a request: {request.url}")

    _install_mock_massive_transport(monkeypatch, handler)

    async def fake_yahoo_get_history(tickers, period, interval, auto_adjust):
        import pandas as pd

        index = pd.DatetimeIndex([pd.Timestamp("2026-09-22")])
        return {
            t: pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [88.8], "Volume": [1]}, index=index)
            for t in tickers
        }

    monkeypatch.setattr(shared_bars_cache.yahoo_client, "get_history", fake_yahoo_get_history)

    result = asyncio.run(
        get_or_fetch_bars_batch(["0700.HK"], DAILY_INTERVAL, 30, auto_adjust=False, reference=datetime(2026, 9, 23))
    )

    assert result["0700.HK"].iloc[-1]["close"] == 88.8


def test_massive_http_failure_falls_back_to_yahoo_and_still_writes_correct_columns(monkeypatch):
    """A genuine Massive-side failure (500, surviving MassiveClient's own
    retries) must fall back to Yahoo for the whole batch, and the result
    must still be written with correct lowercase columns -- exercising
    YahooDailySource's own rename(columns=str.lower) call, the other half
    of the casing contract _write_rows depends on."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(settings, "massive_enabled", True)
    monkeypatch.setattr(massive_client_module, "RATE_LIMIT_MAX_RETRIES", 0)
    monkeypatch.setattr(massive_client_module, "SERVER_ERROR_MAX_RETRIES", 0)

    def handler(request):
        return httpx.Response(500, json={"error": "internal error"})

    _install_mock_massive_transport(monkeypatch, handler)

    async def fake_yahoo_get_history(tickers, period, interval, auto_adjust):
        import pandas as pd

        index = pd.DatetimeIndex([pd.Timestamp("2026-09-22")])
        return {
            t: pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [321.0], "Volume": [42]}, index=index)
            for t in tickers
        }

    monkeypatch.setattr(shared_bars_cache.yahoo_client, "get_history", fake_yahoo_get_history)

    result = asyncio.run(
        get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, 30, auto_adjust=False, reference=datetime(2026, 9, 23))
    )

    assert result["AAPL"].iloc[-1]["close"] == 321.0
    with Session(engine) as session:
        rows = session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == "AAPL")).all()
    assert rows[0].close == 321.0
    assert rows[0].volume == 42
