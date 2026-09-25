"""Standalone research script: a faithful port of a Pine Script `sState` Weinstein
stage engine (sticky branch only, tsMode=false) on weekly bars, compared -- as
data only -- against production's `weinstein_stage`.

NOT wired into any cron job, API route, or the app. Read-only against the real
DB (SharedBarsCache for bars, TrendAnalysis for the production stage) -- it
never writes. Full rewrite; replaces the earlier three-MA/swing-based version.

Stage engine (weekly):
  m = MA(close, ma_length); m_prev = m shifted slope_lookback weeks;
  valid = m and m_prev both present; slope_pct = (m - m_prev)/m_prev*100;
  rising/falling = slope_pct >/< 0; above/below_band = close beyond
  m*(1 +/- within_range_pct/100). Next state is a function of the previous
  state (1 Base, 2 Advance, 3 Top, 4 Decline); nothing is assigned until valid.
Volume/RS never gate the state machine. They only produce `confirmed_breakout`:
  a transition INTO Advance with volume_ratio >= volume_mult AND
  (mansfield_rs is NaN OR > 0). Mansfield RS is measured against SPY.

Run from backend/:  uv run python -m scripts.weinstein_4stage_simulation
"""

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session

from analysis.trend_structure.weinstein import resample_to_weekly
from clients.shared_bars_cache import _load_frames
from core.db import engine
from core.models import TrendAnalysis

TICKERS = ["META", "AAPL", "HWM", "BKNG", "GOOGL"]
STAGE_NAMES = {1: "S1 Base", 2: "S2 Advance", 3: "S3 Top", 4: "S4 Decline"}
PROD_TO_NUM = {"base": 1, "advance": 2, "top": 3, "decline": 4}


@dataclass
class SimParams:
    ma_length: int = 30
    ma_type: str = "EMA"
    within_range_pct: float = 5.0
    slope_lookback: int = 5
    use_volume_confirmation: bool = True
    volume_mult: float = 2.0
    volume_avg_length: int = 50
    use_rs_confirmation: bool = True
    rs_benchmark: str = "SPY"
    rs_smoothing_length: int = 52


def compute_ma(close: pd.Series, length: int, ma_type: str) -> pd.Series:
    if ma_type.upper() == "EMA":
        return close.ewm(span=length, adjust=False, min_periods=length).mean()
    if ma_type.upper() == "SMA":
        return close.rolling(window=length, min_periods=length).mean()
    raise ValueError(f"ma_type must be SMA or EMA, got {ma_type!r}")


def next_state(prev: int | None, rising: bool, falling: bool, above: bool, below: bool) -> int:
    if prev is None:  # first valid week
        if rising and above:
            return 2
        if falling and below:
            return 4
        return 3 if (rising or above) else 1
    if prev == 2:
        if falling and below:
            return 4
        return 3 if not rising else 2
    if prev == 3:
        if rising and above:
            return 2
        if falling and below:
            return 4
        return 3
    if prev == 4:
        if rising and above:
            return 2
        return 1 if not falling else 4
    # prev == 1
    if falling and below:
        return 4
    if rising and above:
        return 2
    return 1


def run_engine(weekly: pd.DataFrame, bench_close: pd.Series | None, p: SimParams) -> tuple[pd.DataFrame, list[dict]]:
    close, vol = weekly["close"], weekly["volume"]
    m = compute_ma(close, p.ma_length, p.ma_type)
    m_prev = m.shift(p.slope_lookback)
    valid = (m.notna() & m_prev.notna()).to_numpy()
    slope = (m - m_prev) / m_prev * 100.0
    band = p.within_range_pct / 100.0
    rising = (slope > 0).to_numpy() & valid
    falling = (slope < 0).to_numpy() & valid
    above = (close > m * (1 + band)).to_numpy() & valid
    below = (close < m * (1 - band)).to_numpy() & valid

    vol_avg = vol.rolling(p.volume_avg_length, min_periods=p.volume_avg_length).mean()
    vol_ratio = vol / vol_avg
    vol_ok = (vol_ratio >= p.volume_mult).to_numpy() if p.use_volume_confirmation else np.ones(len(close), bool)

    if bench_close is not None:
        rs_ratio = close / bench_close.reindex(close.index)
        rs_sma = rs_ratio.rolling(p.rs_smoothing_length, min_periods=p.rs_smoothing_length).mean()
        mansfield = (rs_ratio / rs_sma - 1.0) * 100.0
    else:
        mansfield = pd.Series(np.nan, index=close.index)
    rs_ok = (mansfield.isna() | (mansfield > 0)).to_numpy() if p.use_rs_confirmation else np.ones(len(close), bool)

    n = len(close)
    stages = np.full(n, np.nan)
    breakout = np.zeros(n, bool)
    transitions: list[dict] = []
    state: int | None = None
    for i in range(n):
        if not valid[i]:
            continue
        new = next_state(state, bool(rising[i]), bool(falling[i]), bool(above[i]), bool(below[i]))
        if state is not None and new != state:
            conf = new == 2 and bool(vol_ok[i]) and bool(rs_ok[i])
            breakout[i] = conf
            transitions.append({"date": weekly.index[i], "from": state, "to": new, "confirmed": conf})
        state = new
        stages[i] = state

    df = pd.DataFrame(
        {"close": close, "ma": m, "slope_pct": slope, "stage": stages, "volume_ratio": vol_ratio,
         "mansfield_rs": mansfield, "confirmed_breakout": breakout},
        index=weekly.index,
    )
    return df, transitions


def load_weekly(session: Session, tickers: list[str], years: int) -> dict[str, pd.DataFrame]:
    frames = _load_frames(session, tickers, "1d", date(1990, 1, 1))
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=365 * years))
    out = {}
    for t, f in frames.items():
        w = resample_to_weekly(f)
        out[t] = w[w.index >= cutoff]
    return out


def production_stage(session: Session, ticker: str):
    row = session.get(TrendAnalysis, ticker)
    if row is None:
        return None
    return row.weinstein_stage, row.weinstein_stage_since_date


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tickers", nargs="+", default=TICKERS)
    ap.add_argument("--years", type=int, default=5)
    d = SimParams()
    for f, v in d.__dict__.items():
        if isinstance(v, bool):
            ap.add_argument("--" + f.replace("_", "-"), type=lambda s: s.lower() in ("1", "true", "yes"), default=v)
        else:
            ap.add_argument("--" + f.replace("_", "-"), type=type(v), default=v)
    a = ap.parse_args()
    p = SimParams(**{f: getattr(a, f) for f in d.__dict__})

    print(f"params: {p}")
    with Session(engine) as session:
        weeklies = load_weekly(session, a.tickers + [p.rs_benchmark], a.years)
        bench = weeklies.get(p.rs_benchmark)
        if bench is None or bench.empty:
            print(f"DATA ISSUE: no {p.rs_benchmark} bars; Mansfield RS will be NaN (counts as OK)")
            bench_close = None
        else:
            bench_close = bench["close"]
            print(f"benchmark {p.rs_benchmark}: {bench.index[0].date()}..{bench.index[-1].date()} ({len(bench)} weeks)")
        for t in a.tickers:
            print(f"\n=== {t} ===")
            weekly = weeklies.get(t)
            if weekly is None or weekly.empty:
                print("  DATA ISSUE: no cached daily bars")
                continue
            gaps = int((weekly.index.to_series().diff().dt.days > 10).sum())
            missing_bench = int(bench_close.reindex(weekly.index).isna().sum()) if bench_close is not None else len(weekly)
            print(
                f"  bars: {weekly.index[0].date()}..{weekly.index[-1].date()} ({len(weekly)} weeks), gaps>10d: {gaps}, "
                f"weeks without {p.rs_benchmark} bar: {missing_bench}, volume NaN/zero weeks: "
                f"{int(weekly['volume'].isna().sum())}/{int((weekly['volume'] == 0).sum())}"
            )
            df, trans = run_engine(weekly, bench_close, p)
            cl = df.dropna(subset=["stage"])
            if cl.empty:
                print("  DATA ISSUE: insufficient history")
                continue
            print(f"  first classifiable week: {cl.index[0].date()} ({len(cl)} classified of {len(weekly)})")
            print(f"  first volume-ratio week: {df['volume_ratio'].first_valid_index().date() if df['volume_ratio'].notna().any() else 'never'}; "
                  f"first Mansfield RS week: {df['mansfield_rs'].first_valid_index().date() if df['mansfield_rs'].notna().any() else 'never'}")
            print(f"  first classified stage: {STAGE_NAMES[int(cl['stage'].iloc[0])]}")
            for tr in trans:
                print(f"    {tr['date'].date()}  {STAGE_NAMES[tr['from']]} -> {STAGE_NAMES[tr['to']]}{'  [confirmed breakout]' if tr['confirmed'] else ''}")
            print(f"  transitions (excl. startup): {len(trans)}")
            bo = df[df["confirmed_breakout"]]
            if bo.empty:
                print("  confirmed breakouts: none")
            for dt, r in bo.iterrows():
                rs = "NaN" if pd.isna(r["mansfield_rs"]) else f"{r['mansfield_rs']:.2f}"
                print(f"  confirmed breakout {dt.date()}: volume_ratio={r['volume_ratio']:.2f}, mansfield_rs={rs}")
            sim_now = int(cl["stage"].iloc[-1])
            last = cl.iloc[-1]
            print(f"  current sim stage: {STAGE_NAMES[sim_now]} (close {last['close']:.2f}, MA {last['ma']:.2f}, slope {last['slope_pct']:.2f}%)")
            prod = production_stage(session, t)
            if prod is None or prod[0] is None:
                print(f"  production: no weinstein_stage on record ({prod})")
            else:
                pnum = PROD_TO_NUM[prod[0]]
                print(f"  production: {STAGE_NAMES[pnum]} since {prod[1]} (informational)")


if __name__ == "__main__":
    main()
