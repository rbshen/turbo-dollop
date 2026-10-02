"""Pure 3-way composite momentum scoring engine -- no DB/HTTP, mirrors this
package's other pure scoring modules (step4.py, trend.py). See
data/momentum_data.py for orchestration (universe/Moat lookup, price
fetch) and pipeline/monthly_momentum_snapshot.py for the cron entry point.

Methodology ported directly from the original ad hoc scratch script
(~/scratch/fathom-momentum-live/, validated against real cached data before
this feature existed -- see CLAUDE.md's Momentum section): trailing total
return over 3/6/12-month windows anchored to a given date, using raw
(non-skip-month) returns since averaging three windows already dampens
single-month noise, then a simple equal-weighted average as the composite
ranking score."""

from dataclasses import dataclass

import pandas as pd

LOOKBACK_MONTHS = [3, 6, 12]

# Informational-only short windows shown beside the ranking columns -- never part of the composite or
# the rank, and a ticker missing one of them is kept (the value is just None), never dropped.
INFO_1W_DAYS = 7
INFO_1MO_MONTHS = 1


@dataclass(frozen=True)
class MomentumRankRow:
    ticker: str
    return_3mo: float
    return_6mo: float
    return_12mo: float
    composite_score: float
    rank: int
    return_1w: float | None = None
    return_1mo: float | None = None


def _price_on_or_before(df: pd.DataFrame, target: pd.Timestamp) -> float | None:
    eligible = df.loc[df.index <= target]
    if eligible.empty:
        return None
    return float(eligible["close"].iloc[-1])


def compute_momentum_ranking(
    price_histories: dict[str, pd.DataFrame], anchor_date: pd.Timestamp
) -> list[MomentumRankRow]:
    """Drops any ticker with no price data on/before `anchor_date`, or
    missing a price on/before any of the three lookback targets (e.g. a
    recent IPO without 12 months of history) -- never imputes. Composite is
    the simple average of the three raw trailing returns (1w/1mo are
    informational only and never enter it). Returns rows
    sorted by composite_score descending, 1-based `rank` assigned by that
    order (ties broken by ticker for a deterministic result)."""
    unranked: list[tuple[str, float, float, float, float, float | None, float | None]] = []

    for ticker, df in price_histories.items():
        if df is None or df.empty:
            continue

        as_of_price = _price_on_or_before(df, anchor_date)
        if as_of_price is None:
            continue

        returns: dict[int, float] = {}
        for months in LOOKBACK_MONTHS:
            target = anchor_date - pd.DateOffset(months=months)
            base_price = _price_on_or_before(df, target)
            if base_price is None:
                break
            returns[months] = (as_of_price / base_price) - 1.0

        if len(returns) != len(LOOKBACK_MONTHS):
            continue

        composite = sum(returns.values()) / len(LOOKBACK_MONTHS)
        info_returns: list[float | None] = []
        for target in (anchor_date - pd.Timedelta(days=INFO_1W_DAYS), anchor_date - pd.DateOffset(months=INFO_1MO_MONTHS)):
            base_price = _price_on_or_before(df, target)
            info_returns.append(None if base_price is None else (as_of_price / base_price) - 1.0)

        unranked.append((ticker, returns[3], returns[6], returns[12], composite, info_returns[0], info_returns[1]))

    unranked.sort(key=lambda row: (-row[4], row[0]))

    return [
        MomentumRankRow(
            ticker=ticker,
            return_3mo=r3,
            return_6mo=r6,
            return_12mo=r12,
            composite_score=composite,
            rank=i,
            return_1w=r1w,
            return_1mo=r1mo,
        )
        for i, (ticker, r3, r6, r12, composite, r1w, r1mo) in enumerate(unranked, start=1)
    ]
