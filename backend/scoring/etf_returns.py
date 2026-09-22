"""Pure trailing-return math for the Sector Heatmap -- no DB/HTTP, same
package convention as scoring/momentum.py. See data/sector_heatmap_data.py
for orchestration (fetch, anchor resolution, persistence).

Every window is a CALENDAR offset back from the anchor date, taking the
last close on/before the target date -- the convention scoring/momentum.py
already uses, and what a column header like "1M" actually says. Trading-day
counts ("21 bars") drift with the holiday calendar and were measured to
differ from calendar offsets by up to 9.5pp on volatile funds (see
docs/etf_heatmap_momentum_investigation_2026-09-20.md, section 3).

"1D" (added 2026-09-22) is the same rule at its one-day limit: target =
anchor - 1 calendar day, then "last close on/before" -- which degrades
correctly into "the prior TRADING day's close" for free, since a Monday
anchor's target (Sunday) has no bar and the lookup falls back to Friday's,
exactly like every other window already falls back across a weekend/holiday.
No separate trading-day-aware mechanism was needed.

The input series is expected to be a TOTAL-return-adjusted close (Yahoo's
`Adj Close`), so the ratio of two closes already includes reinvested
distributions -- nothing here knows or cares about dividends."""

from dataclasses import dataclass
from datetime import date

import pandas as pd

WINDOWS = ("1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y")

# A fund whose latest bar is older than this (calendar days) relative to the
# anchor has a stale/partial download -- every window reads None rather than
# silently reporting a return that ends days before its neighbours'.
# Covers a long weekend plus a day of slack.
MAX_STALE_DAYS = 5


@dataclass(frozen=True)
class WindowReturn:
    window: str
    base_date: date | None
    return_pct: float | None


def _target_date(window: str, anchor: pd.Timestamp) -> pd.Timestamp:
    if window == "1d":
        return anchor - pd.DateOffset(days=1)
    if window == "1w":
        return anchor - pd.DateOffset(weeks=1)
    if window == "1y":
        return anchor - pd.DateOffset(years=1)
    if window == "ytd":
        # Prior calendar year's final trading day: the last close on/before
        # Dec 31 -- the standard YTD base (measuring from the year's first
        # close would drop that session's own move).
        return pd.Timestamp(year=anchor.year - 1, month=12, day=31)
    return anchor - pd.DateOffset(months=int(window[:-1]))


def _last_bar_on_or_before(series: pd.Series, target: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    eligible = series.loc[series.index <= target]
    if eligible.empty:
        return None
    return eligible.index[-1], float(eligible.iloc[-1])


def compute_window_returns(adj_close: pd.Series, anchor: pd.Timestamp) -> list[WindowReturn]:
    """All 7 windows, in WINDOWS order, for one fund's total-return-adjusted
    close series (DatetimeIndex, any order/tz -- normalized here).

    A window is None/None (never imputed) when the fund has no bar on/before
    that window's target date (young fund), when the base close is not
    positive, or when the fund's own latest bar on/before `anchor` is more
    than MAX_STALE_DAYS old (in which case ALL windows are None -- a fund
    that stopped printing bars shouldn't show a return ending in the past
    beside its neighbours' current ones)."""
    series = adj_close.dropna().sort_index()
    if series.index.tz is not None:
        series = series.tz_localize(None)
    series.index = series.index.normalize()

    empty = [WindowReturn(w, None, None) for w in WINDOWS]

    latest = _last_bar_on_or_before(series, anchor)
    if latest is None or (anchor - latest[0]).days > MAX_STALE_DAYS or latest[1] <= 0:
        return empty
    _, as_of_price = latest

    results: list[WindowReturn] = []
    for window in WINDOWS:
        base = _last_bar_on_or_before(series, _target_date(window, anchor))
        if base is None or base[1] <= 0:
            results.append(WindowReturn(window, None, None))
            continue
        base_ts, base_price = base
        results.append(WindowReturn(window, base_ts.date(), (as_of_price / base_price - 1.0) * 100.0))
    return results
