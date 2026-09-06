"""Stan Weinstein's classic 4-stage (Base/Advance/Top/Decline) analysis --
computed entirely on WEEKLY bars, independent of the daily-bar swing/BOS
engine in engine.py. See CLAUDE.md's "Trend structure analysis (Technical)"
section for the full methodology and the Pine Script v6 source this is
ported from.

Weekly bars are derived by resampling the SAME daily OHLCV frame the
swing/BOS engine already receives (resample_to_weekly), not a second Yahoo
Finance fetch -- confirmed bit-identical to yfinance's own native
interval="1wk" bars once anchored correctly (see resample_to_weekly's own
docstring for the exact anchoring rule this depends on).

The state machine (compute_stage_series) is the STICKY variant from the
Pine source (its own `sState`), not the stateless per-bar quadrant read
(`sTS`) the script's own tsMode default actually renders -- chosen after an
empirical comparison across real tickers found the stateless read flickers
into false Top/Base readings on ordinary single-week volatility within an
established trend (e.g. a stock deep in a downtrend popping briefly above
its own falling 30-week MA), while the sticky machine requires clearing a
+/-5% band with genuine slope confirmation before it will ever change its
mind -- much closer to what "stage analysis" is supposed to mean (a
multi-month/quarter regime read, not a bar-by-bar indicator).
"""

from datetime import date

import pandas as pd

from .types import WeinsteinStage, WeinsteinStageResult

WEINSTEIN_BENCHMARK_TICKER = "^GSPC"

MA_LEN = 30
SLOPE_LOOKBACK = 5
WITHIN_RANGE_PCT = 5.0
VOLUME_AVG_LEN = 30
VOLUME_CONFIRM_MULTIPLIER = 2.0
RS_SMOOTHING_LEN = 52
# MA_LEN + SLOPE_LOOKBACK (the bare structural minimum for the MA/slope to
# have a first valid value) + a 5-week margin. Empirically validated
# (full-history backtest across 15 real tickers, ~245 historical anchor
# points): at >=104 weeks (2y) the sticky state machine's bootstrap error
# (starting from an arbitrary state=0) has ALWAYS washed out to match the
# true full-history stage; at this 40-week floor a small residual
# bootstrap-inaccuracy risk remains (~1.6% of anchors tested at exactly 52
# weeks mismatched) -- an accepted, documented limitation for a newer
# ticker that doesn't yet have a full 2y of daily history, not something
# this module tries to fix further.
MIN_WEEKS_REQUIRED = MA_LEN + SLOPE_LOOKBACK + 5

# Internal sState encoding (1=Base, 2=Advance, 3=Top, 4=Decline, 0=not yet
# seeded/pre-bootstrap), translated to the public string enum on the way
# out of compute_stage_series.
_STATE_LABEL: dict[int, WeinsteinStage | None] = {0: None, 1: "base", 2: "advance", 3: "top", 4: "decline"}


def resample_to_weekly(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Resamples a daily OHLCV frame (lowercase open/high/low/close/volume
    columns, matching YahooPriceCache's own naming) into weekly bars.

    Confirmed bit-identical (mean/max diff ~0.0000%) to yfinance's own
    native interval="1wk" bars, PROVIDED weeks are anchored correctly:
    yfinance labels each weekly bar by its MONDAY (week start), while a
    naive `resample("W-FRI")` labels by the week's Friday (week end) -- a
    4-day offset. Resampling "W-FRI" (which correctly bins Mon-Fri trading
    days into one bucket, since Sat/Sun have no data anyway) and then
    shifting the resulting index back 4 days reproduces yfinance's own
    Monday-anchored label exactly. Do NOT use "W-MON" -- that bins
    Tue-through-Mon, the wrong days entirely for a Mon-Fri trading week.
    """
    if ohlcv.empty:
        return ohlcv

    weekly = (
        ohlcv.resample("W-FRI")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
    )
    weekly.index = weekly.index - pd.Timedelta(days=4)
    return weekly


def compute_stage_series(weekly_close: pd.Series) -> pd.DataFrame:
    """Ports the Pine source's sticky `sState` state machine bar-by-bar,
    including its `var int sState := ...` persistence across bars (a week
    with no valid MA/slope yet leaves the running state unchanged, exactly
    like Pine's `if valid` guard around the whole reassignment).

    Returns a DataFrame indexed like `weekly_close` with columns:
    ma, slope, valid, stage (WeinsteinStage | None -- None for every week
    before the state machine has ever seen a single valid MA/slope pair,
    i.e. the bootstrap period; a real string thereafter, never reverting to
    None once seeded).
    """
    ma = weekly_close.rolling(window=MA_LEN, min_periods=MA_LEN).mean()
    ma_prev = ma.shift(SLOPE_LOOKBACK)
    valid = ma.notna() & ma_prev.notna()
    slope = (ma - ma_prev) / ma_prev * 100.0

    band = WITHIN_RANGE_PCT / 100.0
    above_band = valid & (weekly_close > ma * (1.0 + band))
    below_band = valid & (weekly_close < ma * (1.0 - band))
    rising = valid & (slope > 0.0)
    falling = valid & (slope < 0.0)

    stage: list[WeinsteinStage | None] = []
    prev_state = 0
    for i in range(len(weekly_close)):
        if not bool(valid.iloc[i]):
            stage.append(_STATE_LABEL.get(prev_state))
            continue
        r, f = bool(rising.iloc[i]), bool(falling.iloc[i])
        ab, bb = bool(above_band.iloc[i]), bool(below_band.iloc[i])
        if prev_state == 2:  # Advance
            new_state = 4 if (f and bb) else (3 if not r else 2)
        elif prev_state == 3:  # Top
            new_state = 2 if (r and ab) else (4 if (f and bb) else 3)
        elif prev_state == 4:  # Decline
            new_state = 2 if (r and ab) else (1 if not f else 4)
        elif prev_state == 1:  # Base
            new_state = 4 if (f and bb) else (2 if (r and ab) else 1)
        else:  # pre-bootstrap
            if r and ab:
                new_state = 2
            elif f and bb:
                new_state = 4
            elif r or ab:
                new_state = 3
            else:
                new_state = 1
        prev_state = new_state
        stage.append(_STATE_LABEL[new_state])

    return pd.DataFrame({"ma": ma, "slope": slope, "valid": valid, "stage": stage}, index=weekly_close.index)


def _stage_since(stage_series: pd.Series) -> tuple[date | None, bool]:
    """Walks the non-null (post-bootstrap) suffix of `stage_series`
    backward from its latest entry to find the start of the CURRENT stage.
    Returns (None, False) if there's no non-null week at all yet.
    """
    valid_stage = stage_series.dropna()
    if valid_stage.empty:
        return None, False

    current = valid_stage.iloc[-1]
    differing = valid_stage[valid_stage != current]
    if differing.empty:
        # Stage has been constant across the ENTIRE available (post-
        # bootstrap) history -- the true start predates this window, so
        # this is a lower bound, not a precise transition date.
        earliest = valid_stage.index[0]
        return (earliest.date() if hasattr(earliest, "date") else earliest), True

    last_differing_date = differing.index[-1]
    since_series = valid_stage[valid_stage.index > last_differing_date]
    since_date = since_series.index[0]
    return (since_date.date() if hasattr(since_date, "date") else since_date), False


def compute_weinstein_stage(ohlcv: pd.DataFrame, benchmark_ohlcv: pd.DataFrame) -> WeinsteinStageResult:
    """ohlcv/benchmark_ohlcv are both daily-indexed frames matching
    engine.py::compute_trend_structure's own contract (lowercase
    open/high/low/close/volume). benchmark_ohlcv may be empty (e.g. the
    ^GSPC fetch failed that run) -- Mansfield RS/breakout's RS gate degrade
    gracefully rather than raising, matching the Pine source's own
    na(mansfield)-passes-through convention.
    """
    ticker_weekly = resample_to_weekly(ohlcv)
    if len(ticker_weekly) < MIN_WEEKS_REQUIRED:
        return WeinsteinStageResult(
            stage=None,
            stage_since_date=None,
            stage_since_is_lower_bound=False,
            ma_slope_pct=None,
            vs_ma_pct=None,
            volume_ratio=None,
            mansfield_rs=None,
            breakout_confirmed=False,
        )

    stage_df = compute_stage_series(ticker_weekly["close"])
    latest = stage_df.iloc[-1]
    current_stage = latest["stage"]

    ma_slope_pct = float(latest["slope"]) if pd.notna(latest["slope"]) else None
    vs_ma_pct = (
        float((ticker_weekly["close"].iloc[-1] - latest["ma"]) / latest["ma"] * 100.0) if pd.notna(latest["ma"]) else None
    )

    volume_avg = ticker_weekly["volume"].rolling(window=VOLUME_AVG_LEN, min_periods=VOLUME_AVG_LEN).mean()
    latest_volume_avg = volume_avg.iloc[-1]
    volume_ratio = (
        float(ticker_weekly["volume"].iloc[-1] / latest_volume_avg)
        if pd.notna(latest_volume_avg) and latest_volume_avg > 0
        else None
    )

    mansfield_rs = None
    if not benchmark_ohlcv.empty:
        benchmark_weekly = resample_to_weekly(benchmark_ohlcv)
        if not benchmark_weekly.empty:
            # Reindexed onto the ticker's own weekly index BEFORE dividing --
            # the two frames are resampled independently, so a thin-history
            # ticker's index is a strict subset of the benchmark's; a naive
            # Series-to-Series division would otherwise align on the UNION
            # of both indices and introduce spurious NaN rows outside the
            # ticker's own range.
            benchmark_close = benchmark_weekly["close"].reindex(ticker_weekly.index)
            rs_ratio = ticker_weekly["close"] / benchmark_close
            rs_smoothed = rs_ratio.rolling(window=RS_SMOOTHING_LEN, min_periods=RS_SMOOTHING_LEN).mean()
            latest_rs_smoothed = rs_smoothed.iloc[-1]
            if pd.notna(latest_rs_smoothed) and latest_rs_smoothed != 0:
                mansfield_rs = float((rs_ratio.iloc[-1] / latest_rs_smoothed - 1.0) * 100.0)

    vol_ok = volume_ratio is not None and volume_ratio >= VOLUME_CONFIRM_MULTIPLIER
    rs_ok = mansfield_rs is None or mansfield_rs > 0.0

    non_null_stage = stage_df["stage"].dropna()
    previous_valid_stage = non_null_stage.iloc[-2] if len(non_null_stage) >= 2 else None
    breakout_confirmed = bool(
        current_stage == "advance"
        and previous_valid_stage is not None
        and previous_valid_stage != "advance"
        and vol_ok
        and rs_ok
    )

    stage_since_date, stage_since_is_lower_bound = _stage_since(stage_df["stage"])

    return WeinsteinStageResult(
        stage=current_stage,
        stage_since_date=stage_since_date,
        stage_since_is_lower_bound=stage_since_is_lower_bound,
        ma_slope_pct=ma_slope_pct,
        vs_ma_pct=vs_ma_pct,
        volume_ratio=volume_ratio,
        mansfield_rs=mansfield_rs,
        breakout_confirmed=breakout_confirmed,
    )
