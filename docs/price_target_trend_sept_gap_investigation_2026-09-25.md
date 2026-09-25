# Price-target trend vs. At-a-Glance gap (GOOGL, 2026-09) -- investigation, 2026-09-25

> **Note:** the job this doc calls `monthly_price_target_snapshot` was renamed to `nightly_price_target_snapshot` and moved to a daily cadence on 2026-09-26 -- see `docs/price_target_daily_snapshot_implementation_2026-09-26.md`. The text below is left as written and describes the job as it was at the time.

Investigation only. No production code or data was changed. The only external I/O was
read-only `sqlite` queries (`mode=ro`) against `backend/fathom.db` and 4 live, un-persisted
`GET /price-target-news` reads (GOOGL, AAPL, JPM, KO) through plain `httpx`, not `fmp_client`, so
nothing was cached or recorded. Scratch scripts were deleted.

## TL;DR

1. **There is no 2026-09 snapshot row for GOOGL (or anyone).** The trend chart's "2026-09" point
   is the 2026-08-31 row, borrowed by a nearest-date join. That row is itself a *reconstruction*
   (backfilled 2026-09-16), not an FMP consensus reading.
2. **The $323.80 vs $431.57 gap is not a stale join, unit mismatch or wrong subset. It is two
   different definitions of "average target".** I reproduced both numbers exactly from raw FMP
   data:
   - At a Glance $431.57 = mean of each analyst's latest target **among analysts who acted in the
     last ~180 days** (23 analysts) -- reproduced to the cent.
   - Trend $323.80 = mean of each analyst's latest target **across every analyst who has *ever*
     issued one since 2021-04, with no age cutoff** (47 analysts, 18 of them last updated more
     than a year ago, 11 more than two years ago, low target $118) -- reproduced to the cent.
3. **Last Month/Quarter/Year/All Time boxes are a third thing again**: FMP's own
   `/price-target-summary`, and the "analysts" count is a count of **price-target actions**, not
   distinct analysts (GOOGL All Time = 272 = the exact number of `/price-target-news` rows, from
   only 47 distinct firms).
4. **Missed run:** the 2026-09-01 run fired on time but skipped because FMP was paused; it wrote
   nothing and logged a `success` heartbeat. There is no catch-up logic. Next run 2026-10-01
   03:00 server time (UTC). That run will write a *live-consensus* row, so the line will step
   from ~$324 to ~$430 for GOOGL because the two methodologies differ (see section 3).
5. **Systemic, not GOOGL-specific**: on 126 tickers with a cached live consensus, the
   2026-08-31 trend value is below the At-a-Glance value for 72%, median gap -9.7%, and more than
   10% apart for 60%.

## 1. Architecture (who powers what)

All three pieces come from one endpoint response, `get_analyst_ratings_data`
(`backend/data/analyst_ratings_data.py:217`), rendered by
`frontend/components/ticker/AnalystRatingsTab.tsx:44` (At a Glance) and `:48` (trend card with the
recency strip). They read three different sources.

| Piece | Source | Refreshed |
|---|---|---|
| At a Glance rating / count | FMP `/grades-consensus`, cached `grades_consensus/latest` (`analyst_ratings_data.py:229-231`, banner built `:296-303`). 83 = 2+70+10+1 buy/hold/sell counts | cache, 7-day staleness |
| At a Glance target range/avg | FMP `/price-target-consensus`, cached `price_target_consensus/latest` (`:232-247`), mapped `:305-314` (`target_consensus` = `targetConsensus`) | cache, 7-day staleness (live FMP) |
| Last Month/Quarter/Year/All Time | FMP `/price-target-summary`, cached `price_target_summary/latest` (`:250-265`), mapped by `_recency_buckets` (`:181-197`). FMP endpoints: `clients/fmp_client.py:340,352` | cache, 7-day staleness |
| Trend chart line | `PriceTargetSnapshot` table (`core/models.py:1004`), read at `analyst_ratings_data.py:267-269` | monthly cron + one-time backfill |

**Recency boxes.** No per-analyst table is involved. `_recency_buckets` copies FMP's
`lastMonthAvgPriceTarget/lastMonthCount` etc. verbatim (a `0` average is turned into `None` when
count is 0, `:192-196`). `PriceTargetRecencyCard.tsx:24` prints `analyst_count` as "N analysts".
Cached GOOGL row (`fetched_at 2026-09-23 20:24:34`):

```
lastMonthCount 2   lastMonthAvgPriceTarget 467.5
lastQuarterCount 16  lastQuarterAvgPriceTarget 429.06
lastYearCount 101  lastYearAvgPriceTarget 372.86
allTimeCount 272   allTimeAvgPriceTarget 247.3
```

The counts are nested windows of *actions*: from the live `/price-target-news` pull, GOOGL has
272 rows in total (= `allTimeCount`) but only 47 distinct `analystCompany` values, and 2 rows dated
in Sept 2026 (= `lastMonthCount`). FMP's window boundaries are its own; I did not try to
reverse-engineer them.

**Trend chart line.** One point per `grades_historical` row (monthly, dated the 1st), not per
snapshot (`analyst_ratings_data.py:318-341`). Each point's value is the nearest
`PriceTargetSnapshot` by date within `SNAPSHOT_TOLERANCE_DAYS = 45` (`:37`, `_nearest_by_date`
`:98-114`), taking `snapshot.target_consensus` (`:339`). No snapshot within 45 days gives a `None`
point. The snapshot table has two writers:

- **Backfill** (one-time, run 2026-09-16, `pipeline/backfills/backfill_price_target_snapshots.py:77-107`):
  `helpers/price_target_history.py::reconstruct_monthly_snapshots`. For each month-end, take each
  analyst's most recent target as of that date (`ffill` on a pivot, `:79-91`), then
  `mean()` over every analyst with any value (`:93-105`). **No age cutoff anywhere.** It emits
  month-ends through the last full month before today, so 2026-08-31 was the last one.
- **Monthly cron** (`pipeline/monthly_price_target_snapshot.py:61-74`): appends
  one row of FMP's *live* `/price-target-consensus` values, `snapshot_date = date.today()`
  (`:121`). Append-only, no unique constraint.

## 2. GOOGL's September row

### Stored rows (`pricetargetsnapshot`, GOOGL, newest first)

```
id     snapshot_date  consensus          high   low    median  fetched_at
13827  2026-08-31     323.79574468085104 475.0  118.0  380.0   2026-09-16 10:49:30
13826  2026-07-31     323.79574468085104 475.0  118.0  380.0   2026-09-16 10:49:30
13825  2026-06-30     314.83478260869566 460.0  118.0  362.5   2026-09-16 10:49:30
13824  2026-05-31     311.46521739130435 460.0  118.0  362.5   ...
```

- **No 2026-09 row.** Across the whole table the newest `snapshot_date` is 2026-08-31 (564 tickers);
  nothing is dated 2026-09-xx.
- The rows have no forward-fill flag (the table has no such column). Every row is a backfill
  reconstruction (`fetched_at` = the 2026-09-16 backfill batch). (The earlier "~56% forward-filled" figure
  is about the reconstruction's per-analyst `ffill`/no-new-actions months, not a stored flag.)
- 07-31 and 08-31 are byte-identical because **GOOGL had zero price-target actions in Aug 2026**
  (live pull: 0 in Aug, 2 in Sep), so the carried-forward per-analyst set did not change.

### What the chart shows under "2026-09"

`grades_historical` has a `2026-09-01` row (cached `2026-09-23`). `_nearest_by_date` picks 2026-08-31
(1 day away) -> 323.7957. The "2026-09" label therefore displays the August month-end
reconstruction. The `2026-08-01` point likewise picks 2026-07-31 (1 day) over 2026-08-31 (30 days),
so it shows the same 323.80 value.

### Reconciliation (live `/price-target-news`, GOOGL, 272 rows, 2021-04-28 on)

```
recon 2026-08-31 mean/high/low/median: [323.8, 475.0, 118.0, 380.0]   <- matches stored row
distinct analysts (latest target each): 47
latest-per-analyst mean, ALL (n=47):      326.35   (as of today, incl. 2 Sept actions)
latest-per-analyst mean, acted <=365d (n=29): 417.28
latest-per-analyst mean, acted <=180d (n=23): 431.57   <- == At a Glance targetConsensus 431.57
latest-per-analyst mean, acted <=90d  (n=12): 428.42
latest-per-analyst mean, acted <=30d  (n=2):  467.50   <- == Last Month box 467.5
analysts whose latest target is older than 1y: 18; older than 2y: 11
```

So 431.57 is FMP's consensus over roughly the last six months of analyst activity (23 firms), and
323.80 includes 24 firms whose last recorded target is older than 6 months, 18 of them older than a
year. GOOGL traded near $340 recently; targets of $118-$250 issued years ago pull the mean down
about 25%. This is a **definition mismatch (no recency window in the reconstruction), not a bug in
the join, units or analyst subset**. It is also not caused by the missed September run: even a
perfectly-run cron would only have added a *different-definition* point.

(Split adjustment is *not* the cause here: `adjPriceTarget` is used
(`price_target_history.py:76`); the stored high/low 475/118 are plausible post-split values.)

## 3. Missed-run behaviour

- **Schedule:** `backend/crontab.txt:191` `0 3 1 * *` -> 03:00 on the 1st, server time (UTC).
  **Next due: 2026-10-01 03:00 UTC.**
- **What happened 2026-09-01:** `cronrunlog` id 81 `pipeline.monthly_price_target_snapshot`
  started 03:00:02.76, ended 03:00:02.79, status `success`. Job log: `Monthly price-target snapshot
  skipped: FMP paused (FMP_ENABLED=False).` (the pre-2026-09-24 global flag; the guard is
  `monthly_price_target_snapshot.py:86-103`). At that time a gated no-op was recorded as `success`.
  Since 2026-09-24 it records `skipped`.
- **No catch-up.** The script has no "last snapshot older than X" check, no backfill for missing
  months, and always writes `date.today()`. A missed 1st is a permanent gap until the next run.
  Same shape as the Market Breadth miss.
- **Health monitoring will not flag it soon.** Expected cadence is 35 days
  (`core/cron_health.py:67,87`), measured from the last row, which is a `success` on 09-01, so
  the job reads "overdue" only after ~2026-10-06, i.e. after the next run is already due.
- **Consequences on Oct 1:**
  1. The row written will be dated `2026-10-01` (run date), not a month-end like the backfill rows;
     it will match the `2026-10-01` grades point at 0 days.
  2. It stores *live* consensus (recency-windowed, 431.57-style), while every earlier row is the
     all-analysts reconstruction (323.80-style). Expect a step change in the line for most tickers
     (GOOGL ~$324 -> ~$430) that is a methodology seam, not a market move. There will be no September
     point.
  3. Re-running the job on the same day appends duplicates (no unique key).

## 4. Scope check

Compared the 2026-08-31 snapshot to the cached live `price_target_consensus` for every ticker that
has both (126 tickers; consensus is only cached for viewed tickers):

```
tickers with both: 126
median gap -9.7%   mean -5.8%
|gap| > 10%: 60%    |gap| > 20%: 33%    trend below At-a-Glance: 72%
by lastYearCount (FMP summary):   n   median gap   mean |gap|
  0-4 actions                      5       0.0%        1.7%
  5-14                             3     -13.7%       20.7%
  15-39                           24     -12.7%       24.2%
  40+                             28     -15.6%       22.6%
```

Spot checks, snapshot (08-31) vs cached consensus, and for three of them the reproduction from a
live `/price-target-news` pull:

| Ticker | Coverage (lastYearCount) | Snapshot 08-31 | Live consensus | Gap | Reproduction |
|---|---|---|---|---|---|
| GOOGL | 101 | 323.80 | 431.57 | -25.0% | all-analysts 323.80; acted<=180d 431.57 (n=23) |
| JPM | 37 | 272.31 | 373.64 | -27.1% | all 272.31 (n=29); <=180d 373.64 (n=11) |
| KO | 32 | 82.72 | 95.75 | -13.6% | all 82.72 (n=25); <=180d 95.75 (n=12) |
| ZBRA | n/a | 353.73 | 359.57 | -1.6% | not reproduced |
| ALB | n/a | 189.39 | 196.42 | -3.6% | not reproduced |
| BRK-B (2 analysts) | 2 | 553.67 | 604 | n/a | thin coverage, single stale/current target |
| HSBC, CNSWF (0-1 analysts) | 0 | 52.0 / 4800 | 52 / 4800 | 0% | identical: no history to dilute |

The pattern is exactly the one predicted by the mechanism: the more analysts with old targets, the
larger the gap; a ticker with a single analyst shows none. Live 180-day windowed mean reproduced
FMP's consensus to the cent on all three fully-reproduced tickers (GOOGL, JPM, KO), which is strong
evidence FMP's `/price-target-consensus` is a ~6-month-activity mean.

**Second, separate seam (AAPL, MSFT).** These two were seeded by a manual test run of the cron
on 2026-07-27 (ids 1-2, live consensus 342.11 / 549.08), so the backfill's `before` bound stopped at
06-30. Their newest rows are: 06-30 (reconstruction 271.19 / 504.78) then 07-27 (live). The chart's
Aug/Sep points therefore borrow the 07-27 *live* row (within 45 days), producing a visible jump
(AAPL 271 -> 342) that mixes both definitions in one line -- a preview of what every ticker will do
on Oct 1. The live AAPL reconstruction as of 08-31 would have been 285.23 against consensus 342.13.

## Caveats

- Only 126 of ~564 tickers have a cached live consensus, so the scope statistics are a viewed-ticker
  sample, not the universe.
- The 180-day window is inferred: it reproduces GOOGL/JPM/KO consensus exactly, but FMP does not
  document it, and the 90d/365d windows do not match. Not tested on other tickers.
- FMP's recency-box windows (last month/quarter/year) were not reverse-engineered.
- No browser verification (per convention); the chart labels above are derived from the endpoint
  logic and stored data, not seen on screen.

## Not investigated / decision points (no fixes made)

- Reconstruction has no recency cutoff, so the history line and live consensus are different series.
- Cron has no catch-up and writes the run date, not a month-end, and stores a differently-defined value.
- The recency boxes label action counts as "analysts".
- Health check will not surface a skipped-but-`success` month.
