# Ops Runbook

Lightweight notes on spotting silent failures in Fathom's cron jobs, plus
what each maintenance script does, how to run it, and what to do if it
fails. Not a general operations manual — mostly entries for failure modes
that have actually happened and weren't caught quickly, plus the newer
scripts below.

## Starting / stopping the app

`./bin/start.sh` from the repo root brings up both servers: preflight
checks (`backend/.env` present with the required keys, `uv`/`node`/`npm`
on `PATH`), an explicit `init_db()` call, a cheap FMP connectivity check
(`GET /quote` for AAPL — fails loud here instead of surfacing later as an
empty ticker page), then backend (`uvicorn core.main:app --reload` →
`backend/logs/uvicorn_dev.log`) and frontend (`next dev` →
`frontend/logs/next_dev.log`), each in its own process group. Runs in the
foreground with prefixed `[backend]`/`[frontend]` log lines; Ctrl-C stops
both cleanly. Success looks like both `Waiting for backend...` /
`Waiting for frontend...` lines resolving to `... is up.` — if the backend
one times out, the preflight/DB/FMP checks already ran, so the problem is
almost always in `uvicorn`'s own startup (check the log path printed in
the failure message).

`./bin/stop.sh` stops both servers via the PID files `start.sh` wrote to
`.run/` — safe to run anytime, including when nothing is running (prints
"nothing to stop" per service, exits 0). Use this from a second shell, or
after a `start.sh` session was disconnected without a clean Ctrl-C.

**Pausing the FMP subscription**: set `FMP_ENABLED=false` in `backend/.env`
and restart (`./bin/stop.sh` then `./bin/start.sh`) — the app runs entirely
cache-only, and `start.sh`'s own FMP connectivity preflight check is
skipped rather than blocking startup. See CLAUDE.md's "Pausing the FMP
subscription" section for what degrades and what stays unaffected.

## Checking logs

Quick copy-pasteable answers for "the app's running fine, let me see what's
happening" — as opposed to the failure-mode sections below, which are for
something already known to be wrong.

**Is the app even running right now?** Check the PID files `start.sh`
writes, rather than guessing from `ps`:

```bash
for f in backend frontend; do
  p=.run/$f.pid
  if [ -f "$p" ] && kill -0 -- "-$(cat "$p")" 2>/dev/null; then
    echo "$f: running (pid $(cat "$p"))"
  else
    echo "$f: not running"
  fi
done
```

**Live backend/frontend logs**, from a second terminal while `start.sh` is
running in the first (these are the exact two files `bin/common.sh`
defines as `BACKEND_LOG`/`FRONTEND_LOG`, distinct from the cron/pipeline
job logs below):

```bash
tail -f backend/logs/uvicorn_dev.log
tail -f frontend/logs/next_dev.log
```

**Important**: the `[backend]`/`[frontend]` prefixes you see in
`start.sh`'s own terminal output are added live by `start.sh` itself (a
`tail -f | sed` view over these same two files) — they are NOT written
into the log files. Tailing the raw files directly, as above, shows
unprefixed backend/frontend output only; if you're looking for the
prefixed interleaved view specifically, that only exists in the terminal
`start.sh` was originally run from.

**Cron / pipeline job logs**, all under `backend/logs/`, one pair per job
(a plain `<name>.log`, written by the script's own `configure_logging()`
call with per-item detail; and a `<name>_cron.log`, the crontab entry's
raw stdout/stderr redirect — normally near-empty, since a healthy run's
real output goes to the first file, so a `_cron.log` with unexpected
content usually means the script crashed before logging was even
configured):

| Job | Log files |
|---|---|
| Nightly fundamentals fetch | `nightly_fundamentals_fetch.log` / `_cron.log` |
| Nightly full-universe score recompute | `nightly_score_recompute.log` / `_cron.log` |
| Weekly S&P 500 list refresh | `sp500_list_refresh.log` / `_cron.log` |
| Weekly Dow list refresh | `dow_list_refresh.log` / `_cron.log` |
| Cache pruning | `prune_cache.log` / `_cron.log` |
| Log rotation | `rotate_logs.log` / `_cron.log` |
| Fixture-contamination audit | `_cron.log` only — the script itself prints to stdout rather than calling `configure_logging()`, so there's no separate plain `.log` file, just the cron redirect |
| Stale-data health check | `stale_data_health_check.log` / `_cron.log` |
| Invalid-ticker purge | `purge_invalid_tickers.log` / `_cron.log` |
| Monthly price-target snapshot | `monthly_price_target_snapshot.log` / `_cron.log` |
| Daily SQLite backup | `backup_db.log` / `_cron.log` |

```bash
tail -50 backend/logs/nightly_fundamentals_fetch.log
tail -50 backend/logs/audit_fixture_contamination_cron.log   # no plain .log for this one
```

**Don't rely on tailing these files alone to catch a crash.** An
**uncaught** exception (Python's default excepthook) prints straight to
stderr — bypassing `configure_logging()`'s handlers entirely, landing only
in the `_cron.log` half of the pair above, invisible in the plain `.log`
and invisible anywhere in the app itself. This actually happened twice
(`sp500_list_refresh` 07-26/08-02, `backup_db` 08-09 — see "Known gaps"
below). `GET /api/config/cron-health` (surfaced as a site-wide banner when
any job isn't healthy) exists specifically to catch this class of failure
without anyone needing to tail a log at all — see "Cron job heartbeat /
health monitoring" below.

## Maintenance scripts (`backend/pipeline/`)

All of the scripts below are wired into `crontab.txt`'s weekly maintenance
window (Sundays 1:10–1:25 AM), the daily backup at 3:30 AM, or the daily
2:50 AM full-universe score recompute. Each can also be run manually with
`uv run python -m pipeline.<name>` from `backend/`.

**`nightly_score_recompute`** — cache-only `TickerScore` recompute
(`compute_ticker_score(cache_only=True)`) across every ticker with any
cached FMP data or an existing score row, not just the S&P 500/Dow
constituent list the nightly fetch job's own end-of-loop recompute
covers. Zero FMP calls, so it runs daily rather than weekly, and is safe
to run anytime. Success: a log line `Recompute complete. Processed: N.
... Failed: 0.` in `backend/logs/nightly_score_recompute.log`. Built
after an investigation found tickers viewed ad hoc (outside the index
universe) could get a stale/incomplete `TickerScore` row — e.g. computed
before all its step inputs finished caching — with nothing ever
revisiting it; `GET /api/tickers/{ticker}/score` also now self-heals a
row like that on its next view (`core/main.py::ticker_score_out`), but
this sweep is the backstop for a ticker that's never viewed again.

**`prune_cache`** — deletes `FundamentalsCache` rows older than
`Settings.cache_retention_days` (180 days by default; distinct from the
7-day staleness window, which only controls refetching, not deletion).
Success: a log line `Pruned N FundamentalsCache row(s) older than 180
days.` in `backend/logs/prune_cache.log`. `--dry-run` previews the count
without deleting. If N is unexpectedly huge, check whether the S&P
500/Dow constituent lists synced correctly recently (see the section
below) — a broken sync can make otherwise-active tickers look
"orphaned" and eligible for pruning.

**`backup_db`** — writes a compressed, timestamped snapshot of
`fathom.db` to `backend/backups/` (gitignored, not synced anywhere else
— this is on-disk-only insurance, not an off-site backup) via SQLite's
own `Connection.backup()` API, and prunes anything beyond the last 14.
Success: `Backup created: .../backups/fathom_<timestamp>.db.gz (N MB).`
in `backend/logs/backup_db.log`. If it fails, check disk space first
(`df -h`) — a full disk is the most likely cause. To restore: `gunzip
-k backend/backups/fathom_<timestamp>.db.gz` and copy the result over
`backend/fathom.db` (stop the app first).

**`rotate_logs`** — gzips any `backend/logs/*.log` file over 5MB to a
timestamped `.gz` archive and truncates the original in place, keeping
the last 8 archives per log name. No system `logrotate` involved
(confirmed not installed here, and a project-wide config would need root
this box doesn't have passwordless `sudo` for). Success: `Log rotation
complete. N file(s) rotated.` — N is often 0, which is normal (most logs
stay under 5MB between weekly runs). Safe even for a log a long-running
process still has open (e.g. `uvicorn_dev.log` during an active
`bin/start.sh` session): both `uvicorn`'s shell redirect and Python's
`logging.FileHandler` write in append mode, which always seeks to the
file's true end before writing, so the next write after a rotation lands
cleanly rather than leaving a gap. The only real caveat (shared with
`logrotate`'s own copytruncate mode) is a narrow race window where a
line written by a live process exactly during the rotation is lost.

**`stale_data_health_check`** — reports how many S&P 500/Dow universe
tickers haven't had their `profile` cache row refreshed within 10 days
(a 3-day buffer past the 7-day staleness window, to tolerate one missed
nightly run without a false alarm). Prints a readable report (fresh /
stale / never-fetched counts, plus the actual stale ticker list) to both
stdout and `backend/logs/stale_data_health_check.log` — never silent. A
large "stale" count is the first place to check the nightly fetch job
(`nightly_fundamentals_fetch_cron.log`) for a crash or an FMP outage; a
large "never fetched" count usually means the S&P 500/Dow constituent
sync hasn't run successfully (see below).

**`audit_fixture_contamination`** — see the incident this script was
built for in `CLAUDE.md`'s "Ad-hoc reproduction scripts must not touch
the real database". Read-only, promoted from manual-only to a weekly
scheduled job since it's cheap and safe. Success: `No fixture-
contamination fingerprints found.` A hit doesn't prove contamination on
its own (e.g. a real company genuinely named "Sample Inc" would
false-positive) — review the flagged ticker/statement/reason manually,
the same way the original incident was investigated.

**`purge_invalid_tickers`** — deletes every `FundamentalsCache` row (all
statement types, not just `profile`) and any `TickerScore` row for a
ticker whose cached `profile` fetch definitively came back with no
`companyName` at all, and that isn't a real `IndexConstituent`. A ticker
with no `profile` row at all is left alone (ambiguous — never attempted,
or a real access-tier gap like BRK.B's known 402, not confirmed
invalid). Success: `Purged N invalid ticker(s): TICKER1, TICKER2, ...`
in `backend/logs/purge_invalid_tickers.log` (or `No invalid ticker rows
found.`). `--dry-run` previews the list without deleting. Low blast
radius even for a rare false positive — unlike the fabricated-data
"Acme Corp" incident above, this only removes an already-empty cache
footprint; a wrongly-purged real ticker simply re-fetches from FMP on
its next view.

### Cron job heartbeat / health monitoring

Cross-cutting, not one specific script — `core/cron_health.py` wraps every
one of the 11 jobs above (plus `nightly_score_recompute`, the weekly S&P
500/Dow refreshes below, and `monthly_price_target_snapshot`) in a
`cron_heartbeat("<job_name>")` context manager, added directly at each
script's `if __name__ == "__main__":` block. It writes a `CronRunLog` row
(`"running"` at start, `"success"`/`"failure"` at exit — one row per
invocation, not an upsert, so a `"running"` row with no `finished_at` well
past that job's expected cadence is itself a useful stuck/crashed signal)
regardless of *how* the job fails, including an uncaught exception that
would otherwise only ever reach stderr — see "Known gaps" above for the
incident this was built to catch.

`GET /api/config/cron-health` computes each job's `health_status` from its
`CronRunLog` history: `"failed"` if the most recent row failed, `"unknown"`
if no row exists yet, `"overdue"` if no successful run falls within that
job's expected cadence (36h for the 3 daily jobs, ~8 days for the 7
weekly-Sunday jobs, ~35 days for the monthly one — `core/cron_health.py`'s
`_EXPECTED_CADENCE_HOURS`), else `"ok"`. The frontend's `CronHealthBanner`
(site-wide, mounted next to `FmpPausedBanner`) renders nothing while every
job is `"ok"`, and otherwise lists every non-ok job — so day to day, seeing
no banner at all is the expected, healthy state; nobody needs to
proactively check this endpoint or tail a log.

`CRON_JOB_NAMES` in `core/cron_health.py` is the single source of truth for
which 11 jobs exist — `tests/test_cron_wiring.py` fails loudly if
`crontab.txt` and this list ever drift apart, or if a listed job's script
stops calling `cron_heartbeat(...)`, so a future 12th cron job can't ship
unmonitored by accident.

**`CRON_HEALTH_ENABLED=false`** (`.env`, default `true`, requires a
backend restart — same convention as `FMP_ENABLED`) mutes the endpoint and
banner without touching heartbeat writes: `GET /api/config/cron-health`
returns `{"enabled": false, "jobs": []}` and `CronHealthBanner` renders
nothing. `CronRunLog` rows keep accumulating normally the whole time — this
is a display kill-switch, not a pause of the monitoring itself, useful for
an extended `FMP_ENABLED=false` window where a second banner alongside
`FmpPausedBanner` would just be noise the operator already knows about.

## Weekly index constituent refresh (S&P 500 / Dow)

Cron: `crontab.txt`, Sundays 1:00 AM (S&P 500) and 1:05 AM (Dow). Scripts:
`scrapers/refresh_sp500_list.py`, `scrapers/refresh_dow_list.py`.

**Known failure mode (2026-08-02 -- 2026-08-05): silent `IntegrityError`
rollback.** A bug in `scrapers/index_scraper.py::sync_index_constituents`
(fixed -- see git history around 2026-08-05) let SQLAlchemy flush new
rows' INSERTs before old rows' DELETEs, tripping the
`uq_index_constituent` unique constraint whenever a ticker appeared in
both the old and new list (the normal case, since index membership rarely
changes). The failure was caught inside the transaction and rolled back
cleanly, so there was no data corruption -- but the constituent table also
silently stopped updating, for over two weeks, with no alert.

**How to check this isn't happening again:**

1. Tail the cron logs -- a healthy run logs `"<Index> constituent refresh
   succeeded: N tickers stored"` from `scrapers.index_scraper`:
   ```
   tail -20 backend/logs/sp500_list_refresh_cron.log
   tail -20 backend/logs/dow_list_refresh_cron.log
   ```
   A run that instead shows a Python traceback (e.g.
   `sqlalchemy.exc.IntegrityError`) or an `ERROR` line means the sync
   failed and the stored list was left unchanged.
2. Check `last_synced_at` directly against today's date -- it should
   never be more than ~7 days stale (both jobs run weekly):
   ```
   uv run python -c "
   from sqlmodel import Session, select
   from core.db import engine
   from core.models import IndexConstituent
   with Session(engine) as session:
       for idx in ['sp500', 'dow']:
           rows = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == idx)).all()
           synced = sorted(r.last_synced_at for r in rows)
           print(idx, 'count=', len(rows), 'last_synced_at=', synced[-1] if synced else 'EMPTY')
   "
   ```

No automated alerting exists for this yet (out of scope for now) -- this
is a manual check to run if a ticker's index membership looks stale or
wrong in the app.

## Known gaps / outstanding items (audited 2026-08-16)

This section supersedes an earlier, uncommitted draft of the same content
(dated 2026-08-15) that sat in the working tree for about a day before
being reconciled into this version -- every item below has been
re-verified against the current repo/commit history as of 2026-08-16, not
carried forward blindly. If `git log`/`git blame` for this file doesn't
match a differently-worded "Known gaps" section a reader remembers seeing,
that draft is why; it was never committed.

**Closed, already done -- do not re-investigate:**

- **`shares_outstanding` data-quality issues (TEAM, FLY, PARA).** Two
  distinct FMP defects, both fixed, plus one non-defect:
  - TEAM Defect A -- FMP's freshly-filed-quarter units bug
    (`weightedAverageShsOut(Dil)` reads ~1000x too small on the latest
    quarter; confirmed on both TEAM and FLY). `37b5177` adds a
    magnitude-sanity guard (`helpers/shares.py::is_implausible_magnitude_
    shift`) that suppresses display rather than guessing a correction --
    `compute_shares_outstanding` itself already preferred
    `quote.marketCap/price` and was never affected.
  - TEAM Defect B -- a just-closed fiscal year's Q4 quarterly row served
    as a byte-identical duplicate of the annual total, silently
    double-counted into TTM (confirmed: TEAM's Q4 FY2026 revenue/CFO/FCF/
    net income). `628a6e2` adds `ttm.py::is_quarter_content_duplicate_of_
    annual` and substitutes the true isolated quarter before summing.
  - **PARA -- not a data defect at all.** FMP's `PARA` symbol was
    reassigned away from Paramount to an unrelated company (the prior
    draft's own working theory: a post-Skydance-merger delisting).
    Confirmed live in `fathom.db`: `PARA`'s cached profile now reads
    `"companyName": "Banzai International, Inc. Class A"` (NASDAQ,
    "Software - Application"), and its `TickerScore` was recomputed
    2026-08-16 (31/Fail) off Banzai's real fundamentals, not stale
    Paramount data. Cache was purged and re-fetched under the correct
    company as a data operation -- no commit, nothing to grep for.
- **Cron thundering-herd, full scope.** `4498c33`'s original fix covered 8
  statement-grain endpoints only, leaving the rest of
  `nightly_fundamentals_fetch.py` on flat 7-day staleness. `e73b9b9`
  extended earnings-date-aware refetching to `ratios`/latest,
  `analyst_estimates`, and `enterprise_values`, and moved `profile` to a
  30-day flat window instead (non-earnings-driven, near-static reference
  data -- earnings-aware gating would be the wrong model there, not just a
  longer version of the same one). `fbc6f8d` stopped force-fetching
  `quote` in the nightly batch job specifically (`live_quote=False`),
  falling back to normal staleness gating there instead. Verified via a
  real-data replay (zero live FMP calls spent): the 4 newly-gated
  endpoints drop from 569 guaranteed same-night fires each to 0-27; `quote`
  drops from 568/night guaranteed to ~81/night average.
- **Cron silent-failure blind spot.** A 2026-08-16 audit of every
  `<job>.log`/`<job>_cron.log` pair found two real, otherwise-invisible
  incidents: `sp500_list_refresh` crashed with an uncaught
  `sqlite3.IntegrityError` on 07-26 and 08-02, and `backup_db` crashed with
  `sqlite3.OperationalError: database or disk is full` on 08-09 -- both
  visible only in the raw `_cron.log` stderr capture, since an uncaught
  exception bypasses `configure_logging()`'s handlers entirely. Closed by
  the `CronRunLog` table + `cron_heartbeat()` wrapper (`core/cron_health.py`,
  wired into all 11 scripts' entry points) + `GET /api/config/cron-health`
  + the site-wide `CronHealthBanner` -- see "Cron job heartbeat / health
  monitoring" below. Purely additive: the wrapper always re-raises the
  original exception unchanged, so existing stderr/`_cron.log` capture and
  exit codes are untouched; a heartbeat DB write failure (e.g. the exact
  disk-full case above) is itself swallowed rather than masking the job's
  real outcome.
- **SEC EDGAR cross-check firing during the nightly bulk sweep.**
  `get_step5_data`'s on-demand cross-check was gated on `cache_only`
  alone, which the nightly job never sets (it needs live data for
  everything else that function fetches) -- confirmed 134 real
  `sec_company_facts` calls fired from the nightly sweep in a single night
  (2026-08-14), against the function's own "never in bulk" invariant.
  `2461d7e` adds a separate `allow_sec_cross_check` flag, defaulting to
  `True` (on-demand single-ticker views unaffected) with the nightly job
  passing `False`.
- **On-demand SEC lookup for zero-value Financials cells -- 2 fields
  only.** `e6cb0c5` implements this for exactly `incomeTaxesPaid`/
  `interestPaid`, the two fields `FinancialsStatementTable.tsx`'s own
  `INCOMPLETE_COVERAGE_LABELS` already flags as having a confirmed FMP
  gap -- XBRL tags verified live against MSFT's real SEC EDGAR filings
  (`IncomeTaxesPaidNet` $28.7B, `InterestPaid` $1.6B for FY2025, both read
  as a literal 0 in FMP's own cache). **Narrower than an earlier draft of
  this section implied**: a generic "any cell" mechanism was investigated
  and explicitly not built, since the XBRL tag-and-fallback research
  doesn't generalize to arbitrary fields without the same kind of
  per-field live-filing work -- see "Still genuinely open" below.
- **`TickerSearch.tsx` ESLint error** (`react-hooks/set-state-in-effect`,
  `setHighlighted(-1)` called synchronously inside a `useEffect`) --
  fixed by `a7bf121`.
- **Watchlist 100-cap undocumented** -- `0967210` added it to CLAUDE.md.
- Carried forward unchanged from the prior draft (not independently
  re-verified this pass -- see that draft's own evidence, now superseded
  as a document but not contradicted):
  - **Bank/Insurance/REIT Valuation-tab correctness** -- `949651e`: Bank/
    REIT forced onto Price-to-Book, Insurance skips CFO-based methods
    entirely. Covered by dedicated tests in `scoring/test_step3.py` and
    `tests/test_step3_data.py`, documented in `docs/valuation.md` /
    `docs/company-type-variations.md`.
  - **Step3/Valuation test coverage** -- 55 tests across
    `scoring/test_step3.py` (36) and `tests/test_step3_data.py` (19), all
    passing. A narrow subset (`run_price_to_book`'s 10yr lookback branch,
    `normalize_fcf` edge cases in isolation, data-layer/pipeline tests)
    was explicitly deferred in `3d647ee`'s own commit message and remains
    the only real gap, not the whole step.
  - **Financials tables -> shadcn Table migration** -- fully done, zero
    raw `<table>` elements outside `components/ui/table.tsx` itself.
  - **Score-explanation feature** -- already shared cross-step via
    `components/shared/AnalysisSectionCard.tsx` (Step1, Step2, Step4,
    Step5 alike), not Financials-only.
  - **`cache_staleness_days` dead-code suspicion** -- false alarm, 15 live
    call sites across `data/`.

**Still genuinely open:**

- **NCI/dual-class DNI-valuation-method bug.** Flagged in a prior
  investigation: Discounted Net Income as a Valuation method mishandles
  companies with a non-controlling/minority interest or a dual (multi-
  class) share structure. Reported against IBKR, BX, ARES, and SYM --
  IBKR/BX/ARES were reviewed and closed with no code change, per an
  explicit decision that the effect wasn't material enough to act on for
  those three. **SYM (Symbotic) remains the one live-risk candidate** if
  this fix family gets picked up later. A proposed fix design exists but
  was never implemented -- confirmed via grep that `scoring/step3.py` /
  `data/step3_data.py` have no minority-interest or dual-class handling
  of any kind today.
- **Generic/any-cell on-demand SEC lookup.** Deliberately not built -- see
  the closed item above. Only `incomeTaxesPaid`/`interestPaid` have a
  lookup path; any other zero/blank Financials or Ratios cell has none.
- **Ticker-symbol-reassignment, as a general structural gap.** The
  PARA/Banzai situation (above) was caught and fixed as a one-off, but
  nothing in the codebase detects this class of issue generally -- a
  delisted/merged/recycled ticker symbol silently getting reassigned to
  an unrelated company by the data provider will recur for other tickers
  with no automated signal to catch it, unlike (a different class of
  data-integrity issue) `audit_fixture_contamination`'s weekly sweep --
  see that script's own section above.

**New since the last audit:**

- **Speculative Growth Summary-tab pill: built, then reverted.** Added in
  `c8b1b1b`, reverted in `401e786` -- judged redundant with the pill
  already shown in the shared, sticky `TickerHeader` (visible on every
  tab, Summary included). Not a bug or a regression, a deliberate
  "not needed" call.

Doc-drift sweep (CLAUDE.md, this file, `docs/*.md`) as of the 2026-08-15
draft found no other discrepancies: no lingering Alpha Vantage/
News-Sentiment references, `STEP_WEIGHTS`/`MOAT_WEIGHT` match byte-for-byte
between `backend/scoring/overall.py` and `frontend/lib/overallScore.ts`,
and the `FMP_ENABLED` pause mechanism (kill switch, cache gating, 503 on
refresh, site-wide banner) is all in place as CLAUDE.md describes -- not
re-run for this pass, carried forward as still current.
