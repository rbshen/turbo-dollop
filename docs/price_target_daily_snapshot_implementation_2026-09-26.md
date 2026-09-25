# Price-target snapshot: monthly -> daily, with methodology labeling (2026-09-26)

Implements Option A of `price_target_daily_refresh_feasibility_2026-09-26.md`. Context:
`price_target_trend_sept_gap_investigation_2026-09-25.md`.

## What changed

**Schema** (`core/models.py`, `core/db.py`)
- `PriceTargetSnapshot.methodology` (nullable str): `legacy_all_analysts` | `live_consensus`.
  Added to existing DBs by `_add_missing_columns` on startup.
- Unique index `uq_pricetargetsnapshot_ticker_date` on `(ticker, snapshot_date)`. Declared on the model
  (fresh DBs/tests) and created idempotently on existing DBs by the new `db._ensure_unique_indexes()`
  (`CREATE UNIQUE INDEX IF NOT EXISTS`), called from `init_db()`, since `_add_missing_columns` is
  add-column-only.
- Migration: `pipeline/backfills/tag_price_target_methodology.py` (idempotent SQL; only touches rows with
  `methodology IS NULL`): `fetched_at` date 2026-09-16 -> `legacy_all_analysts`; 2026-07-27 -> `live_consensus`.

**Job** (`pipeline/monthly_price_target_snapshot.py`; file/job name deliberately unchanged)
- Fetches via `get_or_fetch("price_target_consensus", "latest", staleness 1 day)`, the same cache row the
  Analyst Ratings tab uses, so tab views and the job share one fetch (and the tab's At-a-Glance target is now
  at most 1 day old after a nightly run).
- Every row is tagged `live_consensus`. Re-run for the same `(ticker, snapshot_date)` updates the row; earlier days are untouched.
  An empty/absent FMP response raises per ticker (counted as a failure) instead of writing an all-null row.
- Pacing unchanged (220 req/min). Docstring/log messages say "daily".
- Crontab: `10 2 * * *` (was `0 3 1 * *`). `core/cron_health.py`: cadence 36 h (was 35 days), `JOB_METADATA`
  "daily", "2:10 AM". `test_cron_wiring` still passes (schedule/metadata agree).
- **Skip/failure status.** The `analyst_ratings` skip guard already recorded `skipped` since 2026-09-24. Note it is
  still required: `get_or_fetch` alone degrades to cache-only when the group is off, which would have written stale
  values under today's date. The remaining silent-success case was a run where *every* ticker failed (FMP down, key
  revoked); it logged `success`. New `record_outcome()` maps: gated -> `skipped`; all tickers failed -> raises (`failure`);
  else `success` with message "N written, M failed".

**API**: `RatingHistoryPoint.methodology`, taken from the snapshot matched to each history point.

**Frontend** (`PriceTargetTrendChart.tsx`): when history has both methodologies, the target line is drawn as two
series in the same hue: dashed = legacy, solid with dots = live, not joined, plus a plain-language note beneath.
With only one methodology the original area chart is unchanged. The price-overlay view gets the same split.

## Migration results (real `fathom.db`, run 2026-09-26)

| | rows |
|---|---|
| `legacy_all_analysts` set | 32,764 |
| `live_consensus` set | 2 (AAPL, MSFT, 2026-07-27) |
| Second run (idempotency) | 0 / 0 |
| Duplicate `(ticker, snapshot_date)` beforehand | 0, so the unique index built cleanly |

The unique index and `methodology` column now exist in the live DB. The API/frontend are production builds:
`./bin/stop.sh && ./bin/start.sh` to pick up the code, then `crontab crontab.txt` from `backend/` to activate
the 02:10 schedule (editing the file alone changes nothing; **not done here**).

## Tests
Backend: 2,142 passed (full suite). New: same-day re-run updates rather than duplicates; earlier days preserved; job
and tab share the cache row (no second FMP call); unique index rejects duplicates; `init_db` adds column + index to a
pre-existing table, idempotently; migration tags legacy/live correctly, never overwrites, is idempotent;
`CronRunLog` status for gated (`skipped`), all-failed (`failure`) and normal (`success`) runs; API passes `methodology` through.
Frontend: vitest 425 passed (3 new for the split, note, and overlay); tsc and eslint clean.

## Things to know
- Until the first live rows exist for a ticker, its chart is legacy-only and looks as before. The first daily run after the
  crontab reinstall creates the seam. History points are matched to the nearest snapshot within the existing tolerance,
  so a monthly grades point can pick a daily live row.
- Rows accumulate at ~566/day (~206k/yr).
- Not done (out of scope): re-deriving legacy rows (Option C); the 2026-09-22 `grades_consensus` fetch.
- `crontab.txt` comment for the Momentum job no longer claims to be staggered "after" the price-target job.

## Manual UI checklist (no browser verification was done)
1. Restart the app (`./bin/stop.sh && ./bin/start.sh`).
2. Before any live rows exist: open Analyst Ratings for GOOGL: the target chart looks as before (single area chart, no note).
3. To see the split before the cron runs, run `uv run python -m pipeline.monthly_price_target_snapshot --tickers GOOGL,AAPL`
   (writes today's live row for those two), reload.
4. GOOGL, AAPL: chart shows a dashed segment (history) and a solid dotted segment (live) with a visible break, and the
   note under the chart. Hover shows the correct label per segment.
5. Toggle "Overlay stock price": both target segments plus the price line, legend lists Target/Stock Price, note still shown.
6. A thin-coverage ticker with few history points: no layout break; with only one methodology, no note and the original chart.
7. A ticker with no snapshots: still "hasn't accumulated yet" message (now says "daily").
8. Next morning: `CronRunLog` for `pipeline.monthly_price_target_snapshot` is `success` ("N written, M failed"), run finished
   before 03:10; Settings > Status lists it as daily, 2:10 AM.
