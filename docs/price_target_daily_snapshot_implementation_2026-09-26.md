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

**Job** (`pipeline/nightly_price_target_snapshot.py`; renamed afterwards, see addendum)
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
3. To see the split before the cron runs, run `uv run python -m pipeline.nightly_price_target_snapshot --tickers GOOGL,AAPL`
   (writes today's live row for those two), reload.
4. GOOGL, AAPL: chart shows a dashed segment (history) and a solid dotted segment (live) with a visible break, and the
   note under the chart. Hover shows the correct label per segment.
5. Toggle "Overlay stock price": both target segments plus the price line, legend lists Target/Stock Price, note still shown.
6. A thin-coverage ticker with few history points: no layout break; with only one methodology, no note and the original chart.
7. A ticker with no snapshots: still "hasn't accumulated yet" message (now says "daily").
8. Next morning: `CronRunLog` for `pipeline.nightly_price_target_snapshot` is `success` ("N written, M failed"), run finished
   before 03:10; Settings > Status lists it as daily, 2:10 AM.

## Addendum (2026-09-25 server date): rename, index confirmation, first full run

**Rename** `monthly_price_target_snapshot` -> `nightly_price_target_snapshot`: `pipeline/` module, its test file
(`tests/test_nightly_price_target_snapshot.py`), the `cron_health.py` entries (`CRON_JOB_NAMES`, cadence, `JOB_METADATA`),
`crontab.txt`, the Settings > Status feature label in `core/data_groups.py` ("Nightly price-target snapshot"), log file names
(`nightly_price_target_snapshot.log` / `_cron.log`), `OPS_RUNBOOK.md`, CLAUDE.md, and code comments/docstrings.
Historical `CronRunLog` rows and the old `monthly_*` log files are untouched. Older dated investigation docs
(`docs/cron_audit_2026-09.md`, the 09-22/09-25/09-26 investigations, `fmp_migration_...`) still say `monthly_...`
on purpose: they describe the code as it was. Because the name changed, the Status page shows this job as having no
history until its first run under the new name (now recorded, below).

**Index.** `uq_pricetargetsnapshot_ticker_date` was already present in the real DB: the tagging script calls `init_db()`
during the earlier migration, which creates it. Re-confirmed via `sqlite_master` (`CREATE UNIQUE INDEX ... ("ticker", "snapshot_date")`).
No restart was needed; `init_db()` was invoked directly (idempotent).

**First full run** (07:12-07:21 UTC, 8.6 min, 516 FMP calls; `CronRunLog`: `success`, "514 written, 4 failed"):
- Universe is **518** (S&P 500 + Dow, `load_universe_tickers`), not the 566 estimated in the feasibility doc (566 was the distinct
  ticker count in the backfilled table, which had a wider universe). Tomorrow's cost estimate falls to ~518 calls.
- Written: 514 rows, all `live_consensus`, none with null values.
- Failed: BF-B, ERIE, L, NWS: FMP returned an empty consensus for them (no data, not an error).
- 516 calls for 518 tickers: some tickers were served from a still-fresh (<1 day) `price_target_consensus` cache row (e.g. AAPL).
- Duplicate `(ticker, snapshot_date)` pairs: 0.
- Pacing was ~0.27 s/request as configured; the run took longer than the 2.6 min estimate because per-call latency (~1 s) dominates.
  It finishes well before 03:10 either way (02:10 + ~9 min).

**Spot check** (snapshot vs the `price_target_consensus` cache row At-a-Glance reads): identical.
GOOGL 431.57 / high 485 / low 350 / median 425; AAPL 342.13 / 400 / 245 / 362. (GOOGL's legacy 2026-08-31 point was ~323.80, so the
seam step is ~+$108, as predicted.)

**Note:** the server date is 2026-09-25, so "today's" rows are dated 2026-09-25, not 09-27.

**Crontab** reinstalled; `crontab -l` is byte-identical to `backend/crontab.txt`. First scheduled run: 02:10 UTC tomorrow.

Manual UI checklist: the checklist above applies as-is, and step 3 (running the job for GOOGL/AAPL) is no longer needed since live rows exist.
The app is still the old production build until restarted (`./bin/stop.sh && ./bin/start.sh`), so the split chart and methodology field won't show until then.

## Addendum 2: chart split reverted

The dashed/solid methodology split and its caption were removed from `PriceTargetTrendChart.tsx` (restored to its pre-`3913b19`
single continuous area chart, plus the "daily" wording in the empty-state text). This was a deliberate decision: the legacy/live
jump now renders as an undifferentiated move. `methodology` remains in the column, API and TS type but the chart no longer reads it.
The "Frontend" bullet above and checklist items 3-5 no longer apply.
