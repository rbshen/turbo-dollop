# Price-target snapshot: monthly -> daily feasibility -- investigation, 2026-09-26

Investigation only. No production code or data changed. Only read-only sqlite queries
(`mode=ro`) against `backend/fathom.db` and reads of `backend/logs/*`. Zero FMP calls made.
Follows `docs/price_target_trend_sept_gap_investigation_2026-09-25.md` (paths/schema not re-traced).
All DB numbers are as of 2026-09-25 ~evening server time.

## TL;DR

1. **`analyst_ratings` is NOT refreshed daily, and is not part of the nightly cycle at all.** The
   2:00 `nightly_fundamentals_fetch` never touches it (`_refresh_one_ticker`,
   `pipeline/nightly_fundamentals_fetch.py:137-158`, calls step1/2/4/5, segmentation, summary,
   score only). The group refreshes **lazily, on a view, with a flat 7-day staleness**. So "reuse
   what the daily refresh already pulled" has nothing to reuse: there is no daily analyst pull.
2. **Only 133 of the 566 snapshot tickers (23.5%) have a cached `price_target_consensus` row, and
   only 48 (8.5%) are fresher than 7 days.** Snapshotting "from cache" daily would cover a
   viewed-ticker minority and would write the same value up to 7 days running.
3. **A real daily snapshot needs ~566 additional FMP calls/day** (1 x `/price-target-consensus` per
   snapshot ticker; 591 if the full tracked universe), against a measured current consensus
   call rate of ~8/day. That is ~2.6 min at the app's existing 220 req/min pacing.
4. **Headroom: the repo enforces/documents only a per-minute limit, no daily quota.** Plan is
   `Ultimate` (3,000 req/min per `clients/daily_bar_sources.py:430`), but that value is a
   user-editable setting, not verified against FMP. I can't state "% of daily quota" because no
   daily quota is recorded anywhere; see section 3 for the per-minute margin and the daily-volume
   comparison I can prove.
5. **Relabeling legacy rows is cheap**: the 32,764 backfill rows are already separable by
   `fetched_at` (all `2026-09-16`), and a nullable `methodology` column is a one-line additive
   migration. Frontend segmenting is the bulk of the work (~1 day total). Re-deriving the legacy
   rows on the live methodology instead would cost ~1,294 FMP calls (measured) and rests on an
   *inferred* 180-day window.

## 1. Current `analyst_ratings` refresh cadence

`analyst_ratings` = five FMP endpoints, each cached in `FundamentalsCache` under key `<type>/latest`
(`core/data_groups.py:155-159` endpoint map, `:228-232` statement-type map). Who fetches what:

| Cache key / endpoint | Fetched by | Trigger | Staleness |
|---|---|---|---|
| `grades_consensus` `/grades-consensus` | `data/analyst_ratings_data.py:226-231` (Analyst Ratings tab) **and** `data/watchlist_data.py:59-86` (Watchlist rating column) | a page load | `settings.cache_staleness_days` = 7 |
| `price_target_consensus` `/price-target-consensus` | `analyst_ratings_data.py:232-243` (tab only) | tab view | 7 |
| `grades_historical` `/grades-historical` | `analyst_ratings_data.py:244-249` (tab only) | tab view | 7 |
| `price_target_summary` `/price-target-summary` | `analyst_ratings_data.py:250-261` (tab only) | tab view | 7 |
| `price_target_news` `/price-target-news` | **never cached**; live only in the one-time backfill | -- | -- |

- No cron job touches the first four. The only FMP-fetching scheduled job in the group is
  `monthly_price_target_snapshot` (`crontab.txt:191`, 03:00 on the 1st). The `analyst_ratings`
  data-group is toggled by that job's skip guard (`monthly_price_target_snapshot.py:86`).
- Staleness is a flat window, **not earnings-date-aware** (`get_or_fetch(..., staleness_days,
  cache_only)`; the earnings-aware variant `get_or_fetch_earnings_aware` is not used here).
- The "At a Glance" card = `grades_consensus` (rating/count) + `price_target_consensus`
  (target avg/high/low) + `quote` (`analyst_ratings_data.py:296-314`).

**Real cache state** (`fundamentalscache`, 2026-09-25):

| statement_type | tickers cached | fetched in last 24h | fetched in last 7d |
|---|---|---|---|
| price_target_consensus | 133 | 2 | 48 |
| grades_historical | 133 | 2 | 48 |
| price_target_summary | 66 | 2 | 48 |
| grades_consensus | 577 | 0 | 547 |
| price_target_news | 0 | -- | -- |

`price_target_consensus` fetches per day, last 10 days: 09-14 1, 09-15 2, 09-16 12, 09-17 2, 09-18 18,
09-19 5, 09-21 2, 09-22 5, 09-23 20, 09-25 2 -- **mean ~7/day, i.e. viewed tickers only.**

`grades_consensus` is broader (577) because the Watchlist column fetches it (`watchlist_data.py:59`).
Unexplained: 538 of those rows have `fetched_at` on 2026-09-22 between 03:19 and 21:35 UTC. The only
code callers are the tab and the Watchlist, and the watchlist has 132 tickers, so something loaded
~400 non-watchlist tickers that day. I did not chase it (out of scope, no bearing on the answer).

## 2. Overlap between the two jobs

- The monthly job calls `fmp_client.get_price_target_consensus(ticker)` **directly, bypassing the
  cache** (`monthly_price_target_snapshot.py:62`), and reads only `targetConsensus/High/Low/Median`
  (`:66-69`). The tab calls the **same endpoint, same payload**, via `get_or_fetch`
  (`analyst_ratings_data.py:232-243`). So they are the same call made through two paths.
- **Redundancy, quantified (one monthly run over the 566 snapshot tickers):**
  - 133 / 566 = **23.5%** already have a cached consensus row; 48 / 566 = **8.5%** are within the 7-day
    window and could have been reused with **0** calls.
  - The other 433 / 566 = **76.5%** have no cached consensus at all, so nothing to reuse.
  - Because the monthly job never writes the cache, its 566 calls do not warm the tab either.
- **The monthly job did not make the calls in September** (skipped, `cronrunlog` id 81), and it has
  only ever fetched live for 2 tickers (manual test 2026-07-27, ids 1-2). So the redundancy above is
  the *designed* redundancy, not a measured one.
- Could it reuse? Yes but only cheaply if the job itself populates the cache: switch its call to
  `get_or_fetch` (1-day staleness) and read the snapshot fields off the cached blob. Then tab views
  and the snapshot share one row, and the tab's At-a-Glance target would also be <=1 day old instead
  of <=7. That trades nothing away, but it is **not** "reuse existing daily data": the data isn't
  there today.

## 3. Cost of going daily

**Universe (real):** `pricetargetsnapshot` has 566 distinct tickers (all in `TickerScore`, 591 rows,
`profile` cache 591 tickers). `IndexConstituent`: sp500 503, dow 30, nasdaq 102. Watchlist 132 tickers.

**Additional FMP calls/day**

| Design | Calls/day | Notes |
|---|---|---|
| Snapshot from existing cache only | **0** | covers 133 tickers; 48 fresh; row value repeats up to 6 of 7 days (7-day staleness), so it is a stale copy, not a daily reading |
| Daily job via `get_or_fetch`, **1-day** staleness, snapshot universe | **~566** minus ~7 already made by views = **~559 net** | 1 call/ticker (`/price-target-consensus`); the other 3 endpoints aren't needed for the snapshot |
| Same, full tracked universe | **~591** (~584 net) | includes 25 tracked tickers with no snapshot history |
| Daily job, 7-day staleness | **~81/day amortized** (566/7) | still writes 566 rows/day; only ~1/7 carry a new value |

Answer to "how many additional calls per day": **566** (snapshot universe, 1 endpoint each). That is
the real number; the 133-ticker cache does not reduce it, because a daily reading requires a
same-day fetch for every ticker.

**Per-minute limit and headroom**

- Plan in DB: `datagroupglobal.fmp_plan = 'Ultimate'` (seeded default, user-editable, **not verified
  against FMP**). Code table: Starter 300 / Premium 750 / **Ultimate 3,000** req/min
  (`clients/daily_bar_sources.py:430`); the daily-bar path self-limits to 50% of that.
- `analyst_ratings` is tier-tagged **Starter** in the group config (`datagroupsetting`, verified=1),
  so it's on plan under any tier.
- Existing paced jobs run at 220 req/min (`nightly_fundamentals_fetch.py:75`,
  `monthly_price_target_snapshot.py:58`), from an empirical 300-600/min observation on an earlier
  plan. At that pacing 566 calls = **2.6 min**; at the Ultimate 50% self-limit (1,500/min) it is
  ~23 s. Peak minute = 220 of 3,000 = **7.3% of the per-minute cap** (14.7% of the 50% budget).
- **Daily quota: none is documented or enforced in the repo.** I therefore can't report "X% of the
  daily quota used"; I would rather say so than invent one. What can be proved is daily *volume*:

| Existing daily FMP volume (real, from logs) | Calls |
|---|---|
| Nightly fundamentals fetch, last 10 nights (09-16..09-25) | 8, 0, 4, 2, 4, 0, 53, **2,655**, 174, 13 (median 6) |
| Nightly daily bars (`nightly_trend_calculation`, CLAUDE.md P2/P3) | ~598/night (592 US + 6 HK; Sunday full resync is also one call per ticker) |
| Views/on-demand (quote, tab loads) | not measured; no request-count table exists |

  So steady-state is roughly **600-800 calls/day**, dominated by daily bars, with occasional
  fundamentals staleness-cycle spikes (2,655 on 09-23; 3,789 on 09-15). Adding ~566 is about
  **+70-95% on a steady day** but a smaller fraction of a spike day. The limiting resource is
  therefore the per-minute cap (comfortable), not a daily cap that we cannot observe.
- Scheduling: nightly fundamentals finishes ~02:01 on a warm day (0.7-1.6 min; 45-65 min on spike
  days), trend job 03:10, LZ 03:25, heatmap 03:30, breadth 03:35, Warren 03:40, score recompute
  03:50, backup 03:55. A daily snapshot would fit in the 02:10-03:05 gap on a normal day, but a
  spike day running 45-65 min from 02:00 would overlap it (same paced `fmp_client` is per-process,
  so overlap doubles instantaneous rate: 2 x 220 = 440/min, still 14.7% of 3,000).

**Side costs (not FMP):** the table is append-only with no unique key
(`core/models.py:1004`, docstring); daily writes add 566 rows/day = ~206k/yr on top of 32,766 today
(size not measured; rows are 5 numeric columns + id/ticker index). A daily job must not append
duplicates on rerun, and `_add_missing_columns` (`core/db.py:39-56`) is add-column-only, so the
`(ticker, snapshot_date)` uniqueness would need an explicit `CREATE UNIQUE INDEX` or a
check-then-insert (the current job's re-run-appends-duplicates behavior would get worse daily).
Chart read is unaffected: `_nearest_by_date` (`analyst_ratings_data.py:98-114`) already picks the
nearest row per monthly `grades_historical` point.

## 4. Methodology cutover

**What is in the table now (measured):** 32,766 rows, ids 1-32,766. 32,764 have
`fetched_at` on 2026-09-16 (the all-analysts backfill reconstruction, month-end dated,
2021-04-30..2026-08-31, 566 tickers). The other 2 are AAPL/MSFT live-consensus rows dated
2026-07-27 (ids 1-2, manual test). There is **no column** marking methodology; the
reconstruction has no recency cutoff (`helpers/price_target_history.py:36`,
`backfills/backfill_price_target_snapshots.py:79-105`), live rows are FMP's own consensus
(reproduced as a ~180-day-activity mean on GOOGL/JPM/KO only).

Options, cheapest first:

| | Approach | Effort | Notes |
|---|---|---|---|
| A | **Nullable `methodology` column** on `PriceTargetSnapshot` (`_add_missing_columns` adds it automatically on startup; NULL for existing rows). One-time `UPDATE` sets the 32,764 `fetched_at = 2026-09-16` rows to `legacy_all_analysts`; the daily job writes `live_consensus`. Expose per point on `RatingHistoryPoint` (`core/schemas.py:1943-1963`, alongside `avg_price_target`) and have `PriceTargetTrendChart.tsx` split into two series/dash styles with a legend note. | ~1 day: model 1 line, job 1 line, one-off UPDATE (idempotent SQL), schema field + `analyst_ratings_data.py:339` pass-through, chart segmenting + test. | Recommended. Explicit, survives future backfills, correctly labels the AAPL/MSFT 07-27 rows as live. Needs a decision on whether the two series join with a gap or a connector at the seam. |
| B | **Derive at read time**, no schema change: legacy iff `snapshot_date <= 2026-08-31` and not one of the 07-27 rows, via a hard-coded cutoff constant. | ~2-3 hours | Brittle: a future re-backfill or restatement can't be labeled; AAPL/MSFT need a special case. |
| C | **Eliminate the seam instead of flagging it**: rebuild the legacy rows with the ~180-day recency rule and re-run the backfill. | Medium: change reconstruction in `helpers/price_target_history.py`, re-run backfill. **Measured cost of the last run: 1,294 FMP calls, 22.1 min** (`logs/backfill_price_target_snapshots.log`, 2026-09-16 11:02) for 580 tickers, 32,764 rows. | Removes the artificial jump, but the 180-day window is **inferred** (matched to the cent on 3 tickers only), not documented by FMP, and it rewrites 32k historical rows. Could be paired with A (label rebuilt rows `reconstruction_180d`). |
| D | **Chart-only annotation**: a vertical "methodology changed" marker at the first `live_consensus` date, no per-point data. | ~2-3 hours | Depends on A or B to know the date; doesn't help API consumers. |

Recommendation for the *decision*, not implemented: A (optionally + D) fixes the silent
discontinuity at low cost regardless of cadence; C is the only option that makes the line
comparable, and is worth doing only if the 180-day rule is first confirmed on more tickers.
Note this needs to land **before** the first live daily row (or Oct 1's monthly one), otherwise the
first live rows are indistinguishable from legacy except via option B's cutoff.

## Caveats

- `fmp_plan = 'Ultimate'` is the app's own editable setting, not confirmed with FMP; the
  per-minute figures and headroom follow it. If the real plan is lower, 220 req/min (existing job
  pacing) is still safe by precedent, and 566 calls would just take 2.6 min.
- No daily FMP quota is recorded anywhere in the repo, and no request-count table exists, so I
  cannot give an all-jobs daily total or "% of daily quota" -- only per-job counts from logs.
- 566 (snapshot tickers) is the real count today; it will drift with the universe and watchlists.
- Consensus fetch/cache counts are a snapshot of a live DB and move daily.
- The 180-day-window claim comes from the previous investigation (3 tickers), not re-tested here.
- No browser verification; UI effort estimates are from reading the components, not from prototyping.
