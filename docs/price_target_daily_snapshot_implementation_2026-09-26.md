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

## Addendum 3 (2026-09-25 server date): failed fetches, full US universe, doc sweep, Sept 22 spike

### 1. The four failed fetches (BF-B, ERIE, L, NWS)

Live, un-cached `fmp_client.get` probes (no DB writes).

- **BF-B was a symbol-format bug, now fixed.** `/price-target-consensus`, `/price-target-summary` and `/price-target-news` return `[]` for `BF-B`
  and real data for `BF.B` (consensus 55, high 67, low 48, median 50; 4 news rows). The other endpoints are the reverse: `/profile` and
  `/grades-consensus` answer to `BF-B` (36 analyst grades) and `BF.B` gives a thinner row (4). Other forms (`BF/B`, `BF_B`, `BFB`) return nothing; `BF-A` only exists hyphenated.
  **BRK-B answers under both spellings with different data** (604 hyphen vs 575 dot), so a blanket hyphen-to-dot replace would silently change it.
  Existing dot-mapping in the repo (`core.tickers.MASSIVE_TICKER_ALIASES`) is for Massive and also covers BRK-B, so it was not reused.
  **Fix:** `clients/fmp_client.py::PRICE_TARGET_SYMBOL_OVERRIDES = {"BF-B": "BF.B"}`, applied to the three price-target methods only. The cache key and
  stored ticker stay `BF-B`. Live check through the real job: BF-B row written (target 55 / 67 / 48 / 50, `live_consensus`). This also fixes
  the Analyst Ratings tab's target for BF-B, which reads the same client method.
  One-off data fix: the first run had cached an empty `[]` for BF-B (`price_target_consensus`/`latest`, 1-day staleness), which would have made tomorrow's
  02:10 run fail too (about 19 h old, still "fresh"). That one row was deleted and the ticker re-fetched.
- **ERIE, L, NWS are genuinely uncovered for price targets** (harmless recurring no-ops): all three return `[]` from `/price-target-consensus`,
  `/price-target-summary` and `/price-target-news`. Grade coverage differs: **ERIE** has none at all (`/grades-consensus` `[]`; `/profile` fine),
  **L** has 4 grades (2 buy / 2 hold) and **NWS** 33 (21 buy / 9 hold / 3 sell) but neither has any price target. NWS's sibling NWSA does have targets (consensus 32.2),
  so it is FMP publishing targets on one share class only, not a symbol problem.

### 2. Full US universe

`pipeline/nightly_price_target_snapshot.py::load_us_price_target_universe`: `load_full_tracked_universe` (index + ever-viewed + scored + watchlisted)
filtered with `core.tickers.is_us_listed` using the cached profile exchange (`daily_bar_sources._profile_exchanges`) -- the same rule that routes daily
bars: listing exchange, not domicile (TSM/BABA/HSBC/NVO count). Also excludes `TickerScore.delisted_at` tickers (AVB, EA, EQR, TWTR, WBA), which the other nightly jobs already skip and which would only fail nightly. The `--limit` CLI path uses the same selector.

| | count |
|---|---|
| Full tracked universe | 591 |
| Non-US listing (HKSE: 0005, 0728, 0857, 0883, 0941, 3988) | 6, excluded |
| Delisted-flagged (all US-listed) | 5, excluded |
| **New job universe** | **580** (was 518: all 518 retained, **+62 new**) |
| Exchange mix | NYSE 379, NASDAQ 199, OTC 3, AMEX 3, CBOE 1 |

The 62 new tickers (measured by running them live, plus BF-B): 62 calls, 61 s (about 1 call/s, latency-bound). 5 of the 62 returned no consensus:
**SPY, TECL** (ETFs), **PARA** (FMP's PARA is Banzai, no coverage), **EVVTY, SINGY** (OTC ADRs). 57 written, 0 duplicates; rows for 2026-09-25 now 571 (later joined by BF-B's re-fetch).
Steady state expectation: 580 tickers, about 8 harmless failures (the 5 above + ERIE, L, NWS), so `record_outcome` still reads `success` ("572 written, 8 failed").
**Additional FMP calls/day: +62** (516 -> about 578; a ticker with a still-fresh cache row costs none).

**Rate-limit headroom.** Pacing is unchanged at 220 req/min, below the Starter-tier documented 300 req/min (`FMP_PLAN_REQUESTS_PER_MIN`; Premium 750, Ultimate 3000), so the ceiling never moves with ticker count. The real rate is latency-bound at about 60 req/min (61 calls in 61 s just now; 516 calls in 8.6 min on the first full run).
Extrapolated full run: 580 calls at about 1 s = **about 10 min**, 02:10 -> about 02:20, well before the 03:10 trend job. The 02:00 fundamentals fetch is a separate process on the same key; that overlap already existed at 518 tickers and adds only 62 calls.
The full 580-ticker run has **not** been executed end to end (only the 62 new ones + BF-B, to avoid duplicating tomorrow's cron); the ~10 min figure is an extrapolation from these two measured runs.
Unique index / upsert: unchanged; a run over the 62 new tickers plus a second BF-B run produced 0 duplicate `(ticker, snapshot_date)` pairs.

Tests: 2,147 passed (full suite). New: BF-B remap on all three endpoints and BRK-B/AAPL left alone; `grades-consensus` keeps the hyphen; universe = US-listed minus delisted (foreign-domicile US listing in, HKSE out).

### 3. Older docs annotated (a forward-reference note under each title; prose untouched)

- `docs/cron_audit_2026-09.md`
- `docs/fmp_migration_and_toggles_investigation_2026-09-24.md`
- `docs/price_target_daily_refresh_feasibility_2026-09-26.md`
- `docs/price_target_trend_sept_gap_investigation_2026-09-25.md`
- `docs/price_target_trend_signal_investigation_2026-09-22.md`

(This doc and `CLAUDE.md` also mention the old name, but as the rename record itself, so they were left as they are; `CLAUDE.md` gained a short universe/BF-B note.)

### 4. The 2026-09-22 `grades_consensus` spike: mechanism found, actor untraceable

`grades_consensus` fetched_at on 2026-09-22: 538 rows (99 Watchlist tickers by today's lists, not the 132 noted before). By time (server clock = UTC):
**440 rows 21:26-21:35, of which 438 in about 80 s (21:34 and 21:35)**; 81 rows 15:01-15:21; 11 at 05:44 (a burst of 11 within 2 s: CRWD, SEZL, DOCN, PLTR, MRVL...); 1 at 03:19 (META).

- **The big burst is a one-off sweep of the tracked universe through `get_or_fetch` with the normal 7-day staleness.** It ran alphabetically from A (after NKE and CELH, likely two manual page views), about 290 tickers/min, far faster than page browsing or any cron. It covered the tracked universe as of that day: 387 of 440 are current index tickers, 53 are extras (delisted AVB/EA/EQR, BABA, CCJ...).
  The 43 current index tickers it did not hit are fully explained by that 7-day rule and by Nasdaq-100 having been added later (2026-09-23): 34 already had a fresh row from 09-17 to 09-19 (26 + 5 + 2), 8 are Nasdaq-only tickers that have no row at all, and 2 were re-fetched on 09-23/09-24.
  The surrounding rows in that minute (one each of earnings, profile, quote, price_change, ratios, historical_price_eod, grades_historical, price_target_summary) are a single ticker-page view, not part of the sweep.
- **Not the cron:** no `CronRunLog` row between 15:00 and 22:30 that day, and no cron job calls the Analyst Ratings data function (its only production caller is `GET /api/tickers/{t}/analyst-ratings`).
- **Actor: untraceable.** Ruled out or exhausted: the uvicorn log (`backend/logs/uvicorn_dev.log`) was reset when the app was restarted today and carries no timestamps; `~/.bash_history` has no timestamp lines; no Claude Code session transcript on this box spans 2026-09-22 21:00-22:00 UTC; no commit falls within 21:00-22:16 UTC (the closest are the 22:16 signal-investigation doc, which describes no FMP sweep, and 15:57 UTC). The most likely explanation is a one-off script or session that iterated the tracked universe through the analyst-ratings data path; that is an inference from the access pattern, not something confirmed.
- Not a problem to fix: it explains why `grades_consensus` rows cluster on 09-22 and 09-17 (an earlier, smaller sweep, 27 rows), and it means most grades rows are on a ~7-day staleness cycle set by that day.

### Manual UI checklist
1. Restart the app (`./bin/stop.sh && ./bin/start.sh`) to pick up the `fmp_client` change (production build, no hot reload).
2. Open `/tickers/BF-B` -> Analyst Ratings: the At-a-Glance price target now shows about $55 (previously empty).
3. Price Target Trend chart for BF-B: a live point dated today appears at the right edge (legacy history may be sparse).
4. Open `/tickers/ERIE` (or L, NWS) -> Analyst Ratings: no target, as before; no error.
5. Tomorrow after 02:30 UTC: `CronRunLog` for `pipeline.nightly_price_target_snapshot` is `success` with about "572 written, 8 failed", finished before 03:10.
