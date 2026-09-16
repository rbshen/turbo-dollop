"""Reconstructs a monthly rolling price-target consensus series from FMP's
raw per-analyst /price-target-news actions -- the only caller is
pipeline/backfills/backfill_price_target_snapshots.py.

FMP's /price-target-news returns one row per individual analyst action
(a price-target raise/cut, often alongside a rating change), not a
ready-made consensus series the way /grades-historical already is. This
module reconstructs what /price-target-consensus would plausibly have read
at each point in the past: at a given date, each analyst's own MOST RECENT
target as of that date, averaged across every analyst who had issued at
least one target by then (a rolling most-recent-per-analyst consensus).

`analystCompany` -- not `analystName`, confirmed live to frequently be an
empty string -- is used as the per-analyst identity key.
"""

from datetime import date

import pandas as pd


def reconstruct_monthly_snapshots(news_rows: list[dict], before: date | None = None) -> list[dict]:
    """Returns one dict per calendar month-end -- {snapshot_date,
    target_consensus, target_high, target_low, target_median} -- covering
    every month from the earliest analyst action in `news_rows` through the
    last FULL calendar month strictly before `before` (or before today if
    `before` is None). The in-progress current month is deliberately never
    included -- that's the ongoing monthly cron's own domain, not this
    reconstruction's (mirrors backfill_entry_signal_events.py's own
    backfill/cron boundary).

    Passing the caller's own earliest already-stored snapshot_date as
    `before` makes this naturally idempotent: reconstruction never produces
    a month on or after that date, so a second run against an
    already-backfilled ticker returns [] (an empty month range), not
    duplicate/conflicting rows -- no separate "already backfilled" flag is
    needed.

    Returns [] if `news_rows` has no usable rows (missing symbol coverage,
    or every row is missing analystCompany/priceTarget/publishedDate).
    """
    if not news_rows:
        return []

    df = pd.DataFrame(news_rows)
    required = {"analystCompany", "priceTarget", "publishedDate"}
    if not required.issubset(df.columns):
        return []

    df = df.dropna(subset=["analystCompany", "priceTarget", "publishedDate"])
    df = df[df["analystCompany"].astype(str).str.strip() != ""]
    if df.empty:
        return []

    df["publishedDate"] = pd.to_datetime(df["publishedDate"], utc=True).dt.tz_localize(None)
    df = df.sort_values("publishedDate").drop_duplicates(subset=["analystCompany", "publishedDate"], keep="last")

    pivot = df.pivot(index="publishedDate", columns="analystCompany", values="priceTarget").sort_index()

    earliest_month_end = pivot.index.min().normalize() + pd.offsets.MonthEnd(0)
    cutoff = pd.Timestamp(before) if before is not None else pd.Timestamp(date.today())
    last_month_end = cutoff.replace(day=1) - pd.Timedelta(days=1)

    month_ends = pd.date_range(earliest_month_end, last_month_end, freq="ME")
    if month_ends.empty:
        return []

    combined_index = pivot.index.union(month_ends)
    filled = pivot.reindex(combined_index).sort_index().ffill()
    monthly = filled.reindex(month_ends)

    results = []
    for ts, row in monthly.iterrows():
        valid = row.dropna()
        if valid.empty:
            continue
        results.append(
            {
                "snapshot_date": ts.date(),
                "target_consensus": float(valid.mean()),
                "target_high": float(valid.max()),
                "target_low": float(valid.min()),
                "target_median": float(valid.median()),
            }
        )
    return results
