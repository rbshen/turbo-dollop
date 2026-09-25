"""Standalone research script: an alternative, simplified Weinstein 4-stage
classifier on weekly bars, compared against production's `weinstein_stage`.

NOT wired into any cron job, API route, or the app. Read-only against the real
DB (SharedBarsCache for bars, TrendAnalysis for the production stage) -- it
never writes, so the "ad-hoc scripts must not touch the real database" rule
in CLAUDE.md is respected.

Reuses production's own pieces so results are apples-to-apples:
  * bars: the same daily SharedBarsCache rows the nightly trend job reads,
    resampled by analysis.trend_structure.weinstein.resample_to_weekly
  * slope: production's definition -- percent change of the MA over
    SLOPE_LOOKBACK (5) weeks; "up" = > 0, "down" = < 0

Rules (d = (close - MA) / MA * 100):
  Stage 2: open & close > MA, MA rising,  d >  outer_pct
  Stage 4: open & close < MA, MA falling, d < -outer_pct
  Stage 1: close < MA and |d| <= inner_pct
  Stage 3: close >= MA and d <= inner_pct
  Otherwise (inner<|d|<=outer, or a Stage 2/4 distance without the matching
  slope/open): carry the previous week's stage forward. The first classifiable
  week has nothing to carry, so a gap-zone first week goes to Stage 3 if
  d >= 0 else Stage 1 (the nearer of the two zone boundaries).

Run from backend/:  uv run python -m scripts.weinstein_4stage_simulation
"""

import argparse
from datetime import date, datetime, timedelta

import pandas as pd
from sqlmodel import Session, select

from analysis.trend_structure.weinstein import SLOPE_LOOKBACK, resample_to_weekly
from clients.shared_bars_cache import _load_frames
from core.db import engine
from core.models import TrendAnalysis

TICKERS = ["META", "AAPL", "HWM", "BKNG", "GOOGL"]
STAGE_NAMES = {1: "S1 Basing", 2: "S2 Advancing", 3: "S3 Topping", 4: "S4 Declining"}
PROD_TO_NUM = {"base": 1, "advance": 2, "top": 3, "decline": 4}


def compute_ma(close: pd.Series, ma_length: int, ma_type: str) -> pd.Series:
    if ma_type.upper() == "EMA":
        return close.ewm(span=ma_length, adjust=False, min_periods=ma_length).mean()
    if ma_type.upper() == "SMA":
        return close.rolling(window=ma_length, min_periods=ma_length).mean()
    raise ValueError(f"ma_type must be SMA or EMA, got {ma_type!r}")


def classify_weekly(
    weekly: pd.DataFrame,
    ma_length: int = 30,
    ma_type: str = "SMA",
    inner_pct: float = 5.0,
    outer_pct: float = 10.0,
    slope_lookback_weeks: int = SLOPE_LOOKBACK,
) -> pd.DataFrame:
    """Returns weekly rows with ma, slope_pct, dist_pct, stage (1-4, NaN before
    the MA/slope exist) and carried (True where the stage was carried forward)."""
    ma = compute_ma(weekly["close"], ma_length, ma_type)
    ma_prev = ma.shift(slope_lookback_weeks)
    slope = (ma - ma_prev) / ma_prev * 100.0
    dist = (weekly["close"] - ma) / ma * 100.0
    valid = ma.notna() & ma_prev.notna()

    up, down = slope > 0, slope < 0
    above = (weekly["open"] > ma) & (weekly["close"] > ma)
    below = (weekly["open"] < ma) & (weekly["close"] < ma)
    is2 = valid & above & up & (dist > outer_pct)
    is4 = valid & below & down & (dist < -outer_pct)
    is1 = valid & (dist < 0) & (dist.abs() <= inner_pct)
    is3 = valid & (dist >= 0) & (dist <= inner_pct)

    stages: list[float] = []
    carried: list[bool] = []
    prev: int | None = None
    for i in range(len(weekly)):
        if not bool(valid.iloc[i]):
            stages.append(float("nan"))
            carried.append(False)
            continue
        if is2.iloc[i]:
            new, c = 2, False
        elif is4.iloc[i]:
            new, c = 4, False
        elif is1.iloc[i]:
            new, c = 1, False
        elif is3.iloc[i]:
            new, c = 3, False
        elif prev is not None:
            new, c = prev, True  # gap zone -> sticky
        else:
            new, c = (3 if dist.iloc[i] >= 0 else 1), False  # bootstrap, not a carry
        prev = new
        stages.append(new)
        carried.append(c)

    return pd.DataFrame(
        {"ma": ma, "slope_pct": slope, "dist_pct": dist, "stage": stages, "carried": carried}, index=weekly.index
    )


def load_weekly(session: Session, tickers: list[str], years: int) -> dict[str, pd.DataFrame]:
    """Read-only: every daily bar the cache holds (the MA needs warm-up history
    before the window), resampled to weekly with production's helper."""
    frames = _load_frames(session, tickers, "1d", date(1990, 1, 1))
    return {t: resample_to_weekly(f) for t, f in frames.items()}


def production_stage(session: Session, ticker: str):
    row = session.get(TrendAnalysis, ticker)
    if row is None:
        return None
    return row.weinstein_stage, row.weinstein_stage_since_date, row.weinstein_weeks_available


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--tickers", nargs="+", default=TICKERS)
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--ma-length", type=int, default=30)
    p.add_argument("--ma-type", default="SMA", choices=["SMA", "EMA"])
    p.add_argument("--inner-pct", type=float, default=5.0)
    p.add_argument("--outer-pct", type=float, default=10.0)
    p.add_argument("--slope-lookback-weeks", type=int, default=SLOPE_LOOKBACK)
    a = p.parse_args()

    print(
        f"params: MA={a.ma_type}{a.ma_length} inner={a.inner_pct}% outer={a.outer_pct}% "
        f"slope={a.slope_lookback_weeks}wk % change (production default {SLOPE_LOOKBACK})"
    )
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=365 * a.years))
    with Session(engine) as session:
        weeklies = load_weekly(session, a.tickers, a.years)
        for t in a.tickers:
            print(f"\n=== {t} ===")
            weekly = weeklies.get(t)
            if weekly is None or weekly.empty:
                print("  DATA ISSUE: no cached daily bars")
                continue
            res = classify_weekly(
                weekly, a.ma_length, a.ma_type, a.inner_pct, a.outer_pct, a.slope_lookback_weeks
            )
            win = res[res.index >= cutoff]
            classified = win.dropna(subset=["stage"])
            gaps = int((weekly.index.to_series().diff().dt.days > 10).sum())
            print(
                f"  bars: {weekly.index[0].date()}..{weekly.index[-1].date()} "
                f"({len(weekly)} weeks total, {len(win)} in {a.years}y window), "
                f"weeks with a >10d gap: {gaps}"
            )
            if len(win) and len(classified) < len(win):
                print(
                    f"  DATA ISSUE: only {len(classified)} of {len(win)} window weeks classifiable "
                    f"(MA needs {a.ma_length}+{a.slope_lookback_weeks} weeks of history; cache starts "
                    f"{weekly.index[0].date()})"
                )
            if classified.empty:
                print("  no classifiable weeks")
                continue
            st = classified["stage"].astype(int)
            print("  transitions:")
            print(f"    {st.index[0].date()}  start -> {STAGE_NAMES[st.iloc[0]]}")
            chg = st != st.shift()
            for d in st.index[chg][1:]:
                i = st.index.get_loc(d)
                print(f"    {d.date()}  {STAGE_NAMES[st.iloc[i - 1]]} -> {STAGE_NAMES[st.iloc[i]]}")
            n_carried = int(classified["carried"].sum())
            print(
                f"  sticky/carried weeks: {n_carried} of {len(classified)} classified "
                f"({n_carried / len(classified):.1%})"
            )
            sim_now = int(st.iloc[-1])
            last = classified.iloc[-1]
            print(
                f"  current sim stage: {STAGE_NAMES[sim_now]} (dist {last['dist_pct']:+.1f}% vs MA, "
                f"slope {last['slope_pct']:+.2f}%{', carried' if last['carried'] else ''})"
            )
            prod = production_stage(session, t)
            if prod is None or prod[0] is None:
                print(f"  production: no weinstein_stage on record ({prod})")
            else:
                pnum = PROD_TO_NUM[prod[0]]
                flag = "agree" if pnum == sim_now else "*** DISAGREE ***"
                print(f"  production: {STAGE_NAMES[pnum]} since {prod[1]} -> {flag}")


if __name__ == "__main__":
    main()
