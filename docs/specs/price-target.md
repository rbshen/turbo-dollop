# Price-target trend (Analyst Ratings tab)

The story of this feature in three parts: the legacy/live methodology split found investigating
a real user-visible gap, the daily-snapshot implementation that followed, and the separate,
definitive research verdict that a price-vs-analyst-target signal isn't viable to build on. All
three pieces are still current — the methodology split is live production behavior, and the
"shelved" verdict is the standing answer to "should we build an alert/score off this."

## Architecture: three different numbers from one endpoint response

`get_analyst_ratings_data` (`data/analyst_ratings_data.py`) reads three genuinely different FMP
sources into one response, rendered by `AnalystRatingsTab.tsx`'s "At a Glance" panel and its
trend card with the recency strip:

| Piece | Source | Refreshed |
|---|---|---|
| At a Glance target range/avg | FMP `/price-target-consensus`, cached `price_target_consensus/latest` | cache, 7-day staleness |
| Last Month/Quarter/Year/All Time boxes | FMP `/price-target-summary`, cached `price_target_summary/latest` | cache, 7-day staleness |
| Trend chart line | `PriceTargetSnapshot` table | nightly cron + one-time backfill |

**The recency boxes' "N analysts" is a count of price-target *actions*, not distinct analysts.**
FMP's own nested windows (`lastMonthCount`, `lastQuarterCount`, `lastYearCount`, `allTimeCount`)
count price-target news rows, not unique firms — confirmed directly: one real ticker's "All Time"
count matched its literal count of `/price-target-news` rows exactly, from a much smaller number
of distinct analyst firms. FMP's own window boundaries were not reverse-engineered.

## Why the trend line and At-a-Glance number can genuinely disagree by 10-25%+

This was investigated directly (2026-09-25) after a user-visible gap on one real ticker, and the
answer generalizes: **the two numbers use different definitions of "average target," not a stale
join, a unit mismatch, or a wrong analyst subset.** Both were reproduced exactly from raw FMP
per-analyst action data:

- **At a Glance** = mean of each analyst's latest target **among analysts who acted in roughly
  the last ~180 days** (an inferred window — it reproduces FMP's live consensus to the cent on
  every ticker checked, but FMP doesn't document it, and neighboring 90-day/365-day windows do
  not reproduce it as cleanly).
- **Trend (pre-daily-snapshot history)** = mean of each analyst's latest target **across every
  analyst who has *ever* issued one, with no age cutoff at all** — so a name with many years of
  covered history can have a large fraction of its "latest per analyst" set sitting on
  multi-year-stale targets, which pulls the mean toward wherever the stock traded that long ago.

Confirmed systemic, not a one-ticker anomaly: across a sample of tickers with both figures
cached, the trend-reconstruction value sat below the At-a-Glance value on the large majority
(median gap roughly -10%, over half more than 10 points apart) — the gap widens with how many
analysts cover the name and how long its price-target history runs, exactly as the "stale
target dilution" mechanism predicts.

**This is now labeled, not hidden.** `PriceTargetSnapshot.methodology` (`legacy_all_analysts` |
`live_consensus`) tags every row so a consumer can tell which definition produced it — see
"Daily snapshot + methodology labeling" below for the mechanism, and the chart-split decision
that was tried and then reverted.

## Missed-run behavior, before the daily cadence

Before the 2026-09-26 daily-snapshot change, the job ran monthly and had **no catch-up logic at
all**: a gated no-op under the pre-2026-09-24 `FMP_ENABLED=False` global flag was recorded as a
`success` heartbeat (since fixed — see "Skip/failure status" below), and a missed 1st of the
month was a permanent gap in the trend line until the next scheduled run, exactly the same shape
of gap Market Breadth's own missed-run investigation found independently. This risk is now
structurally much smaller at daily cadence (a single missed night just means one thin day in a
now-dense series), but the job still has no explicit catch-up/backfill-on-recovery logic.

## Daily snapshot + methodology labeling (implemented 2026-09-26)

**Schema**: `PriceTargetSnapshot.methodology` (nullable), added by `_add_missing_columns`.
Unique index `uq_pricetargetsnapshot_ticker_date` on `(ticker, snapshot_date)`, created
idempotently on existing DBs by `db._ensure_unique_indexes()` (since `_add_missing_columns` is
add-column-only and can't add a constraint). A one-time migration script tagged every
pre-existing row by its own `fetched_at` date (the backfill batch — 32,764 rows, built from all
analysts since 2021 with no recency cutoff, hence not comparable to FMP's ~180-day live consensus →
`legacy_all_analysts`; the
one earlier manual test run → `live_consensus`).

**Job**: `pipeline.nightly_price_target_snapshot` (renamed from `monthly_price_target_snapshot`
2026-09-27), now runs **daily 02:10**. Fetches through the same `price_target_consensus` cache
row the Analyst Ratings tab itself uses (1-day staleness), so tab views and the nightly job
share one fetch — the tab's own At-a-Glance figure is now at most 1 day old after a nightly run.
Every row written is tagged `live_consensus`; re-running for the same `(ticker, snapshot_date)`
updates the row rather than duplicating it. An empty/absent FMP response raises per ticker
(counted as a failure) instead of writing an all-null row.

**Universe** (`load_us_price_target_universe`): `load_full_tracked_universe` (index membership +
ever-viewed + scored + watchlisted) filtered to US-listed tickers via the cached profile
exchange, minus `delisted_at`-flagged tickers — 580 tickers as of the last full-universe run
(grew from an earlier 518-ticker S&P-500-plus-Dow scope once the wider universe function was
substituted in). **`BF-B` symbol-format fix**: FMP's three `/price-target-*` endpoints only
recognize it as `BF.B` (`PRICE_TARGET_SYMBOL_OVERRIDES`, a one-entry allowlist scoped to only
those three endpoints) — `/profile` and `/grades-consensus` want the hyphen form, and `BRK-B`
must **not** be remapped (it answers with genuinely different data under each spelling, unlike
BF-B). A handful of tickers (ERIE, L, NWS, and a few ETF/OTC names) genuinely have no FMP
price-target coverage (also SPY, TECL, PARA) and fail harmlessly every night — a run normally reports
~8 failures; expected, not a regression.

**Skip/failure status**: the existing `analyst_ratings` group-off skip guard already recorded a
real `skipped` `CronRunLog` status (fixed as part of the broader 2026-09-24 data-groups work).
The gap this build closed was a different silent-success case — a run where *every* ticker
failed (FMP down, key revoked) previously still logged plain `success`; `record_outcome()` now
distinguishes gated (`skipped`) / all-failed (`failure`, raises) / partial-success
(`success`, "N written, M failed").

**Chart split tried, then reverted the same week.** `PriceTargetTrendChart.tsx` briefly drew two
series (dashed = legacy, solid-with-dots = live) when a ticker's history spanned both
methodologies. This was deliberately reverted — the legacy/live jump now renders as an
undifferentiated move on a single continuous area chart. `methodology` remains in the column,
API response, and TS type; the chart just no longer reads it. Anyone re-adding a visual split in
the future should know this was tried once already and pulled back, not that it was never
considered.

## Verdict: not a viable predictive signal — shelve it (2026-09-25)

A separate, definitive research pass — not an implementation step, a decision — tested whether
`(price − analyst target) / target` predicts forward stock returns, as a candidate for a future
card/alert/score input. **Answer: no, and this is a considered conclusion, not "needs more
data."**

- **Out-of-sample result**: the monthly cross-sectional rank correlation between the price/target
  gap and next-21-trading-day SPY-relative return was **-0.012** (t = -0.41) across 30 held-out
  months, with a 95% interval of roughly [-0.07, +0.05] — indistinguishable from zero. The
  long-short quintile spread was +0.2%/month (t = +0.24), also indistinguishable from zero.
- **The study was adequately powered to see a moderate effect and found none**: the design could
  have detected a true IC of ~0.08 at 80% power; what it found (essentially 0) rules out
  anything approaching a usable signal, though it can't formally exclude a true effect in the
  ~0.02-0.03 range — an effect that small wouldn't survive real-world costs or justify a feature
  even if confirmed.
- **A prior positive-looking finding was reproduced and explained away, not just discarded.** An
  earlier exploratory pass had found a per-ticker time-series correlation (gap vs. next-month
  return) that looked like a real, if modest, edge. Re-running that exact statistic on the fuller
  panel reproduced the effect — but a **placebo with no analyst-target input at all** (price
  relative to the ticker's own historical average) produced an even *stronger* version of the
  same statistic. What the original statistic was actually measuring was ordinary per-ticker
  price-level mean reversion, not analyst-target information — a mechanical time-series artifact,
  not a cross-sectional trading signal (and a cross-sectional signal is what any real feature
  would need, since that's the only form that's actually tradeable across a universe).
- **One promising-looking tail bucket vanished under scrutiny.** A "price far below target"
  bucket initially showed a large, statistically-suggestive excess return — but this turned out
  to be driven almost entirely by a handful of tickers whose split-adjusted analyst targets sat
  on a different accounting basis in some quarters than their prices, manufacturing an
  artificially large "gap" reading. Once those known basis-defect tickers were excluded, the
  effect collapsed to statistically indistinguishable from zero. This exact case is recorded
  here because it's precisely the kind of number that would have justified building the feature
  had it not been checked.
- **Validated that the reconstruction underlying this whole study is a legitimate stand-in for
  the live daily-snapshot definition** — a 180-day latest-per-analyst reconstruction reproduces
  FMP's own live consensus within 1% for the large majority of tickers, so the (much larger)
  historical reconstruction used for the backtest is trustworthy evidence, not an artifact of
  the study's own methodology.

**What survives**: the descriptive Analyst Ratings display itself (price vs. target as context,
the legacy-vs-live methodology note above) is unaffected — this conclusion is only about
building a *predictive* feature (a card, alert, or score input) on top of the gap, which should
not be done. If this is ever revisited, the fresh-only, SPY-relative, pre-split-basis-screened
protocol from this study is the one to reuse — the FMP action-log density and the split-basis
screen materially changed the answer here and would need to be repeated first.
