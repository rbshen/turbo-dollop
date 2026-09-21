"""Pure market-breadth math -- no DB/HTTP, same package convention as
scoring/etf_returns.py. See data/market_breadth_data.py for orchestration
(universe, fetch, anchor resolution, coverage gate, persistence) and
docs/market_breadth_investigation_2026-09-21.md for the design.

Three metrics per session, each over the constituents that HAVE a bar that
session:
  - % of constituents whose close is above their own 50-day SMA,
  - the same for the 200-day SMA,
  - new 52-week highs minus new 52-week lows (a count, not a percentage).

**Windows are counted in each ticker's OWN bars, never on a shared date
index.** A date-union frame would let one missing bar inside a ticker's
trailing 252 rows silently disqualify it (the investigation's FISV
finding: 500 real bars, dropped from the 52-week count by a strict
min_periods on the union frame). Rolling per ticker sidesteps that, and a
ticker too young for a window is counted in that metric's *eligible*
denominator's absence -- never as "below".

**52-week = intraday High/Low over the trailing 252 sessions including
today, ties count, a full 252-bar window required** -- a new high is
`high >= max(last 252 highs)`, a new low `low <= min(last 252 lows)`.
SMA position is `close > SMA` (strict, SMA includes today), matching how
TrendAnalysis.sma{50,200}_position_pct is signed.

Bars are expected as lowercase-column frames (what clients/
shared_bars_cache.py hands back), with split-adjusted-but-not-dividend-
adjusted prices (auto_adjust=False), like every other technical consumer."""

import pandas as pd

SMA_SHORT = 50
SMA_LONG = 200
HL_WINDOW = 252

# One row per session, one column per running total across tickers.
COUNT_COLUMNS = (
    "with_bar",
    "sma50_eligible",
    "sma50_above",
    "sma200_eligible",
    "sma200_above",
    "hl_eligible",
    "new_highs",
    "new_lows",
)


def _own_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """The ticker's real bars: a row missing any of high/low/close is not a
    bar. Index normalized to tz-naive midnight so sessions from different
    tickers line up; a duplicated date keeps its last row."""
    bars = frame[["high", "low", "close"]].dropna()
    index = pd.DatetimeIndex(bars.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    bars = bars.set_axis(index.normalize())
    return bars[~bars.index.duplicated(keep="last")].sort_index()


def ticker_flags(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Per ticker, one 0/1 row per session it has a bar on, one column per
    COUNT_COLUMNS entry. A ticker with no usable bars is left out. Vectorized
    within a ticker; the per-ticker loop is ~500 short rolling passes."""
    flags: dict[str, pd.DataFrame] = {}
    for ticker, frame in bars.items():
        if frame is None or frame.empty:
            continue
        own = _own_bars(frame)
        if own.empty:
            continue
        close, high, low = own["close"], own["high"], own["low"]
        sma50 = close.rolling(SMA_SHORT).mean()
        sma200 = close.rolling(SMA_LONG).mean()
        high_252 = high.rolling(HL_WINDOW).max()
        low_252 = low.rolling(HL_WINDOW).min()
        has50, has200, has_hl = sma50.notna(), sma200.notna(), high_252.notna()
        flags[ticker] = pd.DataFrame(
            {
                "with_bar": 1,
                "sma50_eligible": has50,
                "sma50_above": has50 & (close > sma50),
                "sma200_eligible": has200,
                "sma200_above": has200 & (close > sma200),
                "hl_eligible": has_hl,
                "new_highs": has_hl & (high >= high_252),
                "new_lows": has_hl & (low <= low_252),
            },
            index=own.index,
        ).astype(int)
    return flags


def aggregate_flags(flags: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Sum every ticker's flags per session -- index: session date,
    ascending; columns: COUNT_COLUMNS. Empty (with those columns) for no
    tickers."""
    if not flags:
        return pd.DataFrame(columns=list(COUNT_COLUMNS), dtype=int)
    return pd.concat(flags.values()).groupby(level=0).sum().sort_index()[list(COUNT_COLUMNS)]


def snapshot_frame(counts: pd.DataFrame, constituents: int) -> pd.DataFrame:
    """The MarketBreadthSnapshot columns (minus universe/computed_at/
    is_backfilled) for every session in `counts`. A percentage is NaN when
    its eligible count is 0."""
    out = pd.DataFrame(index=counts.index)
    out["constituents"] = constituents
    out["stale_excluded"] = constituents - counts["with_bar"]
    for prefix in ("sma50", "sma200"):
        out[f"{prefix}_eligible"] = counts[f"{prefix}_eligible"]
        out[f"{prefix}_above"] = counts[f"{prefix}_above"]
        eligible = counts[f"{prefix}_eligible"].where(counts[f"{prefix}_eligible"] > 0)
        out[f"pct_above_{prefix}"] = counts[f"{prefix}_above"] / eligible * 100
    out["hl_eligible"] = counts["hl_eligible"]
    out["new_highs"] = counts["new_highs"]
    out["new_lows"] = counts["new_lows"]
    out["net_new_highs"] = counts["new_highs"] - counts["new_lows"]
    return out
