from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.market_breadth_data as market_breadth_data
import pipeline.backfills.backfill_market_breadth as backfill
from core.models import IndexConstituent, MarketBreadthSnapshot, SharedBarsCache


def _seed(monkeypatch, tmp_path, tickers, periods=320, sectors: dict[str, str] | None = None):
    sectors = sectors or {}
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(market_breadth_data, "engine", engine)
    monkeypatch.setattr(backfill, "engine", engine)
    monkeypatch.setattr(backfill, "init_db", lambda: None)  # would create_all on the REAL db
    monkeypatch.setattr(backfill, "LOG_PATH", tmp_path / "test_backfill_market_breadth.log")
    monkeypatch.setattr(backfill, "_most_recent_completed_trading_date", lambda: date(2026, 9, 18))
    index = pd.bdate_range(end="2026-09-18", periods=periods)
    with Session(engine) as session:
        for ticker in tickers:
            session.add(
                IndexConstituent(
                    index_name="sp500", ticker=ticker, company_name=ticker, sector=sectors.get(ticker), last_synced_at=datetime(2026, 9, 20)
                )
            )
            for day, price in zip(index, np.linspace(100, 150, periods)):
                session.add(SharedBarsCache(ticker=ticker, interval="1d", bar_time=day.to_pydatetime(), open=price, high=price + 1,
                                            low=price - 1, close=price, volume=1, fetched_at=datetime(2026, 9, 19)))
        session.commit()
    return engine, index


def _bar_count(engine) -> int:
    with Session(engine) as session:
        return len(session.exec(select(SharedBarsCache)).all())


def test_backfill_inserts_flagged_rows_from_the_cache_and_never_writes_the_cache(monkeypatch, tmp_path):
    engine, index = _seed(monkeypatch, tmp_path, ["AAA", "BBB", "CCC"])
    bars_before = _bar_count(engine)

    summary = backfill.main()

    assert summary["inserted"] == summary["kept"] == 320 - 251 and summary["already_present"] == 0
    assert summary["first_date"] == index[251].date().isoformat() and summary["last_date"] == "2026-09-18"
    with Session(engine) as session:
        rows = session.exec(select(MarketBreadthSnapshot)).all()
    assert len(rows) == summary["inserted"] and all(r.is_backfilled and r.universe == "sp500" for r in rows)
    assert _bar_count(engine) == bars_before  # read-only against SharedBarsCache


def _old_row(as_of: date, **overrides) -> MarketBreadthSnapshot:
    """A row as it looked before the 20-day metric existed: sma20 NULL, and sentinel values in every other
    column that a real recompute would NOT produce, so any overwrite is detectable."""
    fields = dict(
        universe="sp500", as_of_date=as_of, computed_at=datetime(2026, 9, 21, 3, 35), constituents=3, stale_excluded=0,
        sma50_eligible=3, sma50_above=1, pct_above_sma50=12.3, sma200_eligible=3, sma200_above=1, pct_above_sma200=45.6,
        hl_eligible=3, new_highs=7, new_lows=8, net_new_highs=-1, is_backfilled=True,
    )
    fields.update(overrides)
    return MarketBreadthSnapshot(**fields)


def _by_date(engine) -> dict:
    with Session(engine) as session:
        return {r.as_of_date: r for r in session.exec(select(MarketBreadthSnapshot)).all()}


def test_backfill_fills_sma20_on_existing_rows_without_touching_anything_else(monkeypatch, tmp_path):
    engine, index = _seed(monkeypatch, tmp_path, ["AAA", "BBB", "CCC"])
    old_day, has_sma20_day, live_day = index[-3].date(), index[-2].date(), index[-1].date()
    with Session(engine) as session:
        session.add(_old_row(old_day))
        # Already has a 20-day reading: must survive a re-run untouched, sentinel and all.
        session.add(_old_row(has_sma20_day, sma20_eligible=3, sma20_above=99, pct_above_sma20=99.0))
        # A live point-in-time row with NULL sma20: never filled from today's constituents.
        session.add(_old_row(live_day, is_backfilled=False))
        session.commit()

    dry = backfill.main(dry_run=True)
    assert dry["sma20_pending"] == 1 and dry["sma20_filled"] == 0
    assert _by_date(engine)[old_day].sma20_eligible is None  # a dry run wrote nothing

    summary = backfill.main()
    assert summary["sma20_pending"] == 1 and summary["sma20_filled"] == 1
    rows = _by_date(engine)

    filled = rows[old_day]
    assert filled.sma20_eligible == 3 and filled.sma20_above == 3 and filled.pct_above_sma20 == 100.0
    # Every pre-existing column is exactly what it was (the sentinels are not what a recompute would give).
    assert (filled.pct_above_sma50, filled.pct_above_sma200, filled.new_highs, filled.new_lows, filled.net_new_highs) == (12.3, 45.6, 7, 8, -1)
    assert filled.is_backfilled is True and filled.computed_at == datetime(2026, 9, 21, 3, 35)

    kept = rows[has_sma20_day]
    assert (kept.sma20_eligible, kept.sma20_above, kept.pct_above_sma20) == (3, 99, 99.0)
    live = rows[live_day]
    assert live.is_backfilled is False and live.sma20_eligible is None and live.pct_above_sma50 == 12.3

    again = backfill.main()
    assert again["sma20_pending"] == 0 and again["sma20_filled"] == 0  # a re-run fills nothing
    assert _by_date(engine)[old_day].sma20_eligible == 3


def test_rerun_is_a_no_op_and_dry_run_writes_nothing(monkeypatch, tmp_path):
    engine, _ = _seed(monkeypatch, tmp_path, ["AAA", "BBB"])

    dry = backfill.main(dry_run=True)
    assert dry["dry_run"] and dry["kept"] > 0 and dry["inserted"] == 0
    with Session(engine) as session:
        assert session.exec(select(MarketBreadthSnapshot)).all() == []

    first = backfill.main()
    again = backfill.main()
    assert first["inserted"] == first["kept"] and again["inserted"] == 0 and again["already_present"] == again["kept"]


def test_a_ticker_with_no_cached_bars_is_reported(monkeypatch, tmp_path):
    engine, _ = _seed(monkeypatch, tmp_path, ["AAA", "BBB"])
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="NOBARS", company_name="x", last_synced_at=datetime(2026, 9, 20)))
        session.commit()
    summary = backfill.main(dry_run=True)
    assert summary["tickers_without_cached_bars"] == ["NOBARS"] and summary["constituents"] == 3
    # 2 of 3 constituents = 67% < 97%: no session qualifies rather than a skewed subset.
    assert summary["kept"] == 0


def test_backfill_also_inserts_sector_rows_read_only_and_idempotent(monkeypatch, tmp_path):
    tickers = ["AAA", "BBB", "CCC"]
    sectors = {"AAA": "Technology", "BBB": "Technology", "CCC": "Energy"}
    engine, index = _seed(monkeypatch, tmp_path, tickers, sectors=sectors)
    bars_before = _bar_count(engine)

    dry = backfill.main(dry_run=True)
    assert dry["sectors"]["XLK"]["kept"] > 0 and dry["sectors"]["XLE"]["kept"] > 0
    assert dry["sector_inserted"] == 0  # a dry run writes nothing
    with Session(engine) as session:
        assert session.exec(select(MarketBreadthSnapshot)).all() == []

    summary = backfill.main()
    assert summary["sector_inserted"] == summary["sectors"]["XLK"]["kept"] + summary["sectors"]["XLE"]["kept"]
    with Session(engine) as session:
        rows = session.exec(select(MarketBreadthSnapshot)).all()
    xlk_rows = [r for r in rows if r.universe == "sector:XLK"]
    xle_rows = [r for r in rows if r.universe == "sector:XLE"]
    assert len(xlk_rows) == summary["sectors"]["XLK"]["kept"] and all(r.is_backfilled and r.constituents == 2 for r in xlk_rows)
    assert len(xle_rows) == summary["sectors"]["XLE"]["kept"] and all(r.constituents == 1 for r in xle_rows)
    assert xlk_rows[0].as_of_date == index[251].date()  # same 252-bar-window first-kept-session rule as sp500
    assert _bar_count(engine) == bars_before  # read-only against SharedBarsCache, sectors included

    again = backfill.main()
    assert again["sector_inserted"] == 0 and again["sector_already_present"] == again["sectors"]["XLK"]["kept"] + again["sectors"]["XLE"]["kept"]
    with Session(engine) as session:
        assert len(session.exec(select(MarketBreadthSnapshot)).all()) == len(rows)  # unchanged -- a re-run never clobbers a live/backfilled row


def test_rebuild_replaces_backfilled_rows_but_never_a_live_row(monkeypatch, tmp_path):
    engine, index = _seed(monkeypatch, tmp_path, ["AAA", "BBB", "CCC"])
    backfill.main()
    kept = 320 - 251
    live_date = index[-1].date()
    with Session(engine) as session:
        for row in session.exec(select(MarketBreadthSnapshot)).all():
            row.pct_above_sma50 = -1.0  # sentinel: a stale, pre-re-source value
            if row.as_of_date == live_date:
                row.is_backfilled = False  # a live nightly row
            session.add(row)
        session.commit()

    plain = backfill.main()  # no --rebuild: insert-only, nothing is restated
    assert plain["inserted"] == 0 and plain["rebuild_deleted"] == 0
    with Session(engine) as session:
        assert all(r.pct_above_sma50 == -1.0 for r in session.exec(select(MarketBreadthSnapshot)).all())

    dry = backfill.main(dry_run=True, rebuild=True)
    assert dry["rebuild_deleted"] == kept - 1
    with Session(engine) as session:
        assert all(r.pct_above_sma50 == -1.0 for r in session.exec(select(MarketBreadthSnapshot)).all())  # dry run wrote nothing

    summary = backfill.main(rebuild=True)
    assert summary["rebuild_deleted"] == kept - 1 and summary["inserted"] == kept - 1  # the live date's row conflicts and is skipped
    with Session(engine) as session:
        rows = {r.as_of_date: r for r in session.exec(select(MarketBreadthSnapshot)).all()}
    assert len(rows) == kept
    assert rows[live_date].pct_above_sma50 == -1.0 and rows[live_date].is_backfilled is False  # untouched
    assert all(r.pct_above_sma50 != -1.0 for d, r in rows.items() if d != live_date)
