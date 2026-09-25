"""Standalone research script: a sticky Weinstein 4-stage STATE MACHINE on
weekly bars, compared against production's `weinstein_stage`.

NOT wired into any cron job, API route, or the app. Read-only against the real
DB (SharedBarsCache for bars, TrendAnalysis for the production stage) -- it
never writes. Refinement of the per-week snapshot classifier in ddaabda.

Shared with production: bars come from the same daily SharedBarsCache rows the
nightly trend job reads, resampled by production's resample_to_weekly. The
"5-week % change of the MA" slope matches production's definition (production
only applies it to the 30-week MA, and calls slope > 0 rising / < 0 falling
with no flat band; the +/-1% flat band here is new).

Rules (all thresholds are named parameters, see SimParams):
  Slope of each MA: 5-week % change; within +/-flat_band_pct = flat, above =
    rising, below = falling.
  Volume baseline: trailing vol_avg_weeks average, EXCLUDING the current week (only the 2->3 rule uses it).
  Swing high/low: fractal, strictly greater/lower than the `swing_n` weeks
    before AND after; confirmed swing_n weeks late (no lookahead).
  1->2 breakout: close > highest swing high formed since the Stage-1 run began,
    close above all three MAs, all three MAs flat or rising (no volume test).
  2->3: close < 10wk MA and volume >= breakdown_vol_mult x avg.
  3->4: close < lowest swing low formed since the Stage-3 run began.
  4->1: 30wk MA slope becomes flat.
  1->4 failed base: in Stage 1, close < lowest close of the preceding Stage-4 run.
  3->2 failed top: in Stage 3, close > highest high since the Stage-3 run began
    (prior weeks only); no volume test.
  Nothing else moves the stage. Startup: above all 3 MAs and none falling -> 2;
  below all 3 and none rising -> 4; else 3 if close > 30wk MA else 1.

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
STAGE_NAMES = {1: "S1 Basing", 2: "S2 Advancing", 3: "S3 Topping", 4: "S4 Declining"}
PROD_TO_NUM = {"base": 1, "advance": 2, "top": 3, "decline": 4}


@dataclass
class SimParams:
    ma_short_len: int = 10
    ma_mid_len: int = 30
    ma_long_len: int = 40
    ma_type: str = "SMA"
    slope_lookback_weeks: int = 5
    flat_band_pct: float = 5.0
    vol_avg_weeks: int = 10
    breakdown_vol_mult: float = 1.0
    swing_n: int = 3


def compute_ma(close: pd.Series, length: int, ma_type: str) -> pd.Series:
    if ma_type.upper() == "EMA":
        return close.ewm(span=length, adjust=False, min_periods=length).mean()
    if ma_type.upper() == "SMA":
        return close.rolling(window=length, min_periods=length).mean()
    raise ValueError(f"ma_type must be SMA or EMA, got {ma_type!r}")


def slope_class(ma: pd.Series, lookback: int, band: float) -> pd.Series:
    pct = (ma / ma.shift(lookback) - 1.0) * 100.0
    out = pd.Series(np.where(pct > band, "rising", np.where(pct < -band, "falling", "flat")), index=ma.index)
    return out.where(pct.notna())


def find_swings(high: pd.Series, low: pd.Series, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Fractal swing flags by ITS OWN week index. Index i is a swing only if it
    beats the n weeks before and n after; the caller must not act on it until
    week i+n (see confirmed_at usage in run_state_machine)."""
    h, l = high.to_numpy(), low.to_numpy()
    sh, sl = np.zeros(len(h), bool), np.zeros(len(h), bool)
    for i in range(n, len(h) - n):
        nb_h = np.r_[h[i - n : i], h[i + 1 : i + n + 1]]
        nb_l = np.r_[l[i - n : i], l[i + 1 : i + n + 1]]
        sh[i] = h[i] > nb_h.max()
        sl[i] = l[i] < nb_l.min()
    return sh, sl


def run_state_machine(weekly: pd.DataFrame, p: SimParams) -> tuple[pd.DataFrame, list[dict], dict]:
    close, high, low, vol = weekly["close"], weekly["high"], weekly["low"], weekly["volume"]
    ma10 = compute_ma(close, p.ma_short_len, p.ma_type)
    ma30 = compute_ma(close, p.ma_mid_len, p.ma_type)
    ma40 = compute_ma(close, p.ma_long_len, p.ma_type)
    sl10, sl30, sl40 = (slope_class(m, p.slope_lookback_weeks, p.flat_band_pct) for m in (ma10, ma30, ma40))
    vol_avg = vol.shift(1).rolling(p.vol_avg_weeks, min_periods=p.vol_avg_weeks).mean()
    swing_hi, swing_lo = find_swings(high, low, p.swing_n)

    valid = (sl10.notna() & sl30.notna() & sl40.notna()).to_numpy()
    c, h, lo = close.to_numpy(), high.to_numpy(), low.to_numpy()
    n = len(weekly)
    stages = np.full(n, np.nan)
    transitions: list[dict] = []
    stats = {"no_swing_yet_weeks": 0, "no_prior_s4_weeks": 0, "flipflops": 0}

    stage, run_start, prev_s4_trough = None, 0, None
    for i in range(n):
        if not valid[i]:
            continue
        above_all = c[i] > max(ma10.iloc[i], ma30.iloc[i], ma40.iloc[i])
        below_all = c[i] < min(ma10.iloc[i], ma30.iloc[i], ma40.iloc[i])
        s = (sl10.iloc[i], sl30.iloc[i], sl40.iloc[i])
        vavg = vol_avg.iloc[i]
        vol_ok = lambda mult: bool(pd.notna(vavg) and vavg > 0 and vol.iloc[i] >= mult * vavg)  # noqa: E731

        if stage is None:  # startup
            if above_all and "falling" not in s:
                stage, why = 2, "startup: above all MAs, none falling"
            elif below_all and "rising" not in s:
                stage, why = 4, "startup: below all MAs, none rising"
            else:
                stage, why = (3, "startup: nearest-zone, above 30wk") if c[i] > ma30.iloc[i] else (1, "startup: nearest-zone, below 30wk")
            run_start = i
            transitions.append({"date": weekly.index[i], "from": None, "to": stage, "trigger": why})
            stages[i] = stage
            continue

        new, why = stage, None
        # swings usable now: formed at or after run start, confirmed (idx + swing_n) <= i
        lim = i - p.swing_n
        if stage == 1:
            failed_base = prev_s4_trough is not None and c[i] < prev_s4_trough
            if prev_s4_trough is None:
                stats["no_prior_s4_weeks"] += 1
            if failed_base:
                new, why = 4, "1->4 failed-base edge case"
            else:
                idx = [j for j in range(run_start, lim + 1) if swing_hi[j]] if lim >= run_start else []
                if not idx:
                    stats["no_swing_yet_weeks"] += 1
                elif (
                    c[i] > max(h[j] for j in idx) and above_all
                    and all(x in ("flat", "rising") for x in s)
                ):
                    new, why = 2, "1->2 breakout"
        elif stage == 2:
            if c[i] < ma10.iloc[i] and vol_ok(p.breakdown_vol_mult):
                new, why = 3, "2->3 close < 10wk MA on volume"
        elif stage == 3:
            if i > run_start and c[i] > h[run_start:i].max():
                new, why = 2, "3->2 failed-top edge case"
            else:
                idx = [j for j in range(run_start, lim + 1) if swing_lo[j]] if lim >= run_start else []
                if not idx:
                    stats["no_swing_yet_weeks"] += 1
                elif c[i] < min(lo[j] for j in idx):
                    new, why = 4, "3->4 break below swing low"
        elif stage == 4 and sl30.iloc[i] == "flat":
            new, why = 1, "4->1 30wk MA slope flat"

        if new != stage:
            if stage == 4:  # leaving Stage 4: remember its lowest close
                prev_s4_trough = float(c[run_start : i + 1].min())
            if why == "1->4 failed-base edge case" and transitions and transitions[-1]["trigger"].startswith("4->1") and transitions[-1]["date"] == weekly.index[i - 1]:
                stats["flipflops"] += 1
            transitions.append({"date": weekly.index[i], "from": stage, "to": new, "trigger": why})
            stage, run_start = new, i
        stages[i] = stage

    df = pd.DataFrame({"close": close, "ma10": ma10, "ma30": ma30, "ma40": ma40, "sl30": sl30, "stage": stages}, index=weekly.index)
    return df, transitions, stats


def load_weekly(session: Session, tickers: list[str]) -> dict[str, pd.DataFrame]:
    frames = _load_frames(session, tickers, "1d", date(1990, 1, 1))
    return {t: resample_to_weekly(f) for t, f in frames.items()}


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
        ap.add_argument("--" + f.replace("_", "-"), type=type(v), default=v)
    a = ap.parse_args()
    p = SimParams(**{f: getattr(a, f) for f in d.__dict__})

    print(f"params: {p}")
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=365 * a.years))
    with Session(engine) as session:
        weeklies = load_weekly(session, a.tickers)
        for t in a.tickers:
            print(f"\n=== {t} ===")
            weekly = weeklies.get(t)
            if weekly is None or weekly.empty:
                print("  DATA ISSUE: no cached daily bars")
                continue
            gaps = int((weekly.index.to_series().diff().dt.days > 10).sum())
            v = weekly["volume"]
            print(
                f"  bars: {weekly.index[0].date()}..{weekly.index[-1].date()} ({len(weekly)} weeks), "
                f"gaps>10d: {gaps}, volume NaN/zero weeks: {int(v.isna().sum())}/{int((v == 0).sum())}"
            )
            df, trans, stats = run_state_machine(weekly, p)
            classified = df.dropna(subset=["stage"])
            print(f"  classified weeks: {len(classified)} of {len(weekly)} (first: {classified.index[0].date() if len(classified) else 'none'})")
            if classified.empty:
                print("  DATA ISSUE: insufficient history")
                continue
            for tr in trans:
                old = STAGE_NAMES[tr["from"]] if tr["from"] else "start"
                print(f"    {tr['date'].date()}  {old} -> {STAGE_NAMES[tr['to']]}   [{tr['trigger']}]")
            print(
                f"  transitions (excl. startup): {len(trans) - 1}; weeks a swing-based trigger couldn't be evaluated "
                f"(no confirmed swing yet): {stats['no_swing_yet_weeks']}; weeks in S1 with no prior S4 trough: "
                f"{stats['no_prior_s4_weeks']}; 4->1->4 immediate flip-flops: {stats['flipflops']}"
            )
            sim_now = int(classified["stage"].iloc[-1])
            last = classified.iloc[-1]
            print(f"  current sim stage: {STAGE_NAMES[sim_now]} (close {last['close']:.2f}, 30wk MA {last['ma30']:.2f}, 30wk slope {last['sl30']})")
            prod = production_stage(session, t)
            if prod is None or prod[0] is None:
                print(f"  production: no weinstein_stage on record ({prod})")
            else:
                pnum = PROD_TO_NUM[prod[0]]
                print(f"  production: {STAGE_NAMES[pnum]} since {prod[1]} -> {'agree' if pnum == sim_now else '*** DISAGREE ***'}")


if __name__ == "__main__":
    main()
