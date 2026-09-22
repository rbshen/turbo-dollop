"""Prototype for the Weinstein Stage "pending confirmation" + ETA feature (2026-09-22).

See docs/weinstein_pending_confirmation_investigation_2026-09-22.md for the full design
proposal and validation write-up this script produces the numbers for.

**Investigation/prototype only -- nothing here is wired into production.** It does not
modify `analysis/trend_structure/weinstein.py` (imported and used UNMODIFIED -- both
`compute_stage_series` and the module's own constants), does not touch `TrendAnalysis` or
any other table, and makes zero writes and zero live Yahoo Finance calls (reads
`SharedBarsCache` straight out of `fathom.db` via a read-only sqlite3 connection, exactly
like `backend/scripts/weinstein_daily_variant_investigation.py`).

Note on location: this repo's convention (see CLAUDE.md's `backend/scripts/` folder
description) is that ad-hoc investigation scripts live there and are deliberately left
untracked. This script is committed instead, under `docs/` alongside its proposal, per
explicit instruction for this round (the prototype itself is one of the deliverables, not
a throwaway repro) -- a deliberate, one-off departure from that convention, not a change
to it.

Usage: `cd backend && uv run python ../docs/weinstein_pending_confirmation_prototype.py`
-- read-only against fathom.db, safe to rerun any time to refresh these numbers against
the latest cached data.
"""

from __future__ import annotations

import sqlite3
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from analysis.trend_structure.weinstein import (  # noqa: E402
    MIN_WEEKS_REQUIRED,
    WITHIN_RANGE_PCT,
    compute_stage_series,
    resample_to_weekly,
)

DB_PATH = Path(__file__).resolve().parent.parent / "backend" / "fathom.db"
BAND = WITHIN_RANGE_PCT / 100.0

Direction = Literal["advance", "decline"]

# Historical dates named in the investigation request -- META's own past "price already
# cleared the band, slope hasn't confirmed" bounces, checked below for whether the pending
# flag fires on them and whether the accompanying ETA would have been trustworthy.
META_CHECK_DATES = ["2026-04-13", "2026-07-06", "2026-09-07", "2026-09-14"]

# Matches MIN_WEEKS_REQUIRED's own "104 weeks (2y)" convention documented in weinstein.py --
# a flat-price projection that hasn't confirmed within 2 years is reported as
# horizon_exceeded rather than searched further.
PROJECTION_HORIZON_WEEKS = 104


# --- Data loading (read-only) ------------------------------------------------------------


def connect_ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def list_tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT ticker FROM sharedbarscache WHERE interval='1d' AND ticker != '^GSPC'").fetchall()
    return sorted(r[0] for r in rows)


def load_weekly_close(conn: sqlite3.Connection, ticker: str) -> pd.Series:
    rows = conn.execute(
        "SELECT bar_time, open, high, low, close, volume FROM sharedbarscache "
        "WHERE interval='1d' AND ticker=? ORDER BY bar_time",
        (ticker,),
    ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["bar_time", "open", "high", "low", "close", "volume"])
    df["bar_time"] = pd.to_datetime(df["bar_time"])
    df = df.set_index("bar_time")
    return resample_to_weekly(df)["close"]


# --- Part A: pending-confirmation flag -----------------------------------------------------
#
# Confirmed against weinstein.py's actual 8 `sState` transition rules (compute_stage_series,
# lines ~114-131): the transitions gated on BOTH a slope condition AND a band condition in
# the same week are exactly Top->Advance, Decline->Advance, Base->Advance (all: rising AND
# above-band) and Advance->Decline, Top->Decline, Base->Decline (all: falling AND below-
# band). Advance->Top (slope-not-rising alone) and Decline->Base (slope-not-falling alone)
# need no band condition, so they have no "one condition met, one pending" state -- this is
# NOT only the Decline->Advance direction the task's own framing led with; Top and Base have
# a symmetric pending state on both sides too.
#
# So: "pending Advance" is meaningful from any current stage OTHER than Advance itself, and
# fires when price already clears the +5% band but slope hasn't turned up; "pending Decline"
# mirrors it, meaningful from any stage other than Decline, when price is already below the
# -5% band but slope hasn't turned down.


def stage_flags(weekly_close: pd.Series) -> pd.DataFrame:
    """Bundles compute_stage_series' output with the band/slope-direction booleans the
    pending logic needs -- all of it read-only derived from weinstein.py's own unmodified
    ma/slope columns, no new numerics.
    """
    stage_df = compute_stage_series(weekly_close)
    out = weekly_close.to_frame("close").join(stage_df)
    out["above_band"] = out["valid"] & (out["close"] > out["ma"] * (1.0 + BAND))
    out["below_band"] = out["valid"] & (out["close"] < out["ma"] * (1.0 - BAND))
    out["rising"] = out["valid"] & (out["slope"] > 0.0)
    out["falling"] = out["valid"] & (out["slope"] < 0.0)
    out["pending_advance"] = out["valid"] & (out["stage"] != "advance") & out["above_band"] & (~out["rising"])
    out["pending_decline"] = out["valid"] & (out["stage"] != "decline") & out["below_band"] & (~out["falling"])
    return out


def current_pending_direction(flags: pd.DataFrame) -> Direction | None:
    latest = flags.iloc[-1]
    if bool(latest["pending_advance"]):
        return "advance"
    if bool(latest["pending_decline"]):
        return "decline"
    return None


def pending_since(flags: pd.DataFrame, direction: Direction) -> tuple[pd.Timestamp | None, bool]:
    """Same walk-backward shape as weinstein.py's own `_stage_since` (not reused directly --
    that one keys off the `stage` label, this keys off a boolean pending column -- but
    deliberately mirrors its "lower bound if constant across all available history" case).
    """
    col = "pending_advance" if direction == "advance" else "pending_decline"
    series = flags[col]
    if not bool(series.iloc[-1]):
        return None, False
    i = len(series) - 1
    while i > 0 and bool(series.iloc[i - 1]):
        i -= 1
    is_lower_bound = i == 0
    return series.index[i], is_lower_bound


# --- Part B: ETA projection ----------------------------------------------------------------


def scenario_growth_rate(weekly_close: pd.Series, scenario: str) -> float:
    """flat -> 0% weekly growth. trend_N -> the trailing N-week average weekly % return,
    compounded forward. N=5 mirrors SLOPE_LOOKBACK itself (the most reactive, most volatile
    read); N=13 is one quarter (a steadier read)."""
    if scenario == "flat":
        return 0.0
    n = int(scenario.split("_")[1])
    trailing = weekly_close.iloc[-(n + 1) :]
    if len(trailing) < 2:
        return 0.0
    return float(trailing.pct_change().dropna().mean())


@dataclass(frozen=True)
class EtaResult:
    weeks_away: int | None
    projected_date: pd.Timestamp | None
    band_lapsed_before_confirmation: bool
    projected_slope_pct: float | None
    growth_rate_pct: float
    horizon_exceeded: bool


def project_confirmation_eta(
    weekly_close: pd.Series,
    direction: Direction,
    scenario: str,
    horizon_weeks: int = PROJECTION_HORIZON_WEEKS,
) -> EtaResult:
    """Walks forward week by week under the stated price-growth assumption (flat, or a
    compounded recent-average weekly return), recomputing weinstein.py's own unmodified
    `compute_stage_series` on the extended series each time a horizon is tried, and reports
    the first future week where BOTH the slope condition AND the band condition needed for
    a real transition are true SIMULTANEOUSLY -- not slope alone.

    That "simultaneously" requirement is the one correctness bug this prototype caught and
    fixed mid-investigation: an earlier version flagged "confirmed" the moment slope alone
    crossed, which for a ticker whose band-clearance is fading as an old price spike rolls
    out of the 30-week window (LYB, see the validation doc) reported a confirmation date at
    which the real `compute_stage_series` would actually transition to Top/Base instead,
    because the band condition had already lapsed by then. `band_lapsed_before_confirmation`
    surfaces exactly this: True whenever the band condition drops false at some point before
    (or, in the horizon-exceeded case, instead of) the two conditions ever coinciding again.
    """
    assert direction in ("advance", "decline")
    last_close = float(weekly_close.iloc[-1])
    last_date = weekly_close.index[-1]
    growth = scenario_growth_rate(weekly_close, scenario)

    future_index = pd.DatetimeIndex([last_date + pd.Timedelta(weeks=i) for i in range(1, horizon_weeks + 1)])
    future_closes = last_close * (1.0 + growth) ** np.arange(1, horizon_weeks + 1)
    extended = pd.concat([weekly_close, pd.Series(future_closes, index=future_index)])

    stage_df = compute_stage_series(extended)
    cutoff_pos = len(weekly_close) - 1

    band_lapsed_first: int | None = None
    for i in range(cutoff_pos + 1, len(extended)):
        slope = stage_df["slope"].iloc[i]
        ma = stage_df["ma"].iloc[i]
        close = extended.iloc[i]
        if pd.isna(slope) or pd.isna(ma):
            continue
        if direction == "advance":
            slope_ok = slope > 0.0
            band_ok = close > ma * (1.0 + BAND)
        else:
            slope_ok = slope < 0.0
            band_ok = close < ma * (1.0 - BAND)

        if not band_ok and band_lapsed_first is None:
            band_lapsed_first = i - cutoff_pos

        if slope_ok and band_ok:
            return EtaResult(
                weeks_away=i - cutoff_pos,
                projected_date=extended.index[i],
                band_lapsed_before_confirmation=band_lapsed_first is not None and band_lapsed_first < (i - cutoff_pos),
                projected_slope_pct=float(slope),
                growth_rate_pct=growth * 100.0,
                horizon_exceeded=False,
            )
    return EtaResult(
        weeks_away=None,
        projected_date=None,
        band_lapsed_before_confirmation=band_lapsed_first is not None,
        projected_slope_pct=None,
        growth_rate_pct=growth * 100.0,
        horizon_exceeded=True,
    )


SCENARIOS = ["flat", "trend_5", "trend_13"]


def eta_report(weekly_close: pd.Series, direction: Direction) -> dict[str, EtaResult]:
    return {s: project_confirmation_eta(weekly_close, direction, s) for s in SCENARIOS}


# --- Supplementary diagnostic: band cushion vs. typical weekly move ------------------------
#
# Not a scenario, a snapshot: how far past the band threshold price closed today, versus how
# big a typical weekly move has been recently. A thin cushion means a single ordinary-sized
# down (or up) week could un-clear the band before slope ever gets a chance to confirm --
# exactly the mechanism behind META's own 4/13 and 7/6 false alarms (see the validation doc).
# This does NOT predict whether that will happen -- it's a risk/fragility read to display
# alongside the ETA, not a fourth scenario.


def band_cushion_pct(weekly_close: pd.Series, direction: Direction) -> tuple[float, float]:
    stage_df = compute_stage_series(weekly_close)
    close = float(weekly_close.iloc[-1])
    ma = float(stage_df["ma"].iloc[-1])
    threshold = ma * (1.0 + BAND) if direction == "advance" else ma * (1.0 - BAND)
    cushion_pct = (close / threshold - 1.0) * 100.0 if direction == "advance" else (1.0 - close / threshold) * 100.0
    recent_returns = weekly_close.pct_change().dropna().iloc[-13:]
    stdev_pct = float(recent_returns.std()) * 100.0
    return cushion_pct, stdev_pct


# --- Validation / report ---------------------------------------------------------------


def fmt_eta(r: EtaResult) -> str:
    if r.horizon_exceeded:
        lapsed = " (band condition lapses under this assumption before slope ever catches up)" if r.band_lapsed_before_confirmation else ""
        return f"does not confirm within {PROJECTION_HORIZON_WEEKS} weeks{lapsed}"
    lapsed_note = " [band lapsed earlier in the path, then re-cleared]" if r.band_lapsed_before_confirmation else ""
    return f"{r.weeks_away}wk away -> {r.projected_date.date()} (growth/wk used: {r.growth_rate_pct:+.2f}%){lapsed_note}"


def report_meta(conn: sqlite3.Connection) -> None:
    print("=" * 88)
    print("META -- current live pending case")
    print("=" * 88)
    weekly = load_weekly_close(conn, "META")
    flags = stage_flags(weekly)
    direction = current_pending_direction(flags)
    latest = flags.iloc[-1]
    print(f"as of {weekly.index[-1].date()}: stage={latest['stage']!r}, vs_ma={((latest['close']/latest['ma']-1)*100):+.2f}%, "
          f"slope={latest['slope']:+.2f}%/wk, pending_direction={direction}")
    if direction:
        since, lower_bound = pending_since(flags, direction)
        print(f"pending since: {since.date()}{' (lower bound)' if lower_bound else ''}")
        cushion, stdev = band_cushion_pct(weekly, direction)
        print(f"band cushion: {cushion:+.2f}pp past threshold vs. recent typical weekly move ~{stdev:.2f}pp "
              f"({'THIN -- one ordinary bad week could erase it' if cushion < stdev else 'comfortable'})")
        for scenario, r in eta_report(weekly, direction).items():
            print(f"  [{scenario:9s}] {fmt_eta(r)}")

    print()
    print("-" * 88)
    print("META -- historical 'as of' re-runs at the 4 named check dates")
    print("(what the flag/ETA would have said THEN, using only data available at that time,")
    print(" vs. what actually happened next)")
    print("-" * 88)
    for asof in META_CHECK_DATES:
        truncated = weekly[weekly.index <= asof]
        tflags = stage_flags(truncated)
        tdirection = current_pending_direction(tflags)
        print(f"\n  as of {asof}: pending={tdirection!r}")
        if tdirection:
            cushion, stdev = band_cushion_pct(truncated, tdirection)
            print(f"    band cushion {cushion:+.2f}pp vs typical weekly move {stdev:.2f}pp")
            for scenario, r in eta_report(truncated, tdirection).items():
                print(f"    [{scenario:9s}] {fmt_eta(r)}")
        after = weekly[weekly.index > asof].iloc[:4]
        after_flags = stage_flags(weekly[weekly.index <= (after.index[-1] if len(after) else asof)])
        print(f"    actual next closes: {list(after.round(2))}")
        if len(after):
            still_pending_next_week = bool(after_flags.loc[after.index[0], "pending_advance" if tdirection == "advance" else "pending_decline"]) if tdirection else None
            print(f"    still pending the very next week? {still_pending_next_week}")


def report_lyb(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 88)
    print("LYB -- the 'rolling off a historical spike' caveat case")
    print("=" * 88)
    weekly = load_weekly_close(conn, "LYB")
    flags = stage_flags(weekly)
    direction = current_pending_direction(flags)
    latest = flags.iloc[-1]
    print(f"as of {weekly.index[-1].date()}: stage={latest['stage']!r}, vs_ma={((latest['close']/latest['ma']-1)*100):+.2f}%, "
          f"slope={latest['slope']:+.2f}%/wk, pending_direction={direction}")
    if direction:
        for scenario, r in eta_report(weekly, direction).items():
            print(f"  [{scenario:9s}] {fmt_eta(r)}")
        print("  -> LYB ran up to ~$80 in March 2026; that spike is still inside the trailing 30-week")
        print("     window propping the MA up. Under a pure FLAT-price assumption the MA falls toward")
        print("     today's price as the spike rolls out, closing the band gap just as fast as (or")
        print("     faster than) slope would confirm -- so flat-price says 'never within 2 years',")
        print("     while a mild continued-decline scenario (trend_5) says a few weeks. This is the")
        print("     concrete instance of the flat-price-assumption caveat the investigation asked about.")


def full_universe_scan(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 88)
    print("Full-universe scan -- all cached tickers, today's snapshot")
    print("=" * 88)
    tickers = list_tickers(conn)
    combos: dict[tuple[str, str], int] = {}
    flat_weeks: list[int] = []
    horizon_exceeded: list[str] = []
    scenario_disagreements = 0
    n_pending = 0
    for t in tickers:
        weekly = load_weekly_close(conn, t)
        if len(weekly) < MIN_WEEKS_REQUIRED:
            continue
        flags = stage_flags(weekly)
        latest_stage = flags.iloc[-1]["stage"]
        if latest_stage is None:
            continue
        direction = current_pending_direction(flags)
        if direction is None:
            continue
        n_pending += 1
        combos[(latest_stage, direction)] = combos.get((latest_stage, direction), 0) + 1
        results = eta_report(weekly, direction)
        if results["flat"].horizon_exceeded:
            horizon_exceeded.append(t)
        else:
            flat_weeks.append(results["flat"].weeks_away)
        weeks_vals = [r.weeks_away for r in results.values() if r.weeks_away is not None]
        if len(weeks_vals) >= 2 and max(weeks_vals) - min(weeks_vals) >= 3:
            scenario_disagreements += 1

    print(f"{len(tickers)} tickers with cached bars; {n_pending} currently pending")
    print("by (current stage, pending direction):", combos)
    if flat_weeks:
        print(f"flat-scenario weeks_away: median={statistics.median(flat_weeks)}, "
              f"p25={statistics.quantiles(flat_weeks, n=4)[0]}, p75={statistics.quantiles(flat_weeks, n=4)[2]}, "
              f"max={max(flat_weeks)}")
    print(f"flat scenario never confirms within {PROJECTION_HORIZON_WEEKS}wk horizon: {horizon_exceeded}")
    print(f"tickers where scenarios disagree by >=3 weeks: {scenario_disagreements} / {n_pending}")


def main() -> None:
    conn = connect_ro()
    try:
        report_meta(conn)
        report_lyb(conn)
        full_universe_scan(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
