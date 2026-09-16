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

Pivots on FMP's `adjPriceTarget` field, not the raw `priceTarget` field --
`priceTarget` is the analyst's nominal figure exactly as originally
published, never retroactively rescaled for a later stock split;
`adjPriceTarget` is the same target adjusted for the security's current
share count (confirmed live: always present, e.g. GOOGL's 2021-10-27
Oppenheimer row reads `priceTarget: 3500, adjPriceTarget: 175` after
GOOGL's July 2022 20:1 split). Since a stale analyst target (one with no
newer action since) is forward-filled indefinitely below, an un-adjusted
pre-split value would corrupt every later month's mean/high forever, not
just the months immediately around the split -- confirmed real case: this
alone inflated GOOGL's 2024-04 reconstructed consensus to $892.78 against a
genuine ~$160-180 range. Falls back to raw `priceTarget` only if
`adjPriceTarget` is missing from a given row.
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

    # Split-adjusted where available -- see this module's own docstring.
    # `fillna` covers a row that's missing `adjPriceTarget` specifically
    # (confirmed live this never happens, but defensive); the `if` branch
    # covers a caller/test that omits the column entirely.
    price_target_col = df["adjPriceTarget"].fillna(df["priceTarget"]) if "adjPriceTarget" in df.columns else df["priceTarget"]
    df = df.assign(_effective_price_target=price_target_col)

    pivot = df.pivot(index="publishedDate", columns="analystCompany", values="_effective_price_target").sort_index()

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
