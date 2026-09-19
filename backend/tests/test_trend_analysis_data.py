import asyncio
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from analysis.trend_structure.weinstein import WEINSTEIN_BENCHMARK_TICKER
import data.trend_analysis_data as trend_analysis_data_module
from core.models import TrendAnalysis
from data.trend_analysis_data import compute_and_store_trend_analysis, get_trend_analysis_data


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _frame_from_closes(closes, open_off: float, high_off: float, low_off: float) -> pd.DataFrame:
    """Lowercase-column, naive-DatetimeIndex daily OHLCV -- exactly the
    shape clients/shared_bars_cache.py::get_or_fetch_bars returns."""
    index = pd.DatetimeIndex([date(2024, 1, 1) + timedelta(days=i) for i in range(len(closes))])
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": c - open_off, "high": c + high_off, "low": c - low_off, "close": c, "volume": 1000}, index=index
    )


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _synthetic_rows(n: int = 150, ticker: str = "AAPL", seed: int = 3) -> pd.DataFrame:
    """A reproducible noisy uptrend -- enough real zigzag to produce genuine
    swings, ATR(14), and the 60-day efficiency ratio (never persisted to
    the DB directly -- returned in place of a real get_or_fetch_bars
    call). The default n=150 (~21 weeks) is deliberately well under
    Weinstein's own MIN_WEEKS_REQUIRED (40) -- most existing tests here
    predate that feature and never intended to exercise it; a real
    Weinstein-stage test passes a longer n explicitly (see
    test_weinstein_stage_fields_round_trip_through_a_real_compute)."""
    rng = np.random.default_rng(seed)
    trend = np.linspace(0, 30, n)
    noise = rng.normal(0, 1.0, size=n).cumsum() * 0.2
    closes = 100 + trend + noise
    return _frame_from_closes(closes, open_off=0.1, high_off=0.5, low_off=0.5)


def test_compute_and_store_trend_analysis_persists_and_returns_matching_result(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    assert result.ticker == "AAPL"
    assert result.trend_state in ("uptrend", "downtrend")
    assert 1 <= result.bar_level <= 5

    with Session(engine) as session:
        row = session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker == "AAPL")).first()
    assert row is not None
    assert row.trend_state == result.trend_state
    assert row.bar_level == result.bar_level


def test_compute_and_store_trend_analysis_raises_when_no_yahoo_data(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_empty(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _empty_frame()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_empty)

    with pytest.raises(ValueError):
        asyncio.run(compute_and_store_trend_analysis("ZZZZINVALID"))


def test_get_trend_analysis_data_cache_only_never_fetches_and_returns_none_when_missing(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    def fail_if_called(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        raise AssertionError("cache_only must never fetch live")

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fail_if_called)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))

    assert result is None


def test_get_trend_analysis_data_computes_when_missing_and_not_cache_only(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=False))

    assert result is not None
    assert result.ticker == "AAPL"


def test_get_trend_analysis_data_returns_fresh_cached_row_without_recomputing(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)
    monkeypatch.setattr(trend_analysis_data_module, "_most_recent_completed_trading_date", lambda: date(2026, 9, 17))

    with Session(engine) as session:
        session.add(
            TrendAnalysis(
                ticker="AAPL",
                computed_at=datetime.now(),
                bars_as_of=date(2026, 9, 17),
                trend_state="uptrend",
                magnitude_tier="strong",
                persistence_count=4,
                bars_since_confirmation=1,
                warning_flag=False,
                efficiency_ratio=0.5,
                regime="trending",
                blended_score=8.0,
                bar_level=5,
            )
        )
        session.commit()

    def fail_if_called(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        raise AssertionError("must not recompute when the cached row is fresh")

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fail_if_called)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=False))

    assert result.bar_level == 5
    assert result.blended_score == 8.0


def test_get_trend_analysis_data_falls_back_to_stale_row_on_yahoo_failure(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    stale_time = datetime.now() - timedelta(days=30)
    with Session(engine) as session:
        session.add(
            TrendAnalysis(
                ticker="AAPL",
                computed_at=stale_time,
                trend_state="downtrend",
                magnitude_tier="weak",
                persistence_count=1,
                bars_since_confirmation=5,
                warning_flag=False,
                blended_score=-3.0,
                bar_level=2,
            )
        )
        session.commit()

    async def fake_empty(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _empty_frame()  # Yahoo has no data -- compute_and_store raises ValueError internally

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_empty)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=False))

    assert result.bar_level == 2  # served the stale row rather than nothing


def test_swing_detail_json_round_trips_through_a_real_compute(monkeypatch):
    """Exercises the actual JSON serialize/deserialize path for
    last_confirmed_swing (a real dataclass -> str column -> SwingDetailOut
    round trip), not just a mocked-out shortcut."""
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    if result.last_confirmed_swing is not None:
        assert isinstance(result.last_confirmed_swing.date, date)
        assert isinstance(result.last_confirmed_swing.ratio, float)

    reread = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))
    assert reread.last_confirmed_swing == result.last_confirmed_swing


def test_ad_bullish_divergence_fields_round_trip_through_a_real_compute(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    assert isinstance(result.ad_bullish_divergence, bool)
    if result.ad_bullish_divergence:
        assert isinstance(result.ad_divergence_swing_date, date)
    else:
        assert result.ad_divergence_swing_date is None

    reread = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))
    assert reread.ad_bullish_divergence == result.ad_bullish_divergence
    assert reread.ad_divergence_swing_date == result.ad_divergence_swing_date


def test_pullback_occurred_since_flip_round_trips_through_a_real_compute(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    assert isinstance(result.pullback_occurred_since_flip, bool)

    reread = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))
    assert reread.pullback_occurred_since_flip == result.pullback_occurred_since_flip


def _synthetic_downtrend_rows(n: int = 150, ticker: str = "AAPL") -> pd.DataFrame:
    """Unlike _synthetic_rows above (a noisy random-walk uptrend), this is a
    deterministic downward-sloping sine wave -- needed to exercise
    reversal_history's real (non-empty) JSON round trip: a random-walk
    series (up OR down) rarely produces enough genuine N=5 fractal swings
    for a reliable, non-flaky test (cumsum'd noise tends to wander too
    smoothly to trip find_swing_highs/find_swing_lows' strict N=5-bars-
    each-side inequality), whereas a clean oscillation reliably produces
    one swing high/low per half-period. Period=14 with a downward slope
    confirmed (by direct inspection) to produce ~9 confirmed LL swings
    across a genuine downtrend."""
    i = np.arange(n)
    closes = 100 + (-0.3 * i) + 5.0 * np.sin(2 * np.pi * i / 14)
    return _frame_from_closes(closes, open_off=0.05, high_off=0.3, low_off=0.3)


def test_reversal_history_round_trips_through_a_real_compute(monkeypatch):
    """Exercises the actual JSON serialize/deserialize path for
    reversal_history (a real list[ReversalCandidate] -> str column ->
    list[ReversalCandidateOut] round trip), not just a mocked-out
    shortcut -- using a genuine downtrend so the list isn't trivially
    empty."""
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _synthetic_downtrend_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    assert result.trend_state == "downtrend"
    assert len(result.reversal_history) >= 1
    for candidate in result.reversal_history:
        assert candidate.swing.classification == "LL"
        assert isinstance(candidate.ad_bullish_divergence, bool)
        if candidate.ad_bullish_divergence:
            assert isinstance(candidate.ad_divergence_swing_date, date)
        else:
            assert candidate.ad_divergence_swing_date is None

    reread = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))
    assert reread.reversal_history == result.reversal_history


def test_sma_position_fields_round_trip_through_a_real_compute(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    # _synthetic_rows() produces 150 bars -- enough for SMA20/50, not SMA200.
    assert result.sma20_position_pct is not None
    assert result.sma20_cross in ("up", "down", None)
    assert result.sma50_position_pct is not None
    assert result.sma50_cross in ("up", "down", None)
    assert result.sma200_position_pct is None
    assert result.sma200_cross is None

    reread = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))
    assert reread.sma20_position_pct == result.sma20_position_pct
    assert reread.sma20_cross == result.sma20_cross
    assert reread.sma50_position_pct == result.sma50_position_pct
    assert reread.sma50_cross == result.sma50_cross
    assert reread.sma200_position_pct == result.sma200_position_pct
    assert reread.sma200_cross == result.sma200_cross


def test_ad_bullish_divergence_reads_as_none_on_a_legacy_pre_migration_row():
    """A row written before this feature's ALTER TABLE migration has NULL in
    both new columns -- must read back as None (falsy), not raise a
    validation error. This is also the regression test for the
    "NEVER COMPUTED" Weinstein state (weinstein_weeks_available is None
    alongside weinstein_stage is None) -- distinct from
    test_weinstein_stage_reads_as_none_below_min_weeks_required's
    "genuinely insufficient" state, where a real compute ran and
    weinstein_weeks_available holds a real (sub-40) count."""
    engine = _fresh_engine()

    with Session(engine) as session:
        session.add(
            TrendAnalysis(
                ticker="AAPL",
                computed_at=datetime.now(),
                trend_state="uptrend",
                magnitude_tier="strong",
                persistence_count=4,
                bars_since_confirmation=1,
                warning_flag=False,
                efficiency_ratio=0.5,
                regime="trending",
                blended_score=8.0,
                bar_level=5,
                # ad_bullish_divergence/ad_divergence_swing_date deliberately omitted
            )
        )
        session.commit()

    with Session(engine) as session:
        row = session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker == "AAPL")).first()

    assert row.ad_bullish_divergence is None
    assert row.ad_divergence_swing_date is None
    assert row.pullback_occurred_since_flip is None
    assert row.sma20_position_pct is None
    assert row.sma20_cross is None
    assert row.sma50_position_pct is None
    assert row.sma50_cross is None
    assert row.sma200_position_pct is None
    assert row.sma200_cross is None
    assert row.weinstein_stage is None
    assert row.weinstein_stage_since_date is None
    assert row.weinstein_stage_since_is_lower_bound is None
    assert row.weinstein_weeks_available is None
    assert row.weinstein_stage_changed is None
    assert row.weinstein_ma_slope_pct is None
    assert row.weinstein_vs_ma_pct is None
    assert row.weinstein_volume_ratio is None
    assert row.weinstein_mansfield_rs is None
    assert row.weinstein_breakout_confirmed is None


def test_weinstein_stage_fields_round_trip_through_a_real_compute(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        # 730 days (~104 weekly bars) clears Weinstein's MIN_WEEKS_REQUIRED
        # with real margin -- ^GSPC returns empty here since this test is
        # about the stage/breakout fields, not Mansfield RS specifically.
        return _empty_frame() if ticker == WEINSTEIN_BENCHMARK_TICKER else _synthetic_rows(n=730)

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    assert result.weinstein_stage in ("base", "advance", "top", "decline")
    assert isinstance(result.weinstein_stage_since_is_lower_bound, bool)
    assert result.weinstein_weeks_available is not None and result.weinstein_weeks_available >= 40
    assert isinstance(result.weinstein_breakout_confirmed, bool)
    assert isinstance(result.weinstein_stage_changed, bool)
    assert result.weinstein_mansfield_rs is None  # no benchmark data supplied in this test

    reread = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))
    assert reread.weinstein_stage == result.weinstein_stage
    assert reread.weinstein_stage_since_date == result.weinstein_stage_since_date
    assert reread.weinstein_stage_since_is_lower_bound == result.weinstein_stage_since_is_lower_bound
    assert reread.weinstein_weeks_available == result.weinstein_weeks_available
    assert reread.weinstein_ma_slope_pct == result.weinstein_ma_slope_pct
    assert reread.weinstein_vs_ma_pct == result.weinstein_vs_ma_pct
    assert reread.weinstein_volume_ratio == result.weinstein_volume_ratio
    assert reread.weinstein_breakout_confirmed == result.weinstein_breakout_confirmed


def test_weinstein_stage_reads_as_none_below_min_weeks_required(monkeypatch):
    """The GENUINELY-insufficient-history state: a real compute ran and
    found real, but too-thin, weekly data -- weinstein_weeks_available
    holds that real (sub-40) count. Distinct from a legacy/never-
    reprocessed row, where the column itself is NULL (see
    test_ad_bullish_divergence_reads_as_none_on_a_legacy_pre_migration_row)."""
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        # Default n=150 (~21 weeks), well under MIN_WEEKS_REQUIRED (40).
        return _empty_frame() if ticker == WEINSTEIN_BENCHMARK_TICKER else _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    assert result.weinstein_stage is None
    assert result.weinstein_weeks_available is not None
    assert result.weinstein_weeks_available < 40
    assert result.weinstein_stage_changed is False


def test_weinstein_stage_changed_reflects_a_real_difference_from_the_prior_stored_value(monkeypatch):
    """weinstein_stage_changed is an ACROSS-RUNS comparison against
    whatever was stored BEFORE this write -- deliberately distinct from
    weinstein_breakout_confirmed's own single-run, week-over-week
    comparison (already covered by analysis/trend_structure/test_weinstein.py)."""
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        return _empty_frame() if ticker == WEINSTEIN_BENCHMARK_TICKER else _synthetic_rows(n=730)

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)

    first = asyncio.run(compute_and_store_trend_analysis("AAPL"))
    assert first.weinstein_stage_changed is False  # brand-new ticker, nothing to compare against yet

    second = asyncio.run(compute_and_store_trend_analysis("AAPL"))
    assert second.weinstein_stage == first.weinstein_stage  # same deterministic series recomputed
    assert second.weinstein_stage_changed is False  # ...so no real change from last night

    with Session(engine) as session:
        row = session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker == "AAPL")).first()
        row.weinstein_stage = next(s for s in ("base", "advance", "top", "decline") if s != row.weinstein_stage)
        session.add(row)
        session.commit()

    third = asyncio.run(compute_and_store_trend_analysis("AAPL"))
    assert third.weinstein_stage == first.weinstein_stage  # deterministic recompute, same real answer
    assert third.weinstein_stage_changed is True  # ...but it now differs from the mutated stored value


# ---------------------------------------------------------------------------
# Close-aware freshness of the stored row (bars_as_of vs. the most recently
# completed session), replacing the old flat computed_at timer.
# ---------------------------------------------------------------------------

_SESSION = date(2026, 9, 17)  # a Thursday


def _ending_on(frame: pd.DataFrame, end: date) -> pd.DataFrame:
    """Same bars, re-dated so the LAST one is `end` (one bar per day)."""
    n = len(frame)
    out = frame.copy()
    out.index = pd.DatetimeIndex([end - timedelta(days=n - 1 - i) for i in range(n)])
    return out


def _insert_row(engine, *, computed_at: datetime, bars_as_of: date | None) -> None:
    with Session(engine) as session:
        session.add(
            TrendAnalysis(
                ticker="AAPL",
                computed_at=computed_at,
                bars_as_of=bars_as_of,
                trend_state="uptrend",
                magnitude_tier="strong",
                persistence_count=4,
                bars_since_confirmation=1,
                warning_flag=False,
                efficiency_ratio=0.5,
                regime="trending",
                blended_score=8.0,
                bar_level=5,
            )
        )
        session.commit()


def _pin_session(monkeypatch, session_date: date) -> None:
    monkeypatch.setattr(trend_analysis_data_module, "_most_recent_completed_trading_date", lambda: session_date)


def _count_fetches(monkeypatch, frame: pd.DataFrame) -> list[str]:
    calls: list[str] = []

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, auto_adjust=False, **kwargs):
        calls.append(ticker)
        return frame

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_bars", fake_get_or_fetch_bars)
    return calls


def test_compute_persists_the_last_bar_date_it_was_computed_from(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)
    _count_fetches(monkeypatch, _ending_on(_synthetic_rows(), _SESSION - timedelta(days=1)))

    asyncio.run(compute_and_store_trend_analysis("AAPL"))

    with Session(engine) as session:
        assert session.get(TrendAnalysis, "AAPL").bars_as_of == _SESSION - timedelta(days=1)


def test_a_row_computed_minutes_ago_is_still_recomputed_when_a_newer_session_has_completed(monkeypatch):
    """The regression this build fixes, end to end: the old flat timer would
    have called a row computed a minute ago "fresh" (1-day window) even though
    a whole new session had since closed and its bar is sitting in the shared
    cache. Now the stored row's own last-bar date is what's compared."""
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)
    base = _synthetic_rows()

    _pin_session(monkeypatch, _SESSION - timedelta(days=1))
    _count_fetches(monkeypatch, _ending_on(base, _SESSION - timedelta(days=1)))
    first = asyncio.run(get_trend_analysis_data("AAPL"))  # night 1: computes from bars ending Wed
    assert first is not None

    _pin_session(monkeypatch, _SESSION)  # Thursday's session closes; its bar lands in the cache
    calls = _count_fetches(monkeypatch, _ending_on(base, _SESSION))
    second = asyncio.run(get_trend_analysis_data("AAPL"))

    assert (datetime.now() - first.computed_at) < timedelta(minutes=5)  # old timer: nowhere near expired
    assert calls == ["AAPL", "^GSPC"]  # ...but it recomputed anyway
    with Session(engine) as session:
        assert session.get(TrendAnalysis, "AAPL").bars_as_of == _SESSION
    assert second.computed_at > first.computed_at


def test_a_row_is_not_recomputed_when_only_the_old_timer_expired_but_its_bars_are_current(monkeypatch):
    """Weekend shape: computed_at is days old (the old timer said stale), yet
    its bars already reach the most recently completed session -- nothing
    new exists to compute from, so it must NOT be recomputed."""
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)
    _pin_session(monkeypatch, _SESSION)
    _insert_row(engine, computed_at=datetime.now() - timedelta(days=3), bars_as_of=_SESSION)
    calls = _count_fetches(monkeypatch, _synthetic_rows())

    result = asyncio.run(get_trend_analysis_data("AAPL"))

    assert calls == []
    assert result.bar_level == 5


def test_a_row_from_before_the_column_existed_is_recomputed_once(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)
    _pin_session(monkeypatch, _SESSION)
    _insert_row(engine, computed_at=datetime.now(), bars_as_of=None)
    calls = _count_fetches(monkeypatch, _ending_on(_synthetic_rows(), _SESSION))

    asyncio.run(get_trend_analysis_data("AAPL"))
    assert calls == ["AAPL", "^GSPC"]

    calls.clear()
    asyncio.run(get_trend_analysis_data("AAPL"))  # now stamped -- steady state, no more recomputes
    assert calls == []


def test_cache_only_reads_never_recompute_regardless_of_how_stale_bars_as_of_is(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)
    _pin_session(monkeypatch, _SESSION)
    _insert_row(engine, computed_at=datetime.now() - timedelta(days=30), bars_as_of=_SESSION - timedelta(days=30))
    calls = _count_fetches(monkeypatch, _synthetic_rows())

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))

    assert calls == []
    assert result.bar_level == 5
