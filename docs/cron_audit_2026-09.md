# Cron Job Audit — 2026-09-11

Phase 1/2 of a requested cron audit: inventory every scheduled job against
what's actually installed and running, report findings, and scope (but not
implement) consolidation/optimization candidates. Read-only investigation —
no code or schedule changes made.

## Live crontab vs. repo `crontab.txt`

**No drift.** `crontab -l` and `backend/crontab.txt` are byte-for-byte
identical — 15 entries, all invoked as `-m package.module` from `backend/`,
matching the documented convention.

## Job count: 15, not 11 (or 12)

CLAUDE.md and `OPS_RUNBOOK.md` both describe the heartbeat mechanism as
covering "12 real cron jobs" (as of the 2026-08-17 build). The actual
current count is **15**, confirmed three independent ways:

- `backend/crontab.txt` has 15 uncommented entries.
- `core/cron_health.py::CRON_JOB_NAMES` has 15 entries.
- `tests/test_cron_wiring.py` (which fails if `crontab.txt` and
  `CRON_JOB_NAMES` drift apart, or if any listed job doesn't call
  `cron_heartbeat`) passes cleanly — **the code itself is internally
  consistent and fully wired**; only the prose in CLAUDE.md/OPS_RUNBOOK.md
  is stale.

The 3 jobs added since the 12-job count was last written down:
`pipeline.nightly_entry_signal_calculation`, `pipeline.nightly_liquidity_zone_calculation`,
and `pipeline.monthly_momentum_snapshot` — all three ship with real
`cron_heartbeat(...)` calls and `_EXPECTED_CADENCE_HOURS` entries, so nothing
is unmonitored. `OPS_RUNBOOK.md`'s "Checking logs" table and its "Cron job
heartbeat" section's "12"/"the 4 daily jobs"/"7 weekly-Sunday jobs"/"the
monthly one" counts are all stale prose (should read 15 jobs — 6 daily / 7
weekly / 2 monthly) — a documentation fix, not a code fix.

**Separately, not in scope of this audit's schedule/wiring check but found
along the way:** CLAUDE.md's "Liquidity Zone (LP) detection" and
"Watchlists" sections still describe the two technical jobs below as scoped
to watchlists literally named `"Main"`/`"Secondary"`. Three commits since
then (`eda38d4`, `fcacfc0`, `0ef5e5b`) renamed those to `"W1"`/`"W2"` and
then generalized to a `^W[1-5]$` pattern match (`data/watchlists.py::
list_tickers_across_watchlists`) — the code is correct and tested, but
CLAUDE.md's prose was never updated to match and is now actively wrong
about the watchlist-naming mechanism.

## Job inventory

| Script | Schedule | Purpose | Live API calls? | Approx runtime | Monitored (heartbeat)? |
|---|---|---|---|---|---|
| `pipeline.nightly_fundamentals_fetch` | Daily 2:00 AM | Refreshes Steps 1/2/4/5 + Summary + Segmentation + TickerScore for the full tracked universe (index ∪ cached ∪ scored ∪ watchlisted, ~572 tickers) | **Yes** — FMP, cache-aware (~7,000 calls/~30min cold, mostly cache hits warm) | Currently instant (FMP paused, early-returns) | Yes |
| `pipeline.nightly_score_recompute` | Daily 2:50 AM | Cache-only `TickerScore` recompute across the full tracked universe (backstop for ad-hoc/watchlisted tickers) | No (cache-only) | ~22s / 572 tickers | Yes |
| `pipeline.nightly_trend_calculation` | Daily 3:10 AM | Swing/BOS/Weinstein-stage/A-D-divergence/SMA-position calc, full tracked universe, one Yahoo batch fetch | Yes — Yahoo only | ~92s / 572 tickers (2 failures: TWTR, WBA — no Yahoo history) | Yes |
| `pipeline.nightly_entry_signal_calculation` | Daily 3:20 AM | BB+RSI (2h) technical entry-signal calc, scoped to the `^W1-W5$` watchlist union (114 tickers currently) | Yes — Yahoo only (FMP intraday is 402'd on the current plan) | ~26s / 114 tickers | Yes |
| `pipeline.nightly_liquidity_zone_calculation` | Daily 3:25 AM | Daily+Weekly support/resistance zone detection, same W1–W5 union | Yes — FMP when enabled, else Yahoo fallback (currently Yahoo, FMP paused) | ~28s / 114 tickers | Yes |
| `scrapers.refresh_sp500_list` | Weekly, Sun 1:00 AM | Scrapes Wikipedia, replaces stored S&P 500 constituent list on success | Yes — Wikipedia (not FMP) | <1s | Yes, nominally (see finding below) |
| `scrapers.refresh_dow_list` | Weekly, Sun 1:05 AM | Scrapes Wikipedia, replaces stored Dow 30 constituent list on success | Yes — Wikipedia (not FMP) | <1s | **Yes, nominally — but see "Live issue found" below: it has been silently failing every week since 2026-08-16 and still reports "success"** |
| `pipeline.prune_cache` | Weekly, Sun 1:10 AM | Deletes `FundamentalsCache` rows older than 180 days (retention, distinct from the 7-day staleness window) | No | <1s (0 rows currently) | Yes |
| `pipeline.rotate_logs` | Weekly, Sun 1:15 AM | Gzips + truncates any `backend/logs/*.log` over 5MB, keeps last 8 archives | No | <1s | Yes |
| `pipeline.audit_fixture_contamination` | Weekly, Sun 1:20 AM | Read-only scan of `FundamentalsCache` for test-fixture contamination fingerprints | No | <1s | Yes |
| `pipeline.stale_data_health_check` | Weekly, Sun 1:25 AM | Reports tickers whose cached `profile` hasn't refreshed within 10 days — scoped to **S&P 500 + Dow only**, not the full tracked universe (see finding below) | No | <1s | Yes |
| `pipeline.purge_invalid_tickers` | Weekly, Sun 1:30 AM | Deletes cache/score rows for tickers with a confirmed-empty FMP profile (excludes index members) | No | <1s (0 found currently) | Yes |
| `pipeline.monthly_price_target_snapshot` | Monthly, 1st @ 3:00 AM | Appends one price-target-consensus snapshot row per S&P 500 + Dow ticker (FMP has no native historical series) | Yes — FMP | See finding below — no real full-universe run has ever completed | Yes |
| `pipeline.monthly_momentum_snapshot` | Daily 3:00 AM, days 1–5 (self-gates to the actual first NYSE trading day) | 3/6/12-month composite momentum ranking over the Moat-rated subset of the full tracked universe | Yes — Yahoo only | ~26s / 395 tickers | Yes |
| `pipeline.backup_db` | Daily 3:35 AM | Transactionally-consistent gzip SQLite backup, keeps last 14 | No (local file op) | ~2min, ~94–96MB compressed | Yes |

All 15 scripts call `cron_heartbeat("<job_name>")` at their own
`if __name__ == "__main__":` block, matching their `CRON_JOB_NAMES`/
`_EXPECTED_CADENCE_HOURS` entries exactly (`test_cron_wiring.py` passes).
Universe scoping was checked against the specific index-only-vs-full-
tracked-universe regression documented in CLAUDE.md's Speculative Growth /
`nightly_score_recompute.py` history: `nightly_fundamentals_fetch`,
`nightly_score_recompute`, `nightly_trend_calculation`, and
`monthly_momentum_snapshot` (via its Moat-rated filter over the full
universe) all correctly call `load_full_tracked_universe`. Two jobs are
narrower **by explicit design** (`stale_data_health_check`,
`monthly_price_target_snapshot` — both use `load_universe_tickers`, i.e.
S&P 500 + Dow only) — flagged below since one of these narrower scopings
looks like a real gap, not just a documented choice.

## Live issues found (not schedule/consolidation issues, but surfaced by this audit)

### 1. Dow list refresh has been silently failing for a month, and reports "healthy" the whole time

`scrapers.refresh_dow_list` has failed every single week since **2026-08-16**
(4 consecutive Sunday runs: 08-16, 08-23, 08-30, 09-06) with:
```
Could not find the constituents table (id="constituents") -- Wikipedia page structure may have changed.
```
The stored Dow constituent list (`IndexConstituent` where `index_name="dow"`)
has not actually synced since **2026-08-09** — over a month stale as of
today.

This is invisible in `GET /api/config/cron-health` / `CronHealthBanner`
because `scrapers/dow_scraper.py::refresh_dow_constituents` (via
`index_scraper.refresh_index_constituents`) deliberately **returns**
`SyncResult(success=False)` on a parse failure rather than raising — a
correct design choice for never leaving the stored list half-synced, but it
means `cron_heartbeat`, which only distinguishes success/failure by whether
an exception propagated out of the `with` block, records every one of these
runs as `"success"`. `CronRunLog` confirms this: the most recent
`scrapers.refresh_dow_list` row reads `status=success`, `finished_at` set
normally — there is currently no automated signal anywhere that this job's
actual output has been wrong for a month. This is a different failure shape
than the "uncaught exception bypasses logging" gap `cron_heartbeat` was
originally built to catch (CLAUDE.md's 2026-08-16 audit) — this is a
**caught, logged, but not re-raised** failure, which the heartbeat mechanism
was never designed to see.

Not fixed as part of this audit (Phase 1/2 is investigate + propose only) —
flagged here since it's a live, currently-ongoing data-quality issue
independent of anything scheduling-related, and because a real fix
(`refresh_index_constituents` re-raising, or a heartbeat-visible
`result.success` check at each scraper's own entry point) is a natural
Phase 3 candidate if you want to expand this task's scope.

### 2. `monthly_price_target_snapshot` has no confirmed full-universe run in its history

The only entry in `monthly_price_target_snapshot.log` is a 2-ticker
(AAPL/MSFT) run from 2026-07-27 that looks like a manual smoke test, not a
real cron-scheduled pass — every scheduled 3:00 AM/1st-of-month run since
then (checked: 2026-09-01) has hit the `FMP_ENABLED=false` early-return and
skipped. `FMP_ENABLED` is currently `false` in `backend/.env`, which also
explains why `nightly_fundamentals_fetch` is currently a no-op every night.
Not a bug — both are the documented, correct degrade behavior — but worth
noting as context for reading the "approx runtime"/"live API calls" columns
above: several of these numbers reflect a currently-paused FMP subscription,
not steady-state behavior.

## Possible consolidations / optimizations

### A. Two monthly jobs both fire at 3:00 AM on the 1st of the month

`monthly_price_target_snapshot` (`0 3 1 * *`) and `monthly_momentum_snapshot`
(`0 3 1-5 * *`) both trigger at the literal same minute on the calendar 1st.
They write to different tables (`PriceTargetSnapshot` vs. the Momentum
snapshot table) and use different data sources (FMP vs. Yahoo), so there's
no redundant-fetch waste — but both open a `Session(engine)` against the
same SQLite file concurrently, meaning one will block on SQLite's writer
lock while the other holds it.
- **Benefit of staggering**: trivial to do (change one cron minute, e.g.
  push momentum to `5 3 1-5 * *`), removes any lock-contention risk, zero
  downside.
- **Risk**: none — this is a one-line schedule change, no logic touched.
- **Priority**: low impact (both jobs are fast and SQLite's lock wait would
  self-resolve in well under a second based on observed runtimes), but
  free to fix.

### B. `stale_data_health_check` is scoped narrower than the job it's checking up on

`nightly_fundamentals_fetch` refreshes the **full tracked universe** (index
∪ cached ∪ scored ∪ watchlisted), but `stale_data_health_check` only checks
staleness over `load_universe_tickers` (S&P 500 + Dow only) — the same
narrower-scope pattern that caused the confirmed staleness bug documented in
CLAUDE.md's Speculative Growth section (`nightly_score_recompute`/
`recompute_ticker_scores.py`'s pre-2026-08-15 default). This means a
watchlisted-but-not-indexed ticker (or any ad-hoc-viewed ticker) whose
nightly refresh silently stopped working would **never show up** in this
report, even though the fetch job itself is supposed to be keeping it fresh.
- **Benefit of widening to `load_full_tracked_universe`**: closes exactly
  the kind of blind spot this job exists to catch; the function is already
  imported two modules away and used by three other jobs in this same
  package, so this is a low-effort, low-risk change (swap one import/call).
- **Risk/tradeoff**: report gets noisier — the full universe (~572) is
  larger than S&P 500 + Dow (~530), and any of the never-viewed/rarely-
  revisited long-tail tickers could show up as "never fetched" simply
  because they were watchlisted or scored once and never refreshed since
  (which is arguably accurate, not a false positive, but a behavior change
  in the report's normal output worth confirming you want).
- **Priority**: medium — this is a monitoring gap, not a live incident like
  finding #1 above, but it's the exact class of regression this task asked
  to specifically check for.

### C. `monthly_price_target_snapshot`'s S&P 500 + Dow-only scope is intentional, not a bug — flagging only as a possible future widen

Unlike (B), this scope is explicit in the module's own docstring and tied to
matching FMP's `grades-historical` monthly grain for the Analyst Ratings
tab. Widening it to the full tracked universe would mean the Analyst
Ratings tab's price-target history starts working for watchlisted/ad-hoc
tickers too, at the cost of more FMP calls once a month. No evidence this
has ever been requested — listed here only because the task asked
specifically to check for universe-scope drift, and this is the other of
the two jobs using the narrower helper.

### D. No genuine redundant-fetch or merge candidates found among the nightly jobs

Checked specifically for jobs "doing redundant fetches of the same data
another job already refreshed that day" and "jobs that run back-to-back and
touch overlapping data": `nightly_entry_signal_calculation` (3:20, intraday
2h bars, 60-day lookback, Yahoo) and `nightly_liquidity_zone_calculation`
(3:25, daily/weekly bars, ~4yr lookback, FMP-or-Yahoo) run 5 minutes apart
over the identical W1–W5 ticker union, but fetch genuinely different bar
granularities for genuinely different purposes — there's no shared raw data
to dedupe between them the way `nightly_trend_calculation`'s single batch
fetch already avoids one-call-per-ticker waste internally. Merging their
Python process (one `init_db()`, one `Session`, one interpreter startup)
would save perhaps a few hundred milliseconds total — not worth the
coupling cost of two independently-versioned features sharing one entry
point (per CLAUDE.md's own stated reasoning for keeping them separate: "an
FMP outage affecting Liquidity Zones shouldn't read as a BB+RSI health
failure or vice versa"). No change recommended here.

### E. `FMP_ENABLED` / `CRON_HEALTH_ENABLED` gating — checked, no gap found

Every job that makes live FMP calls already gates correctly:
`nightly_fundamentals_fetch` and `monthly_price_target_snapshot` both
early-return before resolving their ticker universe when
`FMP_ENABLED=false`; `nightly_liquidity_zone_calculation` branches cleanly
between FMP/Yahoo via `daily_price_sources.get_daily_bar_source()`. Every
Yahoo-only job (`nightly_trend_calculation`, `nightly_entry_signal_calculation`,
`monthly_momentum_snapshot`) correctly has **no** `FMP_ENABLED` guard at all,
since none of their fetches are FMP-gated to begin with. No optimization
needed here — this was already done correctly.

## Constraints observed for this phase

- No code, schedule, or documentation changes made — investigation and
  reporting only, per the task's Phase 1/2 scope.
- No browser verification performed.
- Full backend test suite was not run; only `tests/test_cron_wiring.py` was
  run (read-only assertion check, 3 passed), consistent with "if you touch
  a script with existing unit tests, run only that script's own test file" —
  no scripts were modified, so this was the only test file relevant to
  confirm the investigation's own claims.
- No scratch/throwaway scripts were created during this investigation (all
  checks were done via direct `uv run python -c "..."` one-liners and log/DB
  reads) — nothing to clean up.

## Awaiting go-ahead for Phase 3

None of the above has been implemented. If you'd like to proceed, please
indicate which item(s) from A–E (and/or the two live issues) to act on —
each will be its own commit, with `crontab.txt`/`OPS_RUNBOOK.md`/CLAUDE.md
updated to match, and `core/cron_health.py` updated if job names/counts
change.
