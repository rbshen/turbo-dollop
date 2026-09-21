# Market breadth signal — feasibility investigation (2026-09-21)

Investigation only. Nothing was implemented; no code, schema, or crontab was changed.
Scratch scripts were run against `fathom.db` through a `mode=ro` connection and deleted afterwards.

Requested design (unchanged): S&P 500 universe via `load_universe_tickers`, daily cron, Yahoo Finance,
new dedicated table (one row per trading day), new top-level nav page. Row-1 metrics: % of constituents
above SMA50, % above SMA200, net new 52-week highs minus lows (count).

## Summary

**Feasible, and cheap.** The bars this job needs are already in `SharedBarsCache` every night, because
`nightly_trend_calculation` (3:10 AM) fetches all 503 S&P 500 tickers at 2y. A breadth job scheduled after
it reads warm cache: about 2–3 s of work, zero incremental Yahoo requests.

Four things need a decision or a correction from you before implementation (section 6):

1. `load_universe_tickers` is S&P 500 **∪ Dow**, not S&P 500 alone. Harmless today (Dow ⊂ S&P 500, union = 503) but not what the name implies.
2. 52-week highs/lows are **not cached anywhere**. Only SMA50/200 position is (in `TrendAnalysis`). Close-based vs intraday-based changes the answer materially.
3. This is **not the first daily cross-sectional job**. The trend job already sweeps 581 tickers daily. What is new is a growing time series and a hard ordering dependency.
4. "One row per trading day, mirroring `SectorEtfReturn`" is contradictory: `SectorEtfReturn` is long format (many rows per date).

## 1. Is SMA50/SMA200 / 52-week high-low already cached cross-sectionally?

| Value | Cached? | Where | Notes |
|---|---|---|---|
| SMA50 position | Yes | `TrendAnalysis.sma50_position_pct` (+ `sma50_cross`) | latest-only, upserted nightly |
| SMA200 position | Yes | `TrendAnalysis.sma200_position_pct` (+ `sma200_cross`) | latest-only |
| 52-week high/low | **No** | nowhere | grep of models, `analysis/`, `data/trend_analysis_data.py` finds none. FMP `yearHigh`/`yearLow` exists on the cached quote, but it is FMP, 7-day staleness, intraday-based, and not point-in-time. Not usable. |
| Raw daily OHLC | Yes | `SharedBarsCache` (`interval="1d"`) | all 503 S&P 500 tickers |

**Freshness (checked live, Mon 2026-09-21 10:49 UTC):**
- `TrendAnalysis`: 503/503 S&P 500 tickers have a row, all `bars_as_of = 2026-09-18` (the last completed session), all written by the 03:10 run. Same-night, not lagged.
- `SharedBarsCache` 1d: 503/503 present, all with a bar on 2026-09-18. Depth: 409 tickers back to 2024-09 (2y), 89 back to 2021-09 (5y, the Liquidity Zone tickers), the remaining 5 with shorter histories (recent IPOs/spin-offs and one other; see below). 318,002 rows total for the universe.

**Consistency check:** computing SMA50/SMA200 from `SharedBarsCache` closes and comparing the
above/below sign against `TrendAnalysis.sma{50,200}_position_pct`: 503/503 and 501/501 agree.
(%>SMA50 = 27.8%, %>SMA200 = 49.3% as of 2026-09-18 on both paths.)

**Recommendation: compute all three from `SharedBarsCache`, not `TrendAnalysis`.**
- `TrendAnalysis` has no 52-week fields, so a second source would be needed regardless.
- It is latest-only, so it cannot seed history.
- A ticker whose fetch fails keeps its old row with an old `bars_as_of`, so reading it needs a per-row staleness filter anyway.
- Use the same call the trend job makes: `clients.shared_bars_cache.get_or_fetch_bars_batch(tickers, "1d", 730, auto_adjust=False)`. Warm cache = read only; if the trend job failed or overran, it self-heals with one live fetch and writes through the shared cache like every other consumer.

Data-thin tickers to handle via an "eligible" count rather than dropping silently: FDXF (80 bars, joined the index 2026-06-01), HONA (67, joined 2026-06-29), Q (225, joined 2025-11-04; has SMA200 but not a full 52-week window). Today: SMA50 eligible 503, SMA200 eligible 501, 52-week eligible 499.

**Implementation gotcha found on the way:** the 4th ticker excluded from the 52-week count, FISV, is *not* thin: it has 500 daily bars. It was excluded only because my check used a strict `min_periods=252` on a date-union frame, so a single missing bar inside its trailing 252 rows disqualified it. The real job should count each ticker's own last 252 bars (or tolerate a small number of gaps) instead of requiring 252 non-null rows on the shared date index. This affects at most a handful of tickers, but it would otherwise silently shrink the denominator. I did not investigate where FISV's gap comes from (the FI→FISV ticker change is a plausible cause).

## 2. Call volume and runtime

Measured components against the real cache (raw SQL, deliberately **not** `get_or_fetch_bars_batch`, which can write to the real DB when stale):

| Step (503 tickers × full 1,255-day history) | Time |
|---|---|
| Column-only read of 318,002 bars | 0.9–1.6 s |
| Pivot to date × ticker | 0.25 s |
| SMA50, SMA200, 252-session high/low, all dates | 0.45–0.5 s |

Warm path total: **~2–3 s**, plus one upsert. Computing only the latest date is cheaper still.

Cold path (cache empty/stale, i.e. the trend job did not run first): one Yahoo batch. Measured live, direct `yf.download`, `threads=True`, `auto_adjust=False`, all 503 tickers: **32.2 s at `2y`**, 28.7 s at `1y`. yfinance's multi-ticker download is a thread pool of per-ticker requests, so this is ~503 HTTP requests, not one bulk call.
`1y` is not usable anyway: it returns 251 bars, one short of a 252-session window. The existing `2y` tier is the right one.

References:
- `nightly_sector_heatmap`: 1.3–2.3 s for **11** tickers. Not a meaningful reference for 503; it is a single small round trip.
- `nightly_trend_calculation`, the real comparable (581 tickers, same shared cache): 52–314 s over the last 10 runs. The 3–6× spread is not fully explained. Slow runs (~270–314 s: 09-15, 09-17, 09-19) fall on weekday-evening-ET nights, where a live refetch is expected, but two such nights (09-16, 09-18) were fast (88 s, 116 s). Treat ~30 s as the cold floor and ~5 min as the cold ceiling. I did not root-cause the variance.

## 3. Constituent list

Available with no extra fetch: `IndexConstituent` (`sp500`: 503 rows, refreshed Sundays 1:00 AM by the Wikipedia scraper, last synced 2026-09-20).

But `load_universe_tickers` returns `load_sp500_tickers ∪ load_dow_tickers`. Verified Dow (30) ⊂ S&P 500 (503), so union = 503 today, and results are identical. If you want "S&P 500 only" strictly, `load_sp500_tickers` (same module, `pipeline/nightly_fundamentals_fetch.py`) is the exact function. Recommend that one; it costs nothing and cannot drift if a Dow-only name ever appears.

Notes: 503 tickers is not 500 companies (dual-class lines such as GOOG/GOOGL). Tickers with a dash (`BRK-B`, `BF-B`) are stored normalized and matched the cache without special handling.

## 4. Proposed schema and schedule

### Table `MarketBreadthSnapshot`

Wide, one row per `(universe, as_of_date)`. Follows `SectorEtfReturn` conventions for units (percentage **points**, `computed_at`, `as_of_date` = the last completed session, upsert so weekend/holiday re-runs are idempotent).

| Column | Type | Notes |
|---|---|---|
| `universe` | `str` (PK part) | `"sp500"`. See below for why it is in the key. |
| `as_of_date` | `date` (PK part) | anchor session, resolved from the fetched data capped at the last completed session (same as sector heatmap's `_resolve_anchor`) |
| `computed_at` | `datetime` | |
| `constituents` | `int` | tickers in the universe at compute time |
| `stale_excluded` | `int` | tickers with no bar on `as_of_date`, excluded from every count |
| `sma50_eligible` | `int` | tickers with ≥50 bars |
| `sma50_above` | `int` | close > SMA50 |
| `pct_above_sma50` | `float` | points, `above / eligible * 100` |
| `sma200_eligible` | `int` | ≥200 bars |
| `sma200_above` | `int` | |
| `pct_above_sma200` | `float` | |
| `hl_eligible` | `int` | ≥252 bars |
| `new_highs` | `int` | |
| `new_lows` | `int` | |
| `net_new_highs` | `int` | `new_highs − new_lows` |
| `is_backfilled` | `bool` | true for rows from the one-time historical backfill |

Why `universe` is in the key even though only `sp500` exists: this codebase's migration tooling (`_add_missing_columns`) is additive-only and cannot change a primary key or unique constraint (the reason `WarrenSignalEvent` had to be a new table). Adding a Dow / Nasdaq-100 / full-tracked universe later would otherwise mean a table recreate. Cost now: one column.

Retention: no pruning recommended, unlike `SectorEtfReturn`. The history is the product for a breadth chart, and a row is ~100 bytes (~365 rows/year).

Definition choices (need your call, section 6): "new 52-week high" as implemented in my check = today's value ≥ max of the trailing **252 sessions including today** (ties count), requiring a full 252-session window.

### Cron slot

Current daily window: 3:10 trend · 3:20 BB+RSI · 3:25 Liquidity Zones · 3:30 sector heatmap · 3:40 Warren · 3:50 score recompute · 3:55 backup.

**Recommend 3:35 AM.**
- Must run after 3:10 (warms the cache). 3:15 is too tight: the slowest recent trend run finished 3:15:18. 3:35 leaves a >20 min margin.
- The 3:30 heatmap takes ~2 s; Warren does not start until 3:40. Warm-path breadth (~3 s) fits with room to spare.
- Nothing reads its output, so its order relative to the 3:50 score recompute does not matter (unlike the technical jobs the recompute copies from).
- Only a cold run (~30 s–5 min) could spill into Warren's start. Overlap would be SQLite writer-lock contention only (they touch different rows), the same class of risk as the 2026-09-11 cron audit's finding #5.

Wiring a new job requires all of (the tests in `tests/test_cron_wiring.py` enforce these): `CRON_JOB_NAMES`, `_EXPECTED_CADENCE_HOURS` (`_DAILY_HOURS`), `JOB_METADATA` (`sort_minutes = 3*60+35`, checked against crontab by `test_job_metadata_sort_minutes_match_crontab`), the `crontab.txt` entry, `cron_heartbeat(...)` at the script's entry point, an `OPS_RUNBOOK.md` entry + log-table row, then **`crontab crontab.txt` reinstalled**. Live crontab was verified byte-identical to `crontab.txt` today, so no existing drift. It would be the 18th job.

### Surface

Mirrors `/sectors`: `GET /api/market-breadth` (route in `core/main.py`, like `/api/sector-heatmap`), `app/breadth/page.tsx`, a `TopNav.tsx` entry (Sectors/Momentum open in a new tab). The API should return the latest row plus a trailing history series, since a breadth page is mostly about trend over time.

## 5. What makes this more expensive / riskier than the existing jobs

1. **Premise correction: it is not the first daily cross-sectional job.** `nightly_trend_calculation` (581 tickers), `nightly_fundamentals_fetch` (universe-wide) and `nightly_score_recompute` are all daily and universe-wide. What is genuinely new: (a) the output is an **accumulating time series** (the others are latest-only upserts, or, for the heatmap, a small rolling window); (b) it is the first job whose **cheapness depends on running after another job**.
2. **Ordering dependency.** If the job ever runs before the trend job (or the trend job fails), it does its own ~503-request live fetch. It still works, but at 30 s–5 min instead of 3 s, and if it overlaps a still-running trend job both may fetch the same tickers concurrently. The 3:35 slot avoids this in normal operation.
3. **Silent skew from a partial Yahoo response.** Breadth is a ratio, so if 60 tickers fail to fetch, the percentages are computed over 443 survivors and still look plausible. The job needs a coverage gate: if fewer than ~97% of constituents have a bar on the anchor date, raise (heartbeat failure) rather than write a row. `stale_excluded` records what was dropped when under the gate.
4. **Backfill can inflate every nightly run if done through the shared cache.** The cache's width logic ("grow to the max window ever requested", preserved width snapped to a period tier) means widening 409 tickers from 2y to 5y makes every subsequent stale refetch pull 5y for them: roughly +300k rows (~+50 MB on a 1.2 GB DB) and a longer nightly download, permanently. Do any backfill with a direct `yahoo_client.get_history` fetch in a throwaway script that never touches `SharedBarsCache`.
5. **History without a fetch is limited to ~1 year, and is survivorship-biased.** From cache alone: SMA200 history from 2025-07-09 (~302 sessions), 52-week history from 2025-09-22 (~250 sessions). Backfilled rows apply *today's* constituents to past dates (RDDT joined 2026-08-18 but would count in earlier months). `IndexConstituent.date_added` can drop late joiners; removals are not tracked at all, so that bias remains. Live nightly rows are point-in-time by construction, hence `is_backfilled`.
6. **Weekend/holiday runs.** A 7-day cron re-derives the same anchor and upserts over it (idempotent; same as sector heatmap). Not holiday-aware: a market holiday causes one extra harmless refetch, as documented for the shared cache.
7. **Incidental, not caused by this job:** the trend job burns ~30 s every night retrying WBA and TWTR (`No data found, symbol may be delisted`; a failed fetch caches nothing, so it retries forever). Neither is in the S&P 500, so a breadth job over `sp500` does not have this cost, but it is a standing tax on the 3:10 job.

Not expensive: DB growth (~365 tiny rows/year), FMP usage (zero calls, no `fmp_enabled` guard needed), and Yahoo requests on the normal warm path (zero incremental).

## 6. Decisions needed before implementation

1. **Universe function:** `load_sp500_tickers` (strictly S&P 500) instead of `load_universe_tickers` (S&P 500 ∪ Dow)? Recommend yes; identical output today.
2. **52-week definition:** close-based or intraday high/low? Over the last 250 sessions, net(close) − net(intraday) differed by a mean of 6.9 names and a max of 54. Latest session (2026-09-18): close-based 2 highs / 30 lows (net −28); intraday 5 / 29 (net −24). Intraday is the common convention (charting platforms, and Yahoo/FMP's own 52-week figures), so I lean intraday; close-based is more consistent with the SMA metrics. Also confirm the 252-session, ties-count, full-window-required rule.
3. **Table shape:** wide `(universe, as_of_date)` as proposed, or long `(universe, as_of_date, metric)` like `SectorEtfReturn`? Long needs no schema change per new metric but stores numerator/denominator awkwardly; wide is more readable and new metrics can be added as nullable columns via `_add_missing_columns`. I recommend wide, and it deviates from the "mirror `SectorEtfReturn`" instruction, so I am flagging it rather than deciding.
4. **Coverage gate threshold** (~97%) and behavior below it (raise vs. write with a flag).
5. **Backfill:** none, ~1 year from cache (free, survivorship-biased), or a deeper direct-fetch backfill (one-off ~30–60 s, no cache growth)?

## Not verified

- No browser/UI checks (none available). Nothing here concerns layout.
- The cache read path was measured with raw SQL rather than by calling `get_or_fetch_bars_batch` (to avoid any risk of writes to the real DB), so the real function's extra grouped freshness query is not included in the 2–3 s figure. It is one grouped MIN/MAX query and is expected to be small.
- The cause of the trend job's 52–314 s runtime spread is not established (section 2).
