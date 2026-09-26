"""Stan Weinstein's classic 4-stage (Base/Advance/Top/Decline) analysis --
computed entirely on WEEKLY bars, independent of the daily-bar swing/BOS
engine in engine.py. See CLAUDE.md's "Trend structure analysis (Technical)"
section for the surrounding feature.

Weekly bars are derived by resampling the SAME daily OHLCV frame the
swing/BOS engine already receives (resample_to_weekly), not a second fetch --
confirmed bit-identical to yfinance's own native interval="1wk" bars once
anchored correctly (see resample_to_weekly's own docstring).

The engine is the sticky `sState` machine of a reviewed Pine Script
reference, fully parameterised by WeinsteinParams (editable in Settings,
read live from the DB by the callers -- this module never touches the DB):
  m = MA(close, ma_length, ma_type); m_prev = m shifted slope_lookback weeks;
  slope_pct = (m - m_prev)/m_prev*100; rising/falling = slope >/< 0;
  above/below_band = close beyond m*(1 +/- within_range_pct/100).
The next state is a function of the previous one (1 Base, 2 Advance, 3 Top,
4 Decline); nothing is assigned until the MA and its slope are both valid.
Volume and relative strength never gate the state machine -- they only feed
`breakout_confirmed`: a transition INTO Advance in the latest week with
volume_ratio >= breakout_volume_mult AND (Mansfield RS unavailable OR > 0).

It is the sticky machine, not the stateless per-bar quadrant read (`sTS`):
an empirical comparison across real tickers found the stateless read
flickers into false Top/Base readings on ordinary single-week volatility
within an established trend, while the sticky machine requires clearing the
band with genuine slope confirmation before it changes its mind.

The previous production engine (fixed 30-week SMA, fixed 5% band, 30-week
volume average) was replaced outright by this one; the state-machine
transition rules themselves are unchanged -- what differs is the
configurable MA (EMA by default), the 50-week volume average, and the fact
that the caller now hands in ~5y of daily history so the machine has a long
run-in (see WEINSTEIN_LOOKBACK_DAYS in data/trend_analysis_data.py).
"""

import json
from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
import pandas as pd

from .types import WeinsteinStage, WeinsteinStageResult

# Default Mansfield RS benchmark. SPY, not the ^GSPC index itself (2026-09-23
# Massive migration decision): Massive/Polygon has no Indices product on the
# Stocks Starter plan and, being a pseudo-ticker, ^GSPC was never coverable
# there. The nightly job fetches whatever WeinsteinParams.rs_benchmark names
# (default this) in the same batch as the tickers. Mansfield RS's ratio math
# is level-invariant, so an ETF's different price scale vs an index level
# doesn't change the result.
WEINSTEIN_BENCHMARK_TICKER = "SPY"

MA_TYPES = ("SMA", "EMA")

# Internal state encoding (1=Base, 2=Advance, 3=Top, 4=Decline, 0=not yet
# seeded), translated to the public string enum on the way out.
_STATE_LABEL: dict[int, WeinsteinStage | None] = {0: None, 1: "base", 2: "advance", 3: "top", 4: "decline"}


@dataclass(frozen=True)
class WeinsteinParams:
    """The 8 admin-editable engine parameters (Settings > Weinstein; stored
    in models.py::WeinsteinSettings). Defaults are the validated Pine
    reference's own."""

    ma_length: int = 30
    ma_type: str = "EMA"
    within_range_pct: float = 5.0
    slope_lookback: int = 5
    breakout_volume_mult: float = 2.0
    volume_avg_length: int = 50
    rs_benchmark: str = WEINSTEIN_BENCHMARK_TICKER
    rs_smoothing_length: int = 52

    @property
    def band(self) -> float:
        return self.within_range_pct / 100.0

    @property
    def min_weeks_required(self) -> int:
        """The bare structural floor (first valid MA + slope pair) plus a
        5-week margin. Below it the engine returns a graceful stage=None
        rather than an unreliable number."""
        return self.ma_length + self.slope_lookback + 5

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(raw: str | None) -> "WeinsteinParams | None":
        if not raw:
            return None
        try:
            return WeinsteinParams(**json.loads(raw))
        except (TypeError, ValueError):
            return None


def resample_to_weekly(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Resamples a daily OHLCV frame (lowercase open/high/low/close/volume
    columns, matching SharedBarsCache's own naming) into weekly bars.

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


def compute_ma(close: pd.Series, length: int, ma_type: str) -> pd.Series:
    """EMA is recursive (span=length, adjust=False, first `length` weeks
    masked) -- not the same as an SMA seeded identically; SMA is the plain
    rolling mean."""
    kind = ma_type.upper()
    if kind == "EMA":
        return close.ewm(span=length, adjust=False, min_periods=length).mean()
    if kind == "SMA":
        return close.rolling(window=length, min_periods=length).mean()
    raise ValueError(f"ma_type must be one of {MA_TYPES}, got {ma_type!r}")


def next_state(prev: int, rising: bool, falling: bool, above: bool, below: bool) -> int:
    """One step of the sticky sState machine. prev == 0 is the first valid
    week (unseeded)."""
    if prev == 2:  # Advance
        return 4 if (falling and below) else (3 if not rising else 2)
    if prev == 3:  # Top
        return 2 if (rising and above) else (4 if (falling and below) else 3)
    if prev == 4:  # Decline
        return 2 if (rising and above) else (1 if not falling else 4)
    if prev == 1:  # Base
        return 4 if (falling and below) else (2 if (rising and above) else 1)
    if rising and above:
        return 2
    if falling and below:
        return 4
    return 3 if (rising or above) else 1


def compute_stage_series(weekly_close: pd.Series, params: WeinsteinParams) -> pd.DataFrame:
    """Runs the sticky state machine bar-by-bar (a week with no valid
    MA/slope yet leaves the running state unchanged, like Pine's
    `if valid`).

    Returns a DataFrame indexed like `weekly_close` with columns:
    ma, slope, valid, stage (WeinsteinStage | None -- None for every week
    before the machine has seen a valid MA/slope pair, a real string
    thereafter), and stage_num (float, NaN pre-seed, 1-4 after)."""
    ma = compute_ma(weekly_close, params.ma_length, params.ma_type)
    ma_prev = ma.shift(params.slope_lookback)
    valid = ma.notna() & ma_prev.notna()
    slope = (ma - ma_prev) / ma_prev * 100.0

    band = params.band
    above_band = valid & (weekly_close > ma * (1.0 + band))
    below_band = valid & (weekly_close < ma * (1.0 - band))
    rising = valid & (slope > 0.0)
    falling = valid & (slope < 0.0)

    v, r_arr, f_arr = valid.to_numpy(), rising.to_numpy(), falling.to_numpy()
    ab_arr, bb_arr = above_band.to_numpy(), below_band.to_numpy()
    n = len(weekly_close)
    nums = np.full(n, np.nan)
    stage: list[WeinsteinStage | None] = []
    prev_state = 0
    for i in range(n):
        if v[i]:
            prev_state = next_state(prev_state, bool(r_arr[i]), bool(f_arr[i]), bool(ab_arr[i]), bool(bb_arr[i]))
            nums[i] = prev_state
        stage.append(_STATE_LABEL[prev_state])

    return pd.DataFrame({"ma": ma, "slope": slope, "valid": valid, "stage": stage, "stage_num": nums}, index=weekly_close.index)


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


def compute_weinstein_stage(ohlcv: pd.DataFrame, benchmark_ohlcv: pd.DataFrame, params: WeinsteinParams | None = None) -> WeinsteinStageResult:
    """ohlcv/benchmark_ohlcv are both daily-indexed frames matching
    engine.py::compute_trend_structure's own contract (lowercase
    open/high/low/close/volume). benchmark_ohlcv may be empty (e.g. the
    benchmark fetch failed that run) -- Mansfield RS and the breakout's RS
    gate degrade gracefully (RS unavailable passes the gate, the Pine
    source's own na(mansfield) convention) rather than raising.

    Every ticker's whole passed-in history is replayed, so stage_since_date
    is the date of the ticker's most recent REAL transition under this
    engine (not a reset-to-today); it is a lower bound only when the stage
    never changed anywhere in the available history."""
    p = params or WeinsteinParams()
    ticker_weekly = resample_to_weekly(ohlcv)
    weeks_available = len(ticker_weekly)
    if weeks_available < p.min_weeks_required:
        return WeinsteinStageResult(
            stage=None,
            stage_since_date=None,
            stage_since_is_lower_bound=False,
            ma_slope_pct=None,
            vs_ma_pct=None,
            volume_ratio=None,
            mansfield_rs=None,
            breakout_confirmed=False,
            weeks_available=weeks_available,
        )

    close = ticker_weekly["close"]
    stage_df = compute_stage_series(close, p)
    latest = stage_df.iloc[-1]
    current_stage = latest["stage"]

    ma_slope_pct = float(latest["slope"]) if pd.notna(latest["slope"]) else None
    vs_ma_pct = float((close.iloc[-1] - latest["ma"]) / latest["ma"] * 100.0) if pd.notna(latest["ma"]) else None

    volume_avg = ticker_weekly["volume"].rolling(window=p.volume_avg_length, min_periods=p.volume_avg_length).mean()
    latest_volume_avg = volume_avg.iloc[-1]
    volume_ratio = (
        float(ticker_weekly["volume"].iloc[-1] / latest_volume_avg)
        if pd.notna(latest_volume_avg) and latest_volume_avg > 0
        else None
    )

    mansfield_rs = None
    if benchmark_ohlcv is not None and not benchmark_ohlcv.empty:
        benchmark_weekly = resample_to_weekly(benchmark_ohlcv)
        if not benchmark_weekly.empty:
            # Reindexed onto the ticker's own weekly index BEFORE dividing --
            # the two frames are resampled independently, so a naive
            # Series-to-Series division would align on the UNION of both
            # indices and introduce spurious NaN rows.
            benchmark_close = benchmark_weekly["close"].reindex(close.index)
            rs_ratio = close / benchmark_close
            rs_smoothed = rs_ratio.rolling(window=p.rs_smoothing_length, min_periods=p.rs_smoothing_length).mean()
            latest_rs_smoothed = rs_smoothed.iloc[-1]
            if pd.notna(latest_rs_smoothed) and latest_rs_smoothed != 0:
                mansfield_rs = float((rs_ratio.iloc[-1] / latest_rs_smoothed - 1.0) * 100.0)

    vol_ok = volume_ratio is not None and volume_ratio >= p.breakout_volume_mult
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
        weeks_available=weeks_available,
        ma_slope_pct=ma_slope_pct,
        vs_ma_pct=vs_ma_pct,
        volume_ratio=volume_ratio,
        mansfield_rs=mansfield_rs,
        breakout_confirmed=breakout_confirmed,
    )
