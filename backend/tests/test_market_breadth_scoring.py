import numpy as np
import pandas as pd

from scoring.market_breadth import HL_WINDOW, aggregate_flags, snapshot_frame, ticker_flags


def _bars(closes, start="2025-01-01", spread=1.0) -> pd.DataFrame:
    index = pd.bdate_range(start=start, periods=len(closes))
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame({"open": close, "high": close + spread, "low": close - spread, "close": close, "volume": 1000})


def _flags_for(frame: pd.DataFrame) -> pd.DataFrame:
    return ticker_flags({"X": frame})["X"]


def test_sma_flags_need_the_full_window_and_use_a_strict_close_above_sma():
    flags = _flags_for(_bars(np.linspace(100, 200, 260)))
    # Rising series: above its own SMA whenever the SMA exists.
    assert flags["sma20_eligible"].sum() == 260 - 19
    assert flags["sma20_above"].sum() == flags["sma20_eligible"].sum()
    assert flags["sma50_eligible"].sum() == 260 - 49
    assert flags["sma50_above"].sum() == flags["sma50_eligible"].sum()
    assert flags["sma200_eligible"].sum() == 260 - 199
    assert flags["sma200_above"].iloc[:199].sum() == 0

    flat = _flags_for(_bars([100.0] * 260))
    # close == SMA is not "above".
    assert flat["sma50_eligible"].sum() == 211 and flat["sma50_above"].sum() == 0
    assert flat["sma20_eligible"].sum() == 241 and flat["sma20_above"].sum() == 0


def test_a_ticker_too_young_for_a_window_is_ineligible_not_below():
    flags = _flags_for(_bars(np.linspace(100, 90, 120)))
    assert flags["sma50_eligible"].sum() == 71 and flags["sma50_above"].sum() == 0
    assert flags["sma200_eligible"].sum() == 0
    assert flags["sma20_eligible"].sum() == 101 and flags["sma20_above"].sum() == 0
    assert flags["hl_eligible"].sum() == 0 and flags["new_highs"].sum() == 0 and flags["new_lows"].sum() == 0


def test_sma20_needs_only_20_own_bars_so_it_is_eligible_wherever_sma50_is():
    # 30 bars: a ticker too young for the 50-day is still measurable on the 20-day.
    flags = _flags_for(_bars(np.linspace(100, 130, 30)))
    assert flags["sma20_eligible"].sum() == 11 and flags["sma50_eligible"].sum() == 0
    assert _flags_for(_bars([100.0] * 19))["sma20_eligible"].sum() == 0
    assert _flags_for(_bars([100.0] * 20))["sma20_eligible"].sum() == 1
    # Shorter window, so eligibility is a superset at every session.
    full = _flags_for(_bars(np.linspace(100, 200, 260)))
    assert (full["sma20_eligible"] >= full["sma50_eligible"]).all() and (full["sma50_eligible"] >= full["sma200_eligible"]).all()


def test_sma20_reacts_to_a_recent_dip_the_slower_averages_ignore():
    # A long uptrend, then a 5-day pullback: below the 20-day SMA while still above the 50- and 200-day.
    closes = list(np.linspace(50, 200, 255)) + [199.0, 197.0, 195.0, 193.0, 190.0]
    last = _flags_for(_bars(closes)).iloc[-1]
    assert last["sma20_above"] == 0 and last["sma50_above"] == 1 and last["sma200_above"] == 1


def test_52_week_high_and_low_use_intraday_extremes_over_252_own_bars_with_ties_counting():
    closes = [100.0] * (HL_WINDOW + 2)
    frame = _bars(closes, spread=2.0)
    frame.iloc[-2, frame.columns.get_loc("high")] = 110.0  # a prior peak
    frame.iloc[-1, frame.columns.get_loc("high")] = 110.0  # today ties it -> still a new high
    frame.iloc[-1, frame.columns.get_loc("low")] = 90.0  # today undercuts every low -> new low
    flags = _flags_for(frame)

    assert flags["hl_eligible"].sum() == 3  # bars 252, 253, 254
    assert flags["new_highs"].iloc[-1] == 1
    assert flags["new_lows"].iloc[-1] == 1
    # A close-only rule would see nothing: closes never moved.
    assert (frame["close"] == 100.0).all()


def test_a_full_252_bar_window_is_required():
    assert _flags_for(_bars([100.0] * (HL_WINDOW - 1)))["hl_eligible"].sum() == 0
    assert _flags_for(_bars([100.0] * HL_WINDOW))["hl_eligible"].sum() == 1


def test_a_missing_bar_inside_the_window_does_not_disqualify_a_ticker():
    # The investigation's FISV case: 500 real bars with one gap must stay
    # eligible because windows count the ticker's OWN bars, not calendar rows.
    frame = _bars(np.linspace(100, 150, 300))
    gappy = frame.drop(frame.index[200])
    other = _bars(np.linspace(100, 150, 300))
    flags = ticker_flags({"GAP": gappy, "FULL": other})
    counts = aggregate_flags(flags)

    last = counts.index[-1]
    assert flags["GAP"].loc[last, "hl_eligible"] == 1
    assert counts.loc[last, "hl_eligible"] == 2
    # On the gap date only the ticker with a bar counts.
    assert counts.loc[frame.index[200], "with_bar"] == 1


def test_nan_rows_are_not_bars_and_tz_aware_indexes_line_up():
    frame = _bars(np.linspace(100, 120, 60))
    frame.iloc[10, frame.columns.get_loc("close")] = np.nan
    tz_frame = _bars(np.linspace(100, 120, 60))
    tz_frame.index = tz_frame.index.tz_localize("America/New_York")

    flags = ticker_flags({"NAN": frame, "TZ": tz_frame})
    assert len(flags["NAN"]) == 59
    assert flags["TZ"].index.tz is None
    assert aggregate_flags(flags).loc[tz_frame.index[-1].tz_localize(None), "with_bar"] == 2


def test_empty_and_missing_frames_are_skipped():
    assert ticker_flags({"A": pd.DataFrame(), "B": None}) == {}
    assert aggregate_flags({}).empty


def test_aggregate_sums_across_tickers_per_session():
    up = _bars(np.linspace(100, 200, 260))
    down = _bars(np.linspace(200, 100, 260))
    counts = aggregate_flags(ticker_flags({"UP": up, "DOWN": down}))
    last = counts.iloc[-1]
    assert last["with_bar"] == 2 and last["sma50_eligible"] == 2 and last["sma50_above"] == 1
    assert last["sma20_eligible"] == 2 and last["sma20_above"] == 1
    assert last["sma200_above"] == 1


def test_snapshot_frame_derives_percentages_net_highs_and_stale_excluded():
    counts = pd.DataFrame(
        {
            "with_bar": [8, 10], "sma20_eligible": [0, 10], "sma20_above": [0, 2], "sma50_eligible": [0, 10], "sma50_above": [0, 3], "sma200_eligible": [0, 8], "sma200_above": [0, 4],
            "hl_eligible": [0, 7], "new_highs": [0, 5], "new_lows": [0, 2],
        },
        index=pd.to_datetime(["2026-09-17", "2026-09-18"]),
    )
    snap = snapshot_frame(counts, constituents=12)

    first, second = snap.iloc[0], snap.iloc[1]
    assert np.isnan(first["pct_above_sma20"]) and np.isnan(first["pct_above_sma50"]) and np.isnan(first["pct_above_sma200"])  # eligible == 0, not 0%
    assert second["pct_above_sma20"] == 20.0 and second["pct_above_sma50"] == 30.0 and second["pct_above_sma200"] == 50.0
    assert second["sma20_eligible"] == 10 and second["sma20_above"] == 2
    assert second["net_new_highs"] == 3 and second["stale_excluded"] == 2 and second["constituents"] == 12
