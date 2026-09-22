import asyncio
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.market_breadth_data as mbd
from core.models import MarketBreadthGateLog, MarketBreadthSnapshot

COMPLETED = date(2026, 9, 18)


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(mbd, "engine", engine)
    return engine


def _frame(end="2026-09-18", periods=300, start_price=100.0, end_price=150.0) -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=periods)
    close = pd.Series(np.linspace(start_price, end_price, periods), index=index)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000})


def _patch_bars(monkeypatch, bars: dict):
    async def fake(tickers, interval, lookback_days, auto_adjust=False, **_):
        assert interval == "1d" and lookback_days == mbd.FETCH_LOOKBACK_DAYS and auto_adjust is False
        return {t: bars[t] for t in tickers if t in bars}

    monkeypatch.setattr(mbd, "get_or_fetch_bars_batch", fake)


def _tickers(n):
    return [f"T{i:03d}" for i in range(n)]


def _run(tickers, completed=COMPLETED):
    return asyncio.run(mbd.compute_and_store_market_breadth(tickers, completed_date=completed))


def _rows(engine):
    with Session(engine) as session:
        return session.exec(select(MarketBreadthSnapshot)).all()


def test_stores_one_row_for_the_anchor_session(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(10)
    bars = {t: _frame(start_price=100, end_price=150 if i < 6 else 60) for i, t in enumerate(tickers)}
    _patch_bars(monkeypatch, bars)

    summary = _run(tickers)

    (row,) = _rows(engine)
    assert row.universe == "sp500" and row.as_of_date == COMPLETED and row.is_backfilled is False
    assert row.constituents == 10 and row.stale_excluded == 0
    assert row.sma20_eligible == 10 and row.sma20_above == 6 and row.pct_above_sma20 == 60.0
    assert row.sma50_eligible == 10 and row.sma50_above == 6 and row.pct_above_sma50 == 60.0
    assert row.sma200_eligible == 10 and row.pct_above_sma200 == 60.0
    # Six rising tickers close on their 52-week high, four falling ones on their low.
    assert row.hl_eligible == 10 and row.new_highs == 6 and row.new_lows == 4 and row.net_new_highs == 2
    assert summary["as_of_date"] == "2026-09-18" and summary["with_bar"] == 10 and summary["net_new_highs"] == 2
    assert summary["pct_above_sma20"] == 60.0


def test_a_bar_after_the_last_completed_session_is_ignored(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(5)
    # yfinance's in-progress same-day bar (Mon 9/21) must not become the anchor.
    _patch_bars(monkeypatch, {t: _frame(end="2026-09-21") for t in tickers})
    _run(tickers)
    assert [r.as_of_date for r in _rows(engine)] == [COMPLETED]


@pytest.mark.parametrize("missing, ok", [(15, True), (16, False)])
def test_coverage_gate_boundary_at_503_constituents(monkeypatch, missing, ok):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(503)
    frame = _frame()
    # Missing tickers are stale (last bar a session behind), not absent.
    stale = _frame(end="2026-09-17")
    _patch_bars(monkeypatch, {t: (stale if i < missing else frame) for i, t in enumerate(tickers)})

    if ok:
        summary = _run(tickers)
        (row,) = _rows(engine)
        assert row.stale_excluded == missing and summary["stale_excluded"] == missing
        # Excluded from every count, not counted as "below" -- the 20-day metric under the same gate as 50/200.
        assert row.sma20_eligible == 503 - missing and row.sma50_eligible == 503 - missing and row.sma200_eligible == 503 - missing
        assert row.sma20_above == 503 - missing  # every live ticker is on a rising series
    else:
        with pytest.raises(mbd.InsufficientCoverageError, match="coverage gate"):
            _run(tickers)
        assert _rows(engine) == []  # nothing written below the gate


def test_a_thin_history_ticker_shrinks_the_sma20_denominator_but_is_not_a_gate_miss(monkeypatch):
    # The gate is bar PRESENCE on the anchor session, identical for every SMA: a young ticker (30 bars)
    # counts toward coverage and is sma20-eligible, yet is absent from the 50/200-day denominators.
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(10)
    _patch_bars(monkeypatch, {t: _frame(periods=30 if i == 0 else 300) for i, t in enumerate(tickers)})
    _run(tickers)
    (row,) = _rows(engine)
    assert row.stale_excluded == 0
    assert row.sma20_eligible == 10 and row.sma50_eligible == 9 and row.sma200_eligible == 9


def test_gate_failure_names_the_missing_tickers(monkeypatch):
    _fresh_engine(monkeypatch)
    tickers = _tickers(10)
    _patch_bars(monkeypatch, {t: _frame() for t in tickers[:5]})  # half never fetched
    with pytest.raises(mbd.InsufficientCoverageError, match="T005"):
        _run(tickers)


def test_no_tickers_or_no_bars_raises(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with pytest.raises(RuntimeError, match="empty universe"):
        _run([])
    _patch_bars(monkeypatch, {})
    with pytest.raises(RuntimeError, match="no usable bars"):
        _run(_tickers(3))
    assert _rows(engine) == []


def test_nightly_overwrites_a_backfilled_row_but_a_backfill_never_overwrites(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(4)
    _patch_bars(monkeypatch, {t: _frame() for t in tickers})
    now = datetime(2026, 9, 21, 3, 35)
    backfilled = dict(
        universe="sp500", as_of_date=COMPLETED, computed_at=now, constituents=4, stale_excluded=0, sma20_eligible=4, sma20_above=0,
        pct_above_sma20=0.0, sma50_eligible=4, sma50_above=0,
        pct_above_sma50=0.0, sma200_eligible=4, sma200_above=0, pct_above_sma200=0.0, hl_eligible=4, new_highs=0, new_lows=0,
        net_new_highs=0, is_backfilled=True,
    )
    assert mbd.store_snapshots([backfilled], overwrite=False) == 1

    _run(tickers)
    (row,) = _rows(engine)
    assert row.is_backfilled is False and row.pct_above_sma50 == 100.0 and row.pct_above_sma20 == 100.0

    # Re-running the backfill leaves the live row alone.
    mbd.store_snapshots([backfilled], overwrite=False)
    (row,) = _rows(engine)
    assert row.is_backfilled is False and row.pct_above_sma50 == 100.0
    # And a weekend/holiday re-run of the same anchor is idempotent.
    _run(tickers)
    assert len(_rows(engine)) == 1


def test_backfill_rows_only_span_sessions_with_full_universe_coverage():
    tickers = _tickers(10)
    # One of 10 constituents is young (120 bars), so at most 9/10 = 90% are ever
    # eligible for the 52-week window -- under the 97% gate on every session.
    bars = {t: _frame(periods=500) for t in tickers[:9]}
    bars[tickers[9]] = _frame(periods=120)
    values, summary = mbd.build_backfill_rows(bars, constituents=10, completed_date=COMPLETED)
    assert values == [] and summary["kept"] == 0

    # With all 10 fully seeded, the first kept session is the one whose
    # 252-bar window first fills (the 252nd bar).
    values, summary = mbd.build_backfill_rows({t: _frame(periods=500) for t in tickers}, constituents=10, completed_date=COMPLETED)
    index = pd.bdate_range(end="2026-09-18", periods=500)
    assert summary["first_date"] == index[251].date().isoformat() and summary["last_date"] == "2026-09-18"
    assert summary["kept"] == 500 - 251 and summary["sessions_seen"] == 500
    assert all(v["is_backfilled"] is True and v["universe"] == "sp500" for v in values)
    assert all(v["constituents"] == 10 and v["stale_excluded"] == 0 for v in values)


def test_backfilled_sma20_matches_an_independent_calculation_for_every_kept_session():
    # Phase-shifted oscillating series, so the share of tickers above their 20-day SMA genuinely varies per
    # session; checked against a plain "last 20 closes" loop rather than the vectorized rolling code under test.
    tickers = _tickers(9)
    bars = {}
    for i, t in enumerate(tickers):
        frame = _frame(periods=320)
        wave = 8 * np.sin(2 * np.pi * np.arange(320) / 30 + i**1.5)
        frame["close"] = frame["close"] + wave
        frame["high"], frame["low"] = frame["close"] + 1, frame["close"] - 1
        bars[t] = frame
    values, summary = mbd.build_backfill_rows(bars, constituents=9, completed_date=COMPLETED)
    assert summary["kept"] > 0

    for v in values:
        day = pd.Timestamp(v["as_of_date"])
        above = eligible = 0
        for frame in bars.values():
            window = frame["close"].loc[:day].iloc[-20:]
            if len(window) == 20:
                eligible += 1
                above += int(window.iloc[-1] > window.mean())
        assert (v["sma20_eligible"], v["sma20_above"]) == (eligible, above)
        assert v["pct_above_sma20"] == pytest.approx(above / eligible * 100)
    assert len({v["pct_above_sma20"] for v in values}) > 2  # the check is not vacuous


def test_backfill_rows_drop_sessions_after_the_completed_date():
    tickers = _tickers(4)
    values, summary = mbd.build_backfill_rows(
        {t: _frame(end="2026-09-21", periods=300) for t in tickers}, constituents=4, completed_date=COMPLETED
    )
    assert summary["last_date"] == "2026-09-18"
    assert max(v["as_of_date"] for v in values) == COMPLETED


def test_backfill_rows_are_plain_python_values_sqlite_can_bind(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(4)
    values, _ = mbd.build_backfill_rows({t: _frame(periods=300) for t in tickers}, constituents=4, completed_date=COMPLETED)
    assert mbd.store_snapshots(values, overwrite=False) == len(values)
    assert len(_rows(engine)) == len(values)


def test_load_cached_daily_bars_is_a_read_only_view_of_shared_bars_cache(monkeypatch):
    from core.models import SharedBarsCache

    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        for day in pd.bdate_range(end="2026-09-18", periods=5):
            session.add(SharedBarsCache(ticker="AAA", interval="1d", bar_time=day.to_pydatetime(), open=1, high=2, low=0.5, close=1.5,
                                        volume=10, fetched_at=datetime(2026, 9, 19)))
        session.add(SharedBarsCache(ticker="AAA", interval="60m", bar_time=datetime(2026, 9, 18, 9, 30), open=1, high=2, low=0.5,
                                    close=1.5, volume=10, fetched_at=datetime(2026, 9, 19)))
        session.commit()
    frames = mbd.load_cached_daily_bars(["AAA", "MISSING"])
    assert set(frames) == {"AAA"} and len(frames["AAA"]) == 5


# ----------------------------------------------------------------------------
# Sector breadth: aggregation, the more-permissive OR-gate, isolation, and
# the gate log's monitoring trace. Sector identifiers are synthetic ("SECA",
# "SECB", ...) rather than real SPDR tickers -- compute_and_store_market_breadth
# takes sector_tickers as a plain caller-supplied mapping, decoupled from
# SECTOR_TO_ETF/load_sector_buckets (covered separately below).
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "constituents, missing, expected",
    [
        (20, 1, True),  # floor rescues: 1/20 = 5% > 3%
        (20, 2, False),  # neither leg passes
        (33, 1, True),  # floor rescues: 1/33 = 3.03% > 3%
        (34, 1, True),  # percentage alone already clears: 1/34 = 2.94% <= 3%
        (85, 2, True),  # a large sector: percentage alone clears (2/85 = 2.35%)
        (0, 0, False),  # no constituents at all
    ],
)
def test_sector_coverage_ok_boundary(constituents, missing, expected):
    assert mbd.sector_coverage_ok(constituents - missing, constituents) is expected


def test_sector_rows_reuse_the_same_bars_and_are_gated_independently(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    sp500_filler = _tickers(200)  # keeps the TOP-LEVEL gate comfortably within 97% regardless of the sector cases below
    seca = [f"A{i:02d}" for i in range(20)]  # every ticker healthy -> clears BOTH legs
    secb = [f"B{i:02d}" for i in range(10)]  # 1 stale of 10 (10% > 3%) -> rescued only by the floor
    sector_tickers = {"SECA": seca, "SECB": secb}
    all_tickers = sorted(set(sp500_filler) | set(seca) | set(secb))

    bars = {t: _frame(start_price=100, end_price=150) for t in all_tickers}
    bars[secb[0]] = _frame(end="2026-09-17")  # stale, not absent
    _patch_bars(monkeypatch, bars)

    summary = asyncio.run(mbd.compute_and_store_market_breadth(all_tickers, completed_date=COMPLETED, sector_tickers=sector_tickers))

    assert summary["sectors"]["SECA"] == {"passed": True, "constituents": 20, "with_bar": 20, "gate_rule": "both", "pct_above_sma50": 100.0}
    assert summary["sectors"]["SECB"]["passed"] is True and summary["sectors"]["SECB"]["gate_rule"] == "floor"
    assert summary["sectors"]["SECB"]["with_bar"] == 9

    with Session(engine) as session:
        rows = session.exec(select(MarketBreadthSnapshot)).all()
    assert {r.universe for r in rows} == {"sp500", "sector:SECA", "sector:SECB"}
    seca_row = next(r for r in rows if r.universe == "sector:SECA")
    assert seca_row.constituents == 20 and seca_row.stale_excluded == 0 and seca_row.pct_above_sma50 == 100.0
    secb_row = next(r for r in rows if r.universe == "sector:SECB")
    assert secb_row.constituents == 10 and secb_row.stale_excluded == 1

    with Session(engine) as session:
        logs = session.exec(select(MarketBreadthGateLog)).all()
    assert {(log.universe, log.passed, log.passed_via) for log in logs} == {
        ("sp500", True, "percentage"),
        ("sector:SECA", True, "both"),
        ("sector:SECB", True, "floor"),
    }
    seca_log = next(log for log in logs if log.universe == "sector:SECA")
    assert seca_log.constituents == 20 and seca_log.with_bar == 20 and seca_log.missing_count == 0
    assert json.loads(seca_log.missing_tickers_json) == []


def test_a_refused_sector_is_isolated_and_never_touches_its_own_prior_row(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    sp500_filler = _tickers(200)
    good = [f"G{i:02d}" for i in range(20)]
    bad = [f"D{i:02d}" for i in range(10)]  # 2 of 10 stale: floor (2 > 1) AND percentage (80% < 97%) both fail
    sector_tickers = {"GOOD": good, "BAD": bad}
    all_tickers = sorted(set(sp500_filler) | set(good) | set(bad))

    bars = {t: _frame() for t in all_tickers}
    bars[bad[0]] = _frame(end="2026-09-17")
    bars[bad[1]] = _frame(end="2026-09-17")
    _patch_bars(monkeypatch, bars)

    # A pre-existing row for the refused sector -- a refusal must leave it byte-for-byte alone.
    prior = dict(
        universe="sector:BAD", as_of_date=date(2026, 9, 10), computed_at=datetime(2026, 9, 10, 3, 35), constituents=10, stale_excluded=0,
        sma20_eligible=10, sma20_above=3, pct_above_sma20=30.0, sma50_eligible=10, sma50_above=3, pct_above_sma50=30.0, sma200_eligible=10,
        sma200_above=3, pct_above_sma200=30.0, hl_eligible=10, new_highs=1, new_lows=2, net_new_highs=-1, is_backfilled=True,
    )
    assert mbd.store_snapshots([prior], overwrite=False) == 1

    summary = asyncio.run(mbd.compute_and_store_market_breadth(all_tickers, completed_date=COMPLETED, sector_tickers=sector_tickers))

    assert summary["sectors"]["BAD"] == {"passed": False, "constituents": 10, "with_bar": 8, "missing": ["D00", "D01"]}
    assert summary["sectors"]["GOOD"]["passed"] is True

    with Session(engine) as session:
        rows = session.exec(select(MarketBreadthSnapshot)).all()
    bad_rows = [r for r in rows if r.universe == "sector:BAD"]
    assert len(bad_rows) == 1  # no new row was added
    assert bad_rows[0].as_of_date == date(2026, 9, 10) and bad_rows[0].pct_above_sma20 == 30.0  # completely untouched
    good_rows = [r for r in rows if r.universe == "sector:GOOD"]
    assert len(good_rows) == 1 and good_rows[0].as_of_date == COMPLETED and good_rows[0].constituents == 20
    # The wholesale run itself did not raise, and the sp500 (and GOOD sector) row was still written.
    assert len([r for r in rows if r.universe == "sp500"]) == 1

    with Session(engine) as session:
        logs = session.exec(select(MarketBreadthGateLog)).all()
    bad_log = next(log for log in logs if log.universe == "sector:BAD")
    assert bad_log.passed is False and bad_log.passed_via is None
    assert bad_log.constituents == 10 and bad_log.with_bar == 8 and bad_log.missing_count == 2
    assert json.loads(bad_log.missing_tickers_json) == ["D00", "D01"]
    good_log = next(log for log in logs if log.universe == "sector:GOOD")
    assert good_log.passed is True


def test_no_sector_rows_or_gate_log_entries_when_sector_tickers_is_omitted(monkeypatch):
    # Every existing caller/test that doesn't pass sector_tickers must be completely unaffected.
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(10)
    _patch_bars(monkeypatch, {t: _frame() for t in tickers})
    summary = _run(tickers)
    assert "sectors" not in summary
    with Session(engine) as session:
        rows = session.exec(select(MarketBreadthSnapshot)).all()
        logs = session.exec(select(MarketBreadthGateLog)).all()
    assert {r.universe for r in rows} == {"sp500"}
    # The sp500-level check is still logged even with no sectors requested.
    assert len(logs) == 1 and logs[0].universe == "sp500" and logs[0].passed is True


def test_load_sector_buckets_maps_index_constituent_sector_text_to_etf_ordered_like_sector_etfs(monkeypatch):
    from core.models import IndexConstituent
    from data.sector_heatmap_data import SECTOR_ETFS

    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", sector="Technology", last_synced_at=datetime(2026, 9, 20)))
        session.add(IndexConstituent(index_name="sp500", ticker="JPM", company_name="JPMorgan", sector="Financial Services", last_synced_at=datetime(2026, 9, 20)))
        session.add(IndexConstituent(index_name="sp500", ticker="MSTRANGE", company_name="Mystery", sector="Not A Real Sector", last_synced_at=datetime(2026, 9, 20)))
        session.add(IndexConstituent(index_name="dow", ticker="AXP", company_name="Amex", sector="Financial Services", last_synced_at=datetime(2026, 9, 20)))
        session.commit()
        buckets = mbd.load_sector_buckets(session)

    # Ordered exactly like SECTOR_ETFS, and every one of the 11 ETFs is present (even empty ones).
    assert list(buckets.keys()) == [etf for etf, _ in SECTOR_ETFS]
    assert buckets["XLK"] == ["AAPL"]
    assert buckets["XLF"] == ["JPM"]  # "dow"-only AXP is excluded -- sp500 strictly
    assert buckets["XLE"] == []  # no matching constituent, still present as an empty bucket
    assert "MSTRANGE" not in [t for tickers in buckets.values() for t in tickers]  # unrecognized sector text, skipped


def test_build_sector_backfill_rows_reuses_the_same_bars_and_applies_the_or_gate():
    # A sector with 20 tickers where 1 is thin-history (120 bars, never 52-week eligible): the sp500-style
    # AND-of-two-legs would zero out every session, but the sector's own OR-per-leg floor (missing <= 1)
    # rescues it -- 19/20 = 95% eligible is within the floor even though it's under the flat 97%.
    tickers = [f"S{i:02d}" for i in range(20)]
    bars = {t: _frame(periods=500) for t in tickers[:19]}
    bars[tickers[19]] = _frame(periods=120)
    sector_tickers = {"SECTHIN": tickers}

    values, summary = mbd.build_sector_backfill_rows(bars, sector_tickers, completed_date=COMPLETED)

    assert summary["SECTHIN"]["kept"] > 0
    assert all(v["universe"] == "sector:SECTHIN" and v["is_backfilled"] is True and v["constituents"] == 20 for v in values)

    # A sector absent from `bars` entirely (e.g. no cached history for any of its tickers) yields nothing,
    # not an error, and other sectors in the same call are unaffected.
    sector_tickers2 = {"SECTHIN": tickers, "EMPTY": ["ZZZ01", "ZZZ02"]}
    values2, summary2 = mbd.build_sector_backfill_rows(bars, sector_tickers2, completed_date=COMPLETED)
    assert summary2["EMPTY"] == {"sessions_seen": 0, "kept": 0, "first_date": None, "last_date": None}
    assert len(values2) == len(values)  # SECTHIN's own rows are unaffected by EMPTY being present too
