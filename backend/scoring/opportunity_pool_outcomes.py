"""Thin, pure wrapper that turns the opportunity outcome engine's output into the SLIM rows of OpportunityPoolOutcome. No DB, no I/O, no
clock. The return logic is NOT reimplemented: it calls scoring/opportunity_outcomes.py::compute_outcomes unchanged (entry = the next
session's open, horizon N = the Nth bar after it, price-only, SPY and sector benchmarks, censoring) and keeps only the fields the pool
baseline needs. The stop, best/worst-move and drawdown the engine also computes, and the exit close, are dropped here.

Spec: docs/specs/opportunities.md, "Pool outcomes"."""

from datetime import date

import pandas as pd

from scoring import opportunity_outcomes as eng

# The OpportunityPoolOutcome fields the engine decides (identity, tier, assigned list, leveraged flag and bookkeeping come from the pool row and the updater).
POOL_VALUE_FIELDS: tuple[str, ...] = (
    "status", "censor_reason", "entry_date", "entry_open", "entry_gap_pct", "entry_gap_flag", "exit_date", "forward_return", "spy_return",
    "excess_vs_spy", "sector_etf", "sector_return", "excess_vs_sector",
)


def slim_values(outcome: eng.HorizonOutcome) -> dict:
    """The slim field subset of one engine HorizonOutcome."""
    d = outcome.as_dict()
    return {k: d[k] for k in POOL_VALUE_FIELDS}


def slim_outcomes(
    *,
    as_of: date,
    as_of_close: float | None,
    ticker_bars: pd.DataFrame | None,
    spy_bars: pd.DataFrame | None,
    sector_bars: pd.DataFrame | None = None,
    sector_etf: str | None = None,
    delisted: bool = False,
    in_universe: bool = True,
) -> dict[int, dict]:
    """horizon -> slim values for a pool name as of `as_of` (the run's as-of date, `as_of_close` its frozen close). Same arguments and
    meaning as the engine's `compute_outcomes`."""
    computed = eng.compute_outcomes(
        as_of=as_of,
        as_of_close=as_of_close,
        ticker_bars=ticker_bars,
        spy_bars=spy_bars,
        sector_bars=sector_bars,
        sector_etf=sector_etf,
        delisted=delisted,
        in_universe=in_universe,
    )
    return {o.horizon: slim_values(o) for o in computed}
