# Market Breadth "Live →" marker investigation (2026-09-27)

Diagnosis only. No functional code changed.

## Conclusion (root cause: (c), something else)

The premise that the job is stuck is wrong. **The nightly job has run and saved a row every night, and the newest
row (as_of 2026-09-25, the last completed session) is current.** The "Live →" marker is not a "latest data" marker
at all. It marks the **first non-backfilled session** in the series
(`frontend/lib/marketBreadth.ts::firstLiveIndex` = `series.findIndex(p => !p.is_backfilled)`), which is the
boundary between backfilled history and live history. That boundary is **2026-09-21**, so it sits several days
before today. It will stay there permanently, since the boundary is by definition the first live row and never moves
forward.

Why it is 09-21 and not 09-23 (the first live row after the coverage failures): the boundary is the *earliest*
`is_backfilled = 0` row, and 09-21 was written live by the 09-22 03:35 run. Its own row was never replaced.
Hypotheses (a) silent skips and (b) API not surfacing new rows are both ruled out (below).

## 1. Job and crontab

- Script: `backend/pipeline/nightly_market_breadth.py` (compute/gate in `backend/data/market_breadth_data.py`).
- Crontab (`crontab.txt` and installed `crontab -l`, both identical):
  `35 3 * * * ... python -m pipeline.nightly_market_breadth >> logs/nightly_market_breadth_cron.log 2>&1`
  (server TZ is UTC; "now" during the investigation was Sat 2026-09-26 22:44 UTC).

## 2. Last 10 `MarketBreadthSnapshot` rows, universe = "sp500"

The table has no `coverage_pct` column. The coverage diagnostics are `constituents`, `stale_excluded` and the
`*_eligible` counts. Coverage is `(constituents - stale_excluded) / constituents`.

| as_of_date | computed_at (UTC) | constituents | stale_excluded | sma20/50/200/hl eligible | is_backfilled |
|---|---|---|---|---|---|
| 2026-09-25 | 2026-09-26 03:35:15 | 503 | 0 | 503/503/501/500 | 0 |
| 2026-09-24 | 2026-09-25 03:35:12 | 503 | 0 | 503/503/501/500 | 0 |
| 2026-09-23 | 2026-09-24 03:35:14 | 503 | 0 | 503/503/501/500 | 0 |
| 2026-09-22 | 2026-09-24 16:33:36 | 503 | 0 | 503/503/501/500 | **1** |
| 2026-09-21 | 2026-09-22 03:35:09 | 503 | 1 | 502/502/500/499 | 0 |
| 2026-09-18 | 2026-09-24 16:33:36 | 503 | 0 | 503/503/501/500 | 1 |
| 2026-09-17 | 2026-09-24 16:33:36 | 503 | 0 | 503/503/501/500 | 1 |
| 2026-09-16 | 2026-09-24 16:33:36 | 503 | 0 | 503/503/501/500 | 1 |
| 2026-09-15 | 2026-09-24 16:33:36 | 503 | 0 | 503/503/501/500 | 1 |
| 2026-09-14 | 2026-09-24 16:33:36 | 503 | 0 | 503/503/501/500 | 1 |

Table totals: 10,812 rows, 2022-09-26 .. 2026-09-25, 10,775 backfilled. Earliest `is_backfilled = 0` row: **2026-09-21**.
Every session through the last completed one (Fri 2026-09-25) has a row. (09-19/09-20 were a weekend.)

## 3. Skip vs success, and does Status mislead?

- The job has no silent-skip path for a coverage shortfall. Below the 97% gate it **raises**
  `InsufficientCoverageError`, which `cron_heartbeat` records as `failure`. The only real `skipped` status is the
  `daily_prices` group-off case, which has not occurred.
- `CronRunLog` for this job (all 15 rows are visible in the log listing; totals: 5 success, 4 failure, 1 running):

| run (UTC) | status | note |
|---|---|---|
| 09-22 03:35 | success | wrote 09-21 (the live boundary row) |
| 09-23 03:35, 03:55, 05:37, 09:23 | **failure** x4 | `InsufficientCoverageError`: only 6-7/503 constituents had a bar on 09-22 |
| 09-23 15:44 | **running** (never finished) | orphan row, `finished_at` NULL |
| 09-23 20:06 | success | |
| 09-24 03:35 | success | wrote 09-23 |
| 09-25 03:35 | success | wrote 09-24 |
| 09-26 03:35 | success | wrote 09-25, 503/503 |

- So the Status page is not misleadingly green about skips: there were no skips. It did show failures on 09-23, and
  those were real (the trend job's cache had not yet caught up to the 09-22 session, during the FMP cutover). They
  self-healed by 09-23 20:06. The marker date 09-21 predates those failures, which is why Status shows nothing
  "since" it.
- Side finding, not the cause: a `running` row (id 265, started 2026-09-23 15:44) has no `finished_at`. Not
  investigated further whether the health view treats it as stuck.

## 4. Logs (`backend/logs/nightly_market_breadth.log` and `_cron.log`)

Nightly at 03:35 for 09-24, 09-25 and 09-26, each "Nightly market breadth complete ... Constituents: 503. With bar:
503. Excluded: 0. Sectors: 11/11 passed" (09-26: "As of: 2026-09-25", duration 13.0s, %>SMA20 29.2 / SMA50 25.8 /
SMA200 45.7, net new highs -30). Every run inserted a row.

Why 09-22 is backfilled: on 09-24 16:33 `backfill_market_breadth --rebuild` ran after the FMP daily-bar cutover. It
deletes and re-inserts `is_backfilled` rows in its date range. Because 09-22's live run had failed (see above), the
09-22 date only existed as a rebuilt backfill row. That is why the series reads live(09-21), backfilled(09-22),
live(09-23...).

## 5. API and frontend

- `GET /api/market-breadth` -> `data/market_breadth_data.py::get_market_breadth` selects **all** rows for the
  universe ordered by `as_of_date`, with no cap, pagination or caching. `latest` and `as_of_date` come from the last
  row (09-25). Newer rows are not hidden.
- The marker: `MarketBreadthCharts.tsx` computes `liveAt = firstLiveIndex(series)`, and if `liveAt > 0` draws a
  dashed `ReferenceLine` at `series[liveAt].as_of_date` labelled "Live →". That is the first live row (09-21), not
  `max(as_of_date)`.
- The same helper drives the sector view (`BreadthSectorView.tsx`). I did not query the sector universes' boundary
  dates.

## Decision points for the follow-up (no fix made)

1. Relabel or reposition: the marker means "live history begins here". Options are a clearer label
   ("Recorded live from ..."), or additionally showing the latest-session date somewhere (the stat tiles already show
   the as-of).
2. If the intent is a contiguous live boundary, treat the 09-22 rebuilt row as a gap (e.g. use the first live row
   after the last backfilled row, which would give 09-23), or flip 09-22's flag semantics. That is a judgment call
   since the 09-22 row is genuinely survivorship-biased backfill.
3. Separately, look at the orphaned `running` CronRunLog row.
