# Analyst price-target trend vs. price trend — signal feasibility investigation (2026-09-22)

> **Note:** the job this doc calls `monthly_price_target_snapshot` was renamed to `nightly_price_target_snapshot` and moved to a daily cadence on 2026-09-26 -- see `docs/price_target_daily_snapshot_implementation_2026-09-26.md`. The text below is left as written and describes the job as it was at the time.

Investigation only. Nothing was implemented; no code, schema, or crontab was changed.
Scratch scripts were run against `fathom.db` through a `mode=ro` connection (never copied the
1.2GB file — the sandbox has no room for that) and deleted afterwards.

## Summary

**There's a real, usable data foundation (564 tickers, most with 2-5+ years of matched monthly
history), and a genuine, non-trivial finding: analyst price targets are reactive, not predictive —
price moves first and targets catch up, not the other way around.** The price-vs-target %
gap is highly persistent (doesn't bounce back quickly) but, at a 1-month horizon, a wide gap
does correlate with a partial reversal in the *next* month's price — and that effect is
meaningfully stronger than a stock's own naive month-over-month reversal. That's a real,
if modest, incremental signal, not just restating "stocks that just popped tend to give some
of it back."

That said: three things temper how strong a claim this supports, and I'd want your read on
them before scoping any implementation (see §6):

1. **~56% of month-over-month target values are literally unchanged** — the "monthly" series is
   mostly a forward-fill of whenever an analyst last actually spoke, not a genuinely fresh
   monthly read. This mechanically inflates the "gap is persistent" finding and means real
   information arrives in irregular bursts, not evenly by month.
2. **The live monthly cron missed its most recent run** (FMP was paused on 2026-09-01, the exact
   day it fires) — the newest snapshot on disk is 2026-08-31, now 3+ weeks stale. This isn't
   self-healing; a missed month just stays missing until the next 1st-of-month run succeeds.
3. **This is a correlation study on ~12-65 monthly observations per ticker, with survivorship
   bias** (the universe is today's tracked tickers projected backward — anything that got
   delisted/went to zero since 2021 isn't in it) and **no backtest of an actual tradeable
   strategy** (position sizing, costs, realistic lag between "gap observed" and "trade
   executable"). The correlation is real and pools consistently across 518 tickers, but I
   haven't shown it survives contact with an actual strategy.

## 1. What price-target history exists

**Table**: `PriceTargetSnapshot` (`backend/core/models.py`) — `(ticker, snapshot_date,
target_consensus, target_high, target_low, target_median, fetched_at)`, deliberately
append-only (no unique constraint, never upserted). Grain is **one row per ticker per calendar
month** (month-end date), holding FMP's average/high/low/median price target **across all
covering analysts as of that date** — not per-analyst, and not a true rolling 6-month window,
a flat monthly point read.

Two writers feed it, both already documented in `CLAUDE.md`:

- **`pipeline/monthly_price_target_snapshot.py`** — ongoing cron, 3am server time, 1st of the
  month. Calls FMP's live `/price-target-consensus` (no history of its own) and appends one row
  per ticker per run, going forward only.
- **`pipeline/backfills/backfill_price_target_snapshots.py`** — one-time backfill, reconstructs
  history from FMP's `/price-target-news` (real per-analyst target actions, 2021+ for
  well-covered names) via `helpers/price_target_history.py::reconstruct_monthly_snapshots`: at
  each month-end, each analyst's most-recent target as of that date, averaged across every
  analyst who'd issued at least one target by then (split-adjusted via FMP's `adjPriceTarget`).

**Real DB state, confirmed via direct query:**

| | |
|---|---|
| Tickers with `PriceTargetSnapshot` rows | **566** |
| Total rows | 32,766 |
| Date range | 2021-04-30 → 2026-08-31 |
| Rows per ticker | median 62, top tier (well-covered, 5+yr) is a flat 65 |
| Thinnest tickers | ECHO (2 rows), FDXF/HONA (3), TMP/TPL (9), Q (11), FLY (12), EME (13), NBIS (16), **CRWV (17)**, SNDK (18) — all recent listings/spinoffs/IPOs with genuinely short real analyst-coverage history, not a data gap |

**The backfill only actually ran 2026-09-16** (confirmed from `logs/backfill_price_target_snapshots.log`
— 580 tickers processed, 32,764 rows inserted, 22.1 min, 0 failures) — six days before this
investigation. Before that, only 2 tickers (AAPL, MSFT) had any history at all, from a manual
test run on 2026-07-27. **This means the deep historical series this investigation relies on is
brand new**, not a long-running, previously-validated pipeline.

**The live monthly cron missed its 2026-09-01 run** (`CronRunLog` shows a `success` status, but
the run's own log reads `"Monthly price-target snapshot skipped: FMP paused (FMP_ENABLED=False)"`
— FMP was paused that specific morning). `.env` currently has `FMP_ENABLED=true`, so it's been
re-enabled since, but nothing re-ran the missed month — the next real snapshot won't land until
2026-10-01. **As of today (2026-09-22), every ticker's most recent price-target data point is
3+ weeks old.**

## 2. What price history exists at matching granularity

**`SharedBarsCache`** (`interval="1d"`, `backend/core/models.py` / `clients/shared_bars_cache.py`)
— the same table backing the Chart tab's technical overlays, Trend/Weinstein Stage, and
Liquidity Zones. Confirmed live:

| | |
|---|---|
| Tickers with `1d` bars | 582 |
| Total rows | 364,657 |
| Date range | 2021-09-20 → 2026-09-22 |

**Depth is not uniform per ticker** — this matters a lot for this investigation. `SharedBarsCache`
grows to "the maximum window ever requested" per `(ticker, interval)`, and the two nightly
consumers of `1d` bars request different windows: Trend/Weinstein Stage fetches 2 years for the
full ~572-ticker universe, Liquidity Zones fetches ~4 years but only for the much smaller W1-W5
watchlist union. A ticker only gets the wider window if it happens to sit on both. Confirmed:

- **100 tickers** have bars back to ~2021-09 (the full ~5yr window, i.e. they're on a watchlist)
- **482 tickers** only have bars back to ~2022-06 or later (the narrower 2yr window)

**Separately, I found a handful of tickers with genuinely broken/stale `SharedBarsCache` rows** —
AVB (27 rows, 2026-07-17 → 2026-08-24), EQR (14 rows, same window), EA (1 row, 2026-08-04) — a
tiny fraction of history for long-established, heavily-covered names, and stale by weeks even
against today. This looks like a nightly-job fetch issue specific to those tickers, unrelated to
this investigation's own question — flagging it, not root-causing it here.

**Overlap between the two series, across the full universe (564 tickers with both):**

| Matched PT+price window | Tickers |
|---|---|
| < 6 months | 6 |
| 6-12 months | 5 |
| 12-24 months | 453 |
| 2-4 years | 6 |
| 4+ years | 94 |

So **the large majority of tickers (453) are capped at the ~2-year `SharedBarsCache` window**
even when they have 5+ years of `PriceTargetSnapshot` history — the price side, not the
price-target side, is usually the binding constraint on how far back a comparison can go.

## 3. What `PriceTargetTrendCard` already computes (Analyst Ratings tab)

Read `frontend/components/analystRatings/PriceTargetTrendCard.tsx` /
`PriceTargetTrendChart.tsx` and the backend `get_analyst_ratings_data`
(`backend/data/analyst_ratings_data.py`). **It does not compute anything like a price-vs-target
trend, lead/lag, or gap statistic.** Specifically:

- The chart's x-axis is driven by **rating-action dates from `grades_historical`** (FMP's rating
  changes feed), not `PriceTargetSnapshot`'s own monthly cadence. For each rating-action date,
  the nearest `PriceTargetSnapshot` row within 45 days is looked up (`_nearest_by_date`) and its
  `target_consensus` plotted as a single line — **price target only, no stock price series at
  all** on this chart.
- The "Price Target by Recency" strip below it (`PriceTargetRecencyCard`) shows FMP's own
  ready-made Last Month / Last Quarter / Last Year / All Time average target buckets
  (`/price-target-summary`) — a different, non-`PriceTargetSnapshot` data source, purely
  informational, no price comparison.
- The one place price and target are compared at all is `PriceTargetSummary.upside_pct`
  (`current_price` vs. `target_consensus`, both **live, today's values only** — one snapshot in
  time, not a series).

So: what this investigation is proposing (a real price series overlaid against the target
series, and any derived lag/gap/mean-reversion read) would be **entirely new**, not a
refinement of something already there.

## 4. Real-data sample: 9 tickers across profiles

Computed directly from `PriceTargetSnapshot` (`target_consensus`) and `SharedBarsCache`
(`close`, matched to each snapshot month-end via nearest trading-day-on-or-before, 10-day
tolerance). `gap_pct = (close - target) / target × 100` — positive means price trades above
the analyst consensus target.

| Ticker | Profile | Matched months | Price CAGR¹ | Target CAGR¹ | Mean gap | Months price > target |
|---|---|---|---|---|---|---|
| AAPL | Mega-cap | 59 (2021-09→2026-07) | +15.6% | +10.1% | -3.4% | 23/59 (39%) |
| NVDA | Mega-cap / momentum | 60 | +82.9% | +79.3% | +2.4% | 31/60 (52%) |
| JPM | Value / financial | 60 | +25.4% | +11.7% | +5.8% | 37/60 (62%) |
| O | REIT / income | 24² | +5.3% | -1.6% | -11.3% | 1/24 (4%) |
| PLTR | Speculative growth | 55 | +130.6% | +96.1% | +46.8% | 36/55 (65%) |
| SNDK | Cyclical spin-off | 18² | +2582%³ | +1725%³ | +4.6% | 10/18 (56%) |
| RKLB | Recent IPO | 24² | +186.0% | +351.0% | +106.6% | 22/24 (92%) |
| KHC | Value / troubled | 24² | -17.2% | -21.0% | -23.8% | 0/24 (0%) |
| CRWV | Recent IPO (Mar-2025) | 17² | — | — | -1.6%⁴ | 8/17 (47%)⁴ |

¹ Annualized, log-linear OLS fit over the matched window — a crude trend estimate, not a real
CAGR over a clean start/end pair; sensitive to window length, shown for rough comparison only.
² Capped by `SharedBarsCache`'s narrower ~2yr window for that ticker (see §2), not by
`PriceTargetSnapshot`'s own longer history.
³ SNDK's memory-pricing-supercycle move (documented elsewhere in the codebase re: Step 3
normalization) makes a log-linear annualized rate nearly meaningless here — shown for
completeness, not as a usable number.
⁴ CRWV's swings are large enough (gap range -52% to +266% across the sample, see raw table
below) that a mean/CAGR summary understates how noisy this one is — see the raw monthly values.

**KHC** (0/24 months price above target) and **O** (1/24) are the cleanest illustrations of a
chronically-optimistic analyst consensus that price never catches up to, even as targets
themselves trend down. **RKLB** and **PLTR** are the mirror case — momentum names where price
usually runs ahead of a slower-moving consensus. **CRWV** is the volatile/short-history case the
brief asked for — 17 months of real data, most of them with the price target and price badly
disagreeing (a 190% gap in June 2025, a -43% gap thirteen months later) and no discernible
pattern.

Representative CRWV raw months (full sample is far noisier than the summary table conveys):

```
2025-05-31  target=$56.12  close=$111.31  gap=+98.3%
2025-06-30  target=$56.12  close=$163.06  gap=+190.5%
2025-11-30  target=$108.27 close=$73.12   gap=-32.5%
2026-07-31  target=$125.52 close=$71.77   gap=-42.8%
```

## 5. Does the relationship show lead, lag, or mean-reversion? (broad scan, 518 tickers)

Ran the same computation across every ticker with ≥40 `PriceTargetSnapshot` rows and ≥100
`SharedBarsCache` bars (518 of 523 qualified). All correlations are of **month-over-month %
changes** (Pearson), pooled across tickers (one number per ticker, then summarized).

| Statistic | Mean | Median | % of tickers positive |
|---|---|---|---|
| Corr(target Δ%, price Δ%) — **same month** | 0.114 | 0.093 | 71% |
| Corr(target Δ% this month, price Δ% **next** month) — target leads | -0.063 | -0.061 | 36% |
| Corr(price Δ% this month, target Δ% **next** month) — price leads | **0.172** | **0.182** | **81%** |
| Gap-level AR(1) (gap this month vs. last month) | 0.717 | 0.758 | **100%** |
| Corr(gap this month, price Δ% next month) | **-0.227** | **-0.225** | **90%** |

**Reading this:**

1. **Weak positive contemporaneous co-movement** (0.11) — expected; both are reacting to the
   same news flow in the same month.
2. **"Price leads target" is real and consistent (0.17 mean, 81% of tickers positive), and
   clearly stronger than "target leads price" (-0.06 mean, only 36% positive).** This is the
   headline qualitative finding: **analyst price targets are reactive, not predictive** — they
   get revised in response to where the stock has already moved, not ahead of it. This matches
   the well-known finance-literature finding that consensus price targets are largely
   extrapolative.
3. **The gap is highly persistent** (AR(1) = 0.72 mean, positive for literally every ticker
   checked) — a wide gap this month is very likely still wide next month. This is **not** the
   same as saying it never closes; the ~56% unchanged-target-month-over-month artifact (§1, §6)
   mechanically inflates this number — see the caveat below.
4. **A wide gap does correlate with next-month reversal** (-0.227 mean, 90% of tickers negative)
   — when price sits well above its target consensus, the following month's price move tends to
   be smaller/negative, and vice versa. This is the closest thing to an actual signal here.

**Control check — is #4 just ordinary stock-price mean reversion, or does the target add real
information?** Computed each ticker's own naive month-over-month price-return autocorrelation
(no target involved at all) as a baseline: mean **-0.070** (63% negative) — a much weaker,
textbook short-term-reversal-sized effect. The gap-based correlation (-0.227) is **meaningfully
stronger**, and stronger than the naive-price-only baseline in **404/518 tickers (78%)**. So the
analyst-target level does appear to carry incremental information beyond "the stock just moved a
lot and tends to give some back" — this isn't circular.

**Caveat on the "top individual tickers" ranking**: the strongest single-ticker `gap → next
price move` correlations (CBOE -0.69, AOS -0.65, AFL -0.65, ...) are all `n=24` (the narrower
~2yr `SharedBarsCache` tickers, §2) — a correlation on 24 monthly points is not reliable evidence
on its own; the 518-ticker pooled mean/consistency is the trustworthy number here, not any
individual ticker's ranking.

## 6. Data-quality issues to weigh before designing anything

1. **~56% of month-over-month `target_consensus` values are literally identical** (17,853 of
   32,169 pairs checked, 69% of tickers have >50% of their months unchanged). This is a real
   property of analyst behavior (they don't revise every month), correctly represented by the
   forward-fill reconstruction — not a bug — but it means:
   - The gap-AR(1) persistence number in §5 is partly mechanical (nothing changed that month, so
     of course the gap barely moved) rather than pure evidence of a slow-moving trend.
   - "Monthly" is a display grain, not an information grain — real analyst updates arrive in
     irregular bursts. Any signal design should probably think in terms of "time since last real
     target revision," not calendar months.
2. **The live cron is fragile to `FMP_ENABLED` pauses with no catch-up mechanism** — a missed
   1st-of-month run (as just happened 2026-09-01) leaves every ticker's target stale until the
   *next* month's run, with nothing auto-backfilling the gap the way the one-time backfill script
   did historically. If this becomes a live-facing signal, that's a real freshness risk worth a
   guard (e.g., an FMP-pause-aware catch-up run), not just a monthly cron's existing convention.
3. **Coverage thins out for smaller/newer names** — `ECHO`/`FDXF`/`HONA`/`TMP`/`Q` etc. have
   single-digit months of real snapshot history; this isn't a data-pipeline bug, it's genuinely
   thin analyst coverage, but any signal needs a minimum-history gate (I used ≥40 snapshots /
   ~3.3 years for the broad scan; a live feature would need its own, probably much shorter,
   threshold plus an explicit "insufficient data" state, matching this codebase's existing
   convention for exactly this situation elsewhere).
4. **`SharedBarsCache`'s per-ticker depth inconsistency (§2) is the actual binding constraint**
   on how far back a price-vs-target comparison can go for 453 of 564 tickers — capped at ~2
   years even though `PriceTargetSnapshot` often has 5. Widening it for this feature would mean
   either accepting the shorter window broadly, or deliberately fetching a wider window for
   tickers this feature cares about (which, per the existing "growth to max window ever
   requested" mechanism, would then also widen it for Trend/Weinstein — a real, not
   free, side effect worth deciding on purpose).
5. **Survivorship bias**: both universes (`PriceTargetSnapshot`'s backfill source and
   `SharedBarsCache`'s tracked universe) are built from *today's* S&P500/Dow/watchlist
   membership projected backward. A ticker that was delisted, went bankrupt, or got acquired
   since 2021 was never fetched and isn't in this analysis at all — meaning the "gap predicts
   reversion" finding in §5 is measured only on names that survived to be trackable today. I have
   no way to quantify the size of this bias from data already in this DB; flagging it as a
   structural limitation of the whole tracked-universe design, not fixable within this feature.
6. **A handful of `SharedBarsCache` rows are stale/broken independent of this investigation**
   (AVB, EQR, EA — §2) — worth a separate look, not blocking this one since it's a tiny fraction
   of the universe.
7. **This is monthly-grain data only.** FMP's `/price-target-news` (the backfill source) does
   have real per-analyst-action *dates*, not just month-end buckets — a genuinely higher-resolution
   reconstruction is possible if a monthly signal turns out too coarse, at the cost of re-deriving
   `reconstruct_monthly_snapshots` into a different (non-monthly) grain. Not attempted here; flagged
   as a design option, not a current gap in what exists.

## 7. Is this a viable signal? (my read)

**Provisionally yes, with real caveats** — this isn't obviously noise, but it also isn't a clean,
ready-to-ship number yet:

- The **"price leads target" finding (§5.2)** is, on its own, more of an *observation about
  analyst behavior* than a tradeable signal — it says targets are lagging indicators, which is
  useful context for interpreting the Analyst Ratings tab honestly, but isn't itself an actionable
  entry/exit trigger.
- The **gap-predicts-reversal finding (§5.4)**, net of the naive-reversion control, is the one
  genuinely promising thread — real, consistent in sign across 90% of a 518-ticker universe, and
  stronger than a naive price-only baseline in 78% of them. But it's a *correlation* result on
  monthly, forward-fill-heavy, survivorship-biased data with no position-sizing/cost/execution-lag
  backtest behind it yet. I'd treat "there's something here worth building further" as confirmed;
  "here's a number you can size a position off" as not yet confirmed.

## 8. If you want to pursue this — proposed design for review (not built)

Not implemented; sketched for your review before any implementation round.

- **Surfacing**: a new, informational-only card on the Analyst Ratings tab (or a Technical-tab
  companion, given the "reactive not predictive" framing is closer to a technical read than a
  fundamentals one) — plots price and target consensus on the same chart (something
  `PriceTargetTrendChart` doesn't do today, §3), with the current gap % and a plain-language
  read ("price trading 23% above its 12-month-average target — consensus has historically lagged
  a move like this"). Never touches Step 1-5/Overall Assessment scoring, matching every other
  lens in this app's family (Speculative Growth, Trend Structure, Weinstein Stage, etc.).
- **Compute approach**: reuse `PriceTargetSnapshot` and `SharedBarsCache` as-is — no new fetch,
  no new external call. A new pure-function module (`analysis/`, matching `trend_structure`'s/
  `liquidity_zones`' own no-DB/no-HTTP convention) takes the two series and returns
  gap-at-latest-snapshot, gap history, and whatever summary stat we land on (I'd lean toward
  "months since last real target revision" alongside the raw gap, given §6.1).
- **Minimum-history gate**: something well short of the ≥40-snapshot bar I used for the broad
  scan (that was chosen for statistical power in this investigation, not as a UI threshold) —
  probably a handful of real (non-forward-filled) target revisions, with an explicit
  "insufficient data" state for the ~150 thinly-covered tickers.
- **Freshness**: needs the FMP-pause catch-up question from §6.2 resolved one way or the other
  before this is live-facing, given the cron just demonstrated the gap it leaves.
- **What I would NOT do**: turn the correlation in §5.4 into a scored/graded signal (a la
  Speculative Growth's qualification gate) without first backtesting an actual strategy
  (entry/exit rules, holding period, costs) — the investigation supports "worth surfacing as
  context," not yet "worth scoring."

**Manual verification needed from you (no browser in this sandbox)**: nothing UI-related was
built this round, so nothing to check yet — flagging only that any chart/card built from this
would need the usual manual screen check before considering it done.
