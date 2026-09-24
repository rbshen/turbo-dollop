import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import pipeline.backfills.backfill_massive_daily_bars as backfill
from core.models import FundamentalsCache, SharedBarsCache, TickerScore, Watchlist, WatchlistTicker


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(backfill, "engine", engine)
    monkeypatch.setattr(backfill, "LOG_PATH", tmp_path / "test_backfill_massive_daily_bars.log")
    return engine


def _daily_frame(n: int = 5) -> pd.DataFrame:
    index = pd.bdate_range(end=date.today(), periods=n)
    return pd.DataFrame(
        {"open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n, "close": [100.5] * n, "volume": [1000] * n},
        index=index,
    )


def _patch_massive(monkeypatch, frame_by_ticker: dict[str, pd.DataFrame] | None = None, *, fail_for: set[str] | None = None):
    frame_by_ticker = frame_by_ticker or {}
    fail_for = fail_for or set()
    calls: list[str] = []

    async def fake_get_daily_bars(symbol, start, end, adjusted=False):
        calls.append(symbol)
        if symbol in fail_for:
            raise RuntimeError(f"simulated Massive failure for {symbol}")
        return frame_by_ticker.get(symbol, pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))

    monkeypatch.setattr(backfill.massive_client, "get_daily_bars", fake_get_daily_bars)
    return calls


def _stored_rows(engine, ticker: str) -> list[SharedBarsCache]:
    with Session(engine) as session:
        return list(session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == ticker)).all())


def test_backfills_a_ticker_and_writes_rows_to_shared_bars_cache(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _patch_massive(monkeypatch, {"AAPL": _daily_frame(5)})

    summary = asyncio.run(backfill.main(tickers=["AAPL"]))

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["bars_written"] == 5
    rows = _stored_rows(engine, "AAPL")
    assert len(rows) == 5
    assert all(r.interval == "1d" for r in rows)


def test_non_us_ticker_is_skipped_entirely_not_attempted_on_massive(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    calls = _patch_massive(monkeypatch, {})

    summary = asyncio.run(backfill.main(tickers=["0700.HK"]))

    assert calls == []
    assert summary["processed"] == 0
    assert summary["skipped_non_us"] == 1
    assert _stored_rows(engine, "0700.HK") == []


def test_a_failing_ticker_does_not_abort_the_run(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    _patch_massive(monkeypatch, {"AAPL": _daily_frame(3), "MSFT": _daily_frame(3)}, fail_for={"BADCO"})

    summary = asyncio.run(backfill.main(tickers=["AAPL", "BADCO", "MSFT"]))

    assert summary["processed"] == 3
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "BADCO"


def test_empty_massive_result_writes_nothing_but_is_not_a_failure(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _patch_massive(monkeypatch, {})  # AAPL gets an empty frame back

    summary = asyncio.run(backfill.main(tickers=["AAPL"]))

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["bars_written"] == 0
    assert _stored_rows(engine, "AAPL") == []


def test_empty_ticker_list_is_handled_without_crashing(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(backfill.main(tickers=[]))

    assert summary == {
        "processed": 0,
        "failed": 0,
        "skipped_non_us": 0,
        "bars_written": 0,
        "duration_seconds": 0.0,
        "failures": [],
    }


def test_resolve_universe_unions_every_daily_bar_consumers_own_source(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    now = datetime.now()
    with Session(engine) as session:
        # load_full_tracked_universe: a cached profile + a TickerScore row.
        session.add(FundamentalsCache(ticker="IREN", statement_type="profile", period="latest", fetched_at=now, raw_json="{}"))
        session.add(TickerScore(ticker="SEZL", overall_score=66, overall_verdict="Fail", computed_at=now))
        # Moat-rated universe (data/momentum_data.py::MOAT_VALUES).
        session.add(TickerScore(ticker="AAPL", moat="wide_moat", overall_score=80, computed_at=now))
        # W1-W5 watchlist union (Liquidity Zones).
        watchlist = Watchlist(name="W1", created_at=now, updated_at=now)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="WLTICK", added_at=now))
        session.commit()

    with Session(engine) as session:
        universe = backfill._resolve_universe(session)

    assert "IREN" in universe
    assert "SEZL" in universe
    assert "AAPL" in universe
    assert "WLTICK" in universe
    assert "SPY" in universe  # Sector Heatmap's own benchmark, always included
    assert "XLK" in universe  # one of the 11 SPDR sector ETFs


def test_moat_filter_alone_excludes_a_ticker_with_no_moat_and_no_other_membership():
    """Isolates data/momentum_data.py::MOAT_VALUES' own exclusion logic
    directly (a ticker with moat=None is dropped, never defaulted) --
    _resolve_universe's own full union can't demonstrate this end to end,
    since ANY TickerScore row (moat or not) already qualifies via
    load_full_tracked_universe's "any ticker with a TickerScore row"
    criterion, independent of the moat-rated query alongside it."""
    rows = [("AAPL", "wide_moat"), ("UNRATED", None)]
    assert {t for t, moat in rows if moat in backfill.MOAT_VALUES} == {"AAPL"}


def test_backfill_lookback_is_five_years():
    assert backfill.LOOKBACK_DAYS == 5 * 365


def test_massive_client_is_called_with_the_massive_symbol_and_five_year_window(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    seen = {}

    async def fake_get_daily_bars(symbol, start, end, adjusted=False):
        seen.update(symbol=symbol, start=start, end=end, adjusted=adjusted)
        return _daily_frame(1)

    monkeypatch.setattr(backfill.massive_client, "get_daily_bars", fake_get_daily_bars)

    asyncio.run(backfill.main(tickers=["BRK-B"]))

    assert seen["symbol"] == "BRK.B"  # Massive's own dot notation for the class share
    assert seen["adjusted"] is True  # split-adjusted (see clients/massive_client.py)
    assert (seen["end"] - seen["start"]).days == backfill.LOOKBACK_DAYS
