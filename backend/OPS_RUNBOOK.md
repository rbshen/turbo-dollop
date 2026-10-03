# Ops Runbook

Lightweight notes on spotting silent failures in Fathom's cron jobs, plus
what each maintenance script does, how to run it, and what to do if it
fails. Not a general operations manual — mostly entries for failure modes
that have actually happened and weren't caught quickly, plus the newer
scripts below.

## Starting / stopping the app

`./bin/start.sh` from the repo root brings up both servers: preflight
checks (`backend/.env` present with the required keys, `uv`/`node`/`npm`
on `PATH`), an explicit `init_db()` call, and a cheap FMP connectivity
check (`GET /quote` for AAPL — fails loud here instead of surfacing later
as an empty ticker page). It has two modes, switched by flag (or the
`FATHOM_MODE=dev|prod` env var):

- **dev (default)** — `./bin/start.sh` / `--dev`: backend `uvicorn --reload`
  and frontend `next dev`, no build step, so code changes hot-reload and
  startup is fast. Uses more memory.
- **prod** — `./bin/start.sh --prod`: a production frontend build
  (`next build`, before either server starts so its memory peak never
  overlaps the backend's), then backend (`uvicorn`, no `--reload`) and
  frontend (`next start`). Keeps the memory footprint down on this small
  VPS, but **there is no hot reload: a code change to either app takes
  effect only after `./bin/stop.sh` + `./bin/start.sh --prod`** (the
  restart rebuilds the frontend, which takes minutes, not seconds).

Logs go to `backend/logs/uvicorn_dev.log` and `frontend/logs/next_dev.log`
(which also holds the prod build output; the `_dev` in both filenames is
historical), each server in its own process group. Runs in the
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

**Pausing the FMP subscription** (no restart, no `.env` edit): Settings > FMP data groups >
"FMP master switch" (below the group table), or from a shell

```
cd backend
uv run python -m pipeline.data_groups status      # per-group state
uv run python -m pipeline.data_groups pause-all   # master OFF: cache-only everywhere, nothing wiped
uv run python -m pipeline.data_groups resume      # master ON (per-group settings untouched)
```

Takes effect within ~5 s in every process (state is in the DB). Individual
groups (fundamentals, news, ...) can be toggled in Settings > FMP data groups; `start.sh`'s
FMP preflight is skipped when the master or `profile_quote` is off, and a 402
there only warns. A nightly job whose group is off records a **skipped** run
(blue dot in Scheduled Jobs, "Skipped since <date>") -- if a job shows skipped
for longer than you intended, a group is still off. See CLAUDE.md's "Data groups"
section for the full mechanism, the 402 safety net and what degrades.

**FMP plan-restriction / key problems:** a group showing "Restricted by FMP" was
canary-confirmed to return HTTP 402 (re-checked weekly by
`pipeline.stale_data_health_check` and when you edit "My FMP plan"); "Failing" means
3+ consecutive non-402 errors; a red "FMP rejected the API key" line means 401/403.
The 402 path has only been tested against simulated responses.
For `fundamentals` a 402 restricts only the refused request variant (e.g. quarterly statements); see "Restricted request variants" below.

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
| Nightly Weinstein stage calculation (`nightly_trend_calculation`) | `nightly_trend_calculation.log` / `_cron.log` |
| Nightly BB+RSI entry-signal calculation | `nightly_entry_signal_calculation.log` / `_cron.log` |
| Nightly Liquidity Zone (LP) calculation | `nightly_liquidity_zone_calculation.log` / `_cron.log` |
| Nightly Sector ETF heatmap | `nightly_sector_heatmap.log` / `_cron.log` |
| Nightly market breadth | `nightly_market_breadth.log` / `_cron.log` |
| Nightly ETFs screener | `nightly_etf_screener.log` / `_cron.log` |
| Nightly corporate-events cache (earnings/dividends/splits) | `nightly_corporate_events.log` / `_cron.log` |
| Nightly last-close cache (header price fallback) | `nightly_last_close_snapshot.log` / `_cron.log` |
| Nightly Warren RSI/ADX/WVF entry-signal calculation | `nightly_warren_signal_calculation.log` / `_cron.log` |
| Weekly S&P 500 list refresh | `sp500_list_refresh.log` / `_cron.log` |
| Weekly Nasdaq-100 list refresh | `nasdaq_list_refresh.log` / `_cron.log` |
| Weekly Dow list refresh | `dow_list_refresh.log` / `_cron.log` |
| Cache pruning | `prune_cache.log` / `_cron.log` |
| Log rotation | `rotate_logs.log` / `_cron.log` |
| Fixture-contamination audit | `_cron.log` only — the script itself prints to stdout rather than calling `configure_logging()`, so there's no separate plain `.log` file, just the cron redirect |
| Stale-data health check | `stale_data_health_check.log` / `_cron.log` |
| Invalid-ticker purge | `purge_invalid_tickers.log` / `_cron.log` |
| Nightly price-target snapshot | `nightly_price_target_snapshot.log` / `_cron.log` |
| Monthly Momentum snapshot | `monthly_momentum_snapshot.log` / `_cron.log` |
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
below). `GET /api/config/cron-health` (surfaced in Settings > Scheduled
Jobs) exists specifically to catch this class of failure without anyone
needing to tail a log at all — see "Cron job heartbeat / health
monitoring" below.

## Maintenance scripts (`backend/pipeline/`)

All of the scripts below are wired into `crontab.txt`'s weekly maintenance
window (Sundays 12:15–12:35 AM), the daily backup at 3:30 AM, or the daily
3:25 AM full-universe score recompute (deliberately last before the backup -- it copies the Weinstein, BB+RSI and Warren
outputs onto `TickerScore`, so it has to run after all three). Each can also be run manually with
`uv run python -m pipeline.<name>` from `backend/`.

**`nightly_score_recompute`** — cache-only `TickerScore` recompute
(`compute_ticker_score(cache_only=True)`) across the tracked universe
(`data/tracked_universe.py`, see "Tracked universe" below), not just the
S&P 500/Dow constituent list the nightly fetch job's own end-of-loop
recompute covers. Zero FMP calls, so it runs daily rather than weekly, and is safe
to run anytime. Success: a log line `Recompute complete. Processed: N.
... Failed: 0.` in `backend/logs/nightly_score_recompute.log`. Built
after an investigation found tickers viewed ad hoc (outside the index
universe) could get a stale/incomplete `TickerScore` row — e.g. computed
before all its step inputs finished caching — with nothing ever
revisiting it; `GET /api/tickers/{ticker}/score` also now self-heals a
row like that on its next view (`core/main.py::ticker_score_out`), but
this sweep is the backstop for a ticker that's never viewed again.

**Why it runs at 3:25 AM, after the technical jobs (moved from 2:50 on
2026-09-19; whole nightly chain re-timed 2026-09-30, technical first):** it copies Weinstein (1:05), BB+RSI (1:20) and Warren
(1:25) output onto `TickerScore` for the Screener. At 2:50 it ran before all
three, so the Screener always showed the *previous* night's stage/signal —
up to a full day stale (36 of 579 tickers' Screener Weinstein stage
disagreed with their own `TrendAnalysis` row). `tests/test_cron_wiring.py::
test_score_recompute_runs_after_every_job_it_copies_from` fails if it is ever
scheduled ahead of any of them again. If one of those jobs overruns 3:25, the
tickers it hadn't reached read a night behind until the next run.

**Check that the ordering is doing its job** (read-only; run after a nightly
run finishes, i.e. after ~3:30 AM server time) — both mismatch counts should
be `0`:

```bash
cd backend && uv run python - <<'EOF'
import sqlite3
c = sqlite3.connect("file:fathom.db?mode=ro", uri=True)
print(c.execute("""select count(*),
                          sum(coalesce(s.weinstein_stage,'') != coalesce(t.weinstein_stage,'')),
                          sum(coalesce(s.weinstein_stage_since_date,'') != coalesce(t.weinstein_stage_since_date,''))
                   from tickerscore s join trendanalysis t on t.ticker = s.ticker""").fetchone())
EOF
```

(Output is `(tickers compared, stage mismatches, since-date mismatches)`. The
since-date check is the more sensitive one: the 1:05 job's replay can revise
a ticker's since-date without changing its stage, so it catches a stale copy
the stage check misses — on the day the reorder shipped it read 173
mismatches against 36 for stage alone.)

**`nightly_trend_calculation`** — recomputes Weinstein Stage Analysis
(`backend/analysis/trend_structure/weinstein.py`; the "trend" job, package,
table and endpoint names are historical -- the swing/BOS trend-structure
engine they were named for was removed 2026-10-01) for the same
tracked universe `nightly_fundamentals_fetch`/`nightly_score_recompute`
use (`data/tracked_universe.py`), upserting one `TrendAnalysis` row per ticker
(`data/trend_analysis_data.py`). Sourced from FMP daily bars (data group `daily_prices`) through
the shared bars cache, not fundamentals endpoints. Fetches the whole
universe's OHLCV in **one** batch
(`clients.shared_bars_cache.get_or_fetch_bars_batch`) -- it is also the only job that fills the
daily-bar cache the LZ/Sector/Breadth/Momentum jobs read warm. **Skipped (real `skipped` status, Phase 6b)
while `daily_prices` is off** -- there is no Yahoo fallback any more, so it does not compute on stale
bars. Success: a log line `Nightly trend calculation complete.
Processed: N. Failed: M.` in `backend/logs/nightly_trend_calculation.log`.
A high failed count points at FMP `/historical-price-eod/full` reachability/rate-limiting or a
delisted/renamed symbol FMP no longer serves -- the heartbeat message's `N not served by FMP (cached
bars kept)` names how many; check the log for the specific tickers.

The Weinstein stage is computed on weekly bars resampled from the
same daily OHLCV batch — no second fetch. `^GSPC` (its Mansfield RS
benchmark) rides along in the same one batch download as one more symbol,
but is never counted toward `Processed`/`Failed` and never gets its own
`TrendAnalysis` row — a `^GSPC` fetch failure that run just degrades every
ticker's Weinstein RS/breakout fields to null/false for that run, it is not
a reason to see it in the failure list.

**`nightly_sector_heatmap`** — recomputes the Sector Heatmap: the 11 SPDR
sector ETFs (`XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC`) x 7 trailing
total-return windows (1w/1m/3m/6m/9m/YTD/1y), upserting 77 `SectorEtfReturn`
rows per session (`data/sector_heatmap_data.py`). One shared-bars-cache batch (FMP daily bars);
skipped while `daily_prices` is off. Runs at 1:35 AM
and re-derives the same anchor (the last completed session) on weekends and
holidays, upserting over its own rows -- harmless. **Scheduled and live** as of
2026-09-21 (installed via `crontab crontab.txt` from `backend/`; `crontab -l`
should show the `30 3 * * *` entry -- editing `crontab.txt` alone does
nothing). After storing, it prunes snapshots older than the rolling
370-day retention window (`RETENTION_DAYS`, measured from the newest
snapshot; a failed run never prunes), so the table plateaus around 20k rows
rather than growing forever. Success: a log line `Nightly sector heatmap
complete. As of: <date>. Processed: 11. Failed: 0. Pruned: N.` in
`backend/logs/nightly_sector_heatmap.log` (`Pruned` is 0 every night until
the first snapshot ages past a year, ~Sep 2027). The job **raises** (so
`cron-health` shows it failed) only when *nothing* could be computed; a
single fund that fails is logged as `Sector heatmap: XL? FAILED` and shows
as a blank row on the page under the new as-of date (never a stale number
under a fresh date). The page prints its own as-of date, so a job that has
quietly stopped reads as an old date. Check `Processed` first -- a
shortfall is FMP not serving a fund or a renamed symbol.

**`nightly_corporate_events`** — **DISABLED since 2026-10-01 pending investigation** (about 1,165 calls per run at 406-527
requests/min, over Starter's 300/min). Its `crontab.txt` line is commented out and the installed crontab matches (pre-change
copy: `backend/crontab.backup-2026-10-01.txt`); the code, tables and cached rows are untouched. The Scheduled Jobs page shows it
as "Skipped — Disabled since 2026-10-01: ..." (`core/cron_health.py::DISABLED_CRON_JOBS`), not Overdue. Effect: the Chart tab's
E/D markers (the cache's only reader) keep serving the frozen cache; newly reported earnings and newly declared dividends get no
marker, and a ticker first opened after 10-01 02:47 has none at all until you run
`uv run python -m pipeline.nightly_corporate_events --tickers X,Y` for it (details: docs/specs/corporate-events.md). Nothing else
depends on it (no job reads its output). **Re-enable:** (1) uncomment the `45 2 * * *` line in `backend/crontab.txt`; (2) delete
the `pipeline.nightly_corporate_events` entry from `DISABLED_CRON_JOBS` in `backend/core/cron_health.py` (the wiring test fails
if only one of the two is done); (3) from `backend/` run `crontab crontab.txt`, then `crontab -l` and confirm the line is there;
(4) **use the planned slot 1:50 AM (`50 1 * * *`), not the old 2:45 line** that stays commented in `crontab.txt`: the job runs at 406-527 requests/min for ~2-4 min, fundamentals starts at 2:00 (since the 2026-10-02 reschedule), so it must end before 2:00 and never overlap it; 1:50 follows Market Breadth (ends ~1:41, worst ~1:45). Edit the commented line's time fields when you uncomment it and update `JOB_METADATA` (`time_label` "1:50 AM", `sort_minutes` 110) to match; `test_corporate_events_runs_after_technical_jobs_and_before_fundamentals` goes live again and passes at 1:50.
**Roll back this change:** `crontab backend/crontab.backup-2026-10-01.txt` restores the installed crontab, and `git revert` of the
disabling commit restores the repo.

(Description of the job when enabled, 2:45 AM, Phase 6a:) refreshes the FMP-backed earnings /
dividends / splits cache (`CorporateEvent`, `CorporateEventFetch`; `data/corporate_events_data.py`)
for every US-listed tracked ticker: two calls per ticker nightly (`/earnings`, `/dividends`, group
`corporate_events`) plus `/splits` weekly (when never fetched or last fetched >= 6 days ago), each
**upserting** by (ticker, type, date) -- a stored row is never deleted because FMP omitted it (safe
against a plan downgrade to a shorter history window) -- so the first run is the backfill. The run then
prunes rows whose event date is older than 4 years (`RETENTION_DAYS`, independent of FMP/plan; the log
line shows `Pruned`). ~1,180 calls on an ordinary night, ~1,770 on a splits night, ~1-2 min. Feeds the Chart tab's E/D markers,
which read this cache first. Success: `Corporate-events refresh complete. Processed: N. With a failed
endpoint: M. ... FMP calls: C. Pruned ...` in `backend/logs/nightly_corporate_events.log`. A failed endpoint keeps that ticker's
old rows for that type (listed under `Tickers with failures`); the job raises (heartbeat "failure")
only if **every** ticker failed. Skipped (real `skipped` status) while `corporate_events` is off — the
cache then keeps serving. Check it: `select event_type, count(*) from corporateevent group by 1` and
`select max(fetched_at) from corporateeventfetch`.

**`nightly_last_close_snapshot`** (1:00 AM, Phase 6a) — caches each US-listed tracked ticker's last
official close (`TickerLastClose`, latest-only; `data/last_close_data.py`), one
`/historical-price-eod/full` call each (group `daily_prices`). It is the ticker header's price
fallback: served when the live FMP quote fails or `profile_quote` is off. Success: `Last-close
snapshot complete (as of <date>). Processed: N. Written: N. Failed: M.`; a few failures (a symbol FMP
has no bars for) are normal; the job raises only if it wrote nothing at all. Skipped while
`daily_prices` is off. Weekend/holiday runs re-cache the same session idempotently.

**`nightly_market_breadth`** — computes one `MarketBreadthSnapshot` row per
session for the S&P 500 (`IndexConstituent` `sp500`, via `load_sp500_tickers`):
the % of constituents closing above their own 20-, 50- and 200-day SMA, and new
52-week highs minus new 52-week lows (intraday High/Low, 252 sessions,
ties count) — `data/market_breadth_data.py`, `scoring/market_breadth.py`.
FMP bars from `SharedBarsCache`; skipped while `daily_prices` is off. Runs at 1:40 AM, **after** the 1:05 bar-cache job that warms
`SharedBarsCache` with all 503 tickers' 2y daily bars, so the normal run is a
~3s warm-cache read. If the 1:05 job failed or overran it self-heals with one
live batch (~30s–5min), which could overlap the 2:45 corporate-events start (writer-lock
contention only). A weekend/holiday run re-derives the same anchor and
upserts over its own row. **Coverage gate:** if fewer than 97% of constituents
(i.e. more than 15 of 503 missing) have a bar on the anchor session, the job
**raises** — `cron-health` shows it failed — and writes nothing, rather than
saving percentages computed over a shrunken universe; the error names the
missing tickers. Below the gate a row is saved even with a few tickers missing
(`stale_excluded` on the row records how many, and the log warns with their
names). Success: a log line `Nightly market breadth complete. As of: <date>.
Constituents: 503. With bar: 503. Excluded: 0.` in
`backend/logs/nightly_market_breadth.log`. A recurring handful of names in
the `Excluded` list is a renamed/delisted symbol FMP no longer serves; a
large number is FMP reachability. The table is never pruned.
**Installed in the live crontab 2026-09-21** (`crontab -l` shows the
`35 3 * * *` entry, byte-identical to `crontab.txt`); a later `crontab.txt`
edit still needs `crontab crontab.txt` from `backend/` to take effect. The
one-time history seed is `pipeline/backfills/backfill_market_breadth.py` (see
its docstring; it also fills the 20-day columns onto rows that predate them,
only where NULL, and is safe to re-run).

**`nightly_etf_screener`** — refreshes the ETFs screener's read-model, one `EtfScreenerRow` per ETF in
`data/tracked_universe.py::load_etf_universe` (19 at registration: the 11 sector SPDRs, SPY, QQQ, TLT, ...). Per ETF: fund facts
from `/etf/info` and the profile, 1y / vs-SPY returns from the shared daily-bar cache, the Weinstein stage, and the
Warren/BB+RSI/LP signal fields. **Registered 2026-10-03 (step 6), 1:45 AM** (daily line in `crontab.txt`, `JOB_METADATA`,
`CRON_JOB_NAMES`, 36 h cadence like the other daily jobs): after the 1:05 bar-cache job and LP/BB+RSI/Warren (Warren ends by
~1:31 at worst), before fundamentals (2:00), the planned corporate-events slot (1:50) and the 3:25 recompute / 3:30 backup.
Steady state ~1-3 min and almost no FMP calls (fresh caches); the first run fetched ~40. Skipped (a real `skipped` status)
while `daily_prices` is off; `etf_info` / `profile_quote` off serve cached rows. A field whose source failed keeps its last
value (never overwritten with NULL, except the three signal fields, where no row is a real answer). After a successful live
run it prunes rows of ETFs no longer in the universe. Failure rule: `check_failure_threshold` (all failed, or >= 5% of >= 25).
Success: a log line with `N ETFs, N written, 0 failed` in `backend/logs/nightly_etf_screener.log`. Manual runs:
`uv run python -m pipeline.nightly_etf_screener [--tickers SPY,QQQ] [--cache-only] [--dry-run]` (`--cache-only --dry-run`
writes nothing at all). Since the **2026-10-03 cutover (step 7)** it is the only job that refreshes an ETF's `TrendAnalysis` (from the one Weinstein computation shared with the screener row) and `TickerLastClose` (and the ETFs' own Sunday bar resync); the stock-side jobs no longer process ETFs, and an ETF's `TickerScore` row is frozen (left in place, never deleted). Its message reads `N ETFs, N written, N trend rows, N last closes, F failed, ...`: `trend rows` and `last closes` should equal `ETFs` on a healthy night. Check these first if an ETF's stage or price looks stale on the Watchlist or ticker page. Rollback of the cutover: `git revert` the step-7 phase B commit (the stock universe holds the ETFs again; the ETF job's extra writes are harmless).

**`prune_cache`** — deletes `FundamentalsCache` rows older than
`Settings.cache_retention_days` (180 days by default; distinct from the
7-day staleness window, which only controls refetching, not deletion).
Success: a log line `Pruned N FundamentalsCache row(s) older than 180
days.` in `backend/logs/prune_cache.log`. `--dry-run` previews the count
without deleting. The same job also trims `SharedBarsCache` (FMP OHLCV bars)
to 6 years of `1d` / 3 years of `60m` (`clients/shared_bars_cache.py::
RETENTION_DAYS`) and logs one `SharedBarsCache: N '<interval>' bar(s) older
than D days deleted.` line per interval — a few thousand bars a week in
steady state, ~1M on the very first run after a long-unpruned cache. If the
FundamentalsCache N is unexpectedly huge, check whether the S&P
500/Dow constituent lists synced correctly recently (see the section
below) — a broken sync can make otherwise-active tickers look
"orphaned" and eligible for pruning.

**`backup_db`** — writes a compressed, timestamped snapshot of
`fathom.db` to `backend/backups/` (gitignored, not synced anywhere else
— this is on-disk-only insurance, not an off-site backup) via SQLite's
own `Connection.backup()` API, then prunes with a tiered retention rule
(changed 2026-09-21 from a flat "last 14"): the **newest 7 backup dates**
(daily tier) plus **4 weekly copies** from before that window (weekly tier)
— 11 dates at steady state, reaching back ~5 weeks. A week's copy is that
ISO week's (Mon–Sun) last backup: the Sunday one normally, the latest
earlier day if a Sunday run failed. Both tiers count backups actually on
disk, not calendar days, so a multi-day outage never shrinks retention below
3 copies. Every file on a kept date is kept (a manual same-day re-run doesn't
displace anything); files that don't match `fathom_YYYYMMDD_HHMMSS.db.gz`
exactly are never pruned. Tunable via `BACKUP_KEEP_DAILY`/`BACKUP_KEEP_WEEKLY`
in `pipeline/backup_db.py`; the constants apply on the next run, and
already-on-disk files are judged against them then (nothing is force-deleted
out-of-band). Success: `Backup created: .../backups/fathom_<timestamp>.db.gz
(N MB). Retention: 3 daily + 4 weekly kept.` in `backend/logs/backup_db.log`,
plus a `Pruned N old backup(s): ...` line whenever anything was deleted.
Before writing anything, it checks the volume has at least 1.25x the DB's size
free (`BACKUP_FREE_SPACE_FACTOR` — the run briefly holds an uncompressed copy
of the DB next to the backups) and otherwise fails immediately with
`InsufficientDiskSpaceError: Refusing to start backup: ... Nothing was
written.`, recorded as a `pipeline.backup_db` failure by the cron heartbeat.
The compressed copy is written under a dot-prefixed temp name and renamed
into place only once complete, and both temp files are removed on any
exception, so a failed run leaves no temp file and no truncated
`fathom_*.db.gz` behind.
A run killed outright (SIGKILL/power loss) skips that cleanup, so each run
first sweeps its own stranded `.fathom_<ts>.db.tmp` / `.db.gz.tmp` files older
than 6 hours (`STALE_TEMP_MIN_AGE_HOURS`) — before the disk-space check, since a
stranded ~1.2GB copy counts against it — and logs a warning naming what it removed.
If it fails, check disk space first
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

**`stale_data_health_check`** — reports how many tickers in the
tracked universe (not just S&P 500/Dow — widened 2026-09-11; since 2026-10-02 an expired or
delisted ticker, and since 2026-10-03 any browsed or unadded one, is not refreshed on purpose, so it is not reported) haven't had their `profile` cache row
refreshed within 10 days (a 3-day buffer past the 7-day staleness window,
to tolerate one missed nightly run without a false alarm). Prints a
readable report (fresh / stale / never-fetched counts, plus the actual
stale ticker list) to both stdout and
`backend/logs/stale_data_health_check.log` — never silent. A large "stale"
count is the first place to check the nightly fetch job
(`nightly_fundamentals_fetch_cron.log`) for a crash or an FMP outage; a
large "never fetched" count usually means the S&P 500/Dow constituent
sync hasn't run successfully (see below).

**Also removes non-US tickers (2026-09-26 safety net).** Fathom supports US-listed tickers only, so at the start
of each run any tracked ticker whose cached profile `exchange` is not a US venue (or, with no profile, whose
symbol is dotted) is deleted from every table with a `ticker` column (`pipeline/non_us_purge.py`; local-only, no
FMP call). Ordinary ADRs (NYSE/NASDAQ) and OTC names are US and untouched. If more than 2% of the tracked
universe would go, it **refuses**, deletes nothing and says so in the report and the heartbeat message
("non-US purge REFUSED") -- that means an exchange-name mismatch (check `core/tickers.py::US_EXCHANGES`), not
real non-US tickers. Removal is irreversible short of a `backups/` restore.

**Also flags delisted tickers, a second, independent write this same run performs**
(rewritten Phase 6a, 2026-09-26 — see the "Phase 6a" section of `docs/archive/claude-md-history-fmp-migration.md` and `docs/specs/fmp-data-and-bar-cache.md`; moved from the
`corporate_events` group to `index_membership` 2026-09-27, since this is a tracked-ticker
universe-membership check, the same job family as the index scrapers, not
earnings/dividends/splits). It pages FMP's `/delisted-companies` (group `index_membership`,
~157 sequential calls of 100 rows) and sets `TickerScore.delisted_at` for any tracked ticker
listed with a delisted date on/before today (a reused symbol — profile `ipoDate` after the
delisted date — is ignored). **A ticker the endpoint does not list is never flagged.** Since
2026-10-02 an existing flag **is** cleared when the whole list was read, the ticker is no
longer on it, and a live `/profile` call says `isActivelyTrading: true` (the heartbeat message
then says `delisted flag cleared: X`); the sync reads the wide known set
(`load_all_known_tickers`) because a flagged ticker is excluded from the tracked universe. Nightly Weinstein/Liquidity Zone/Momentum skip a flagged ticker's fetch/compute entirely.
The sync deletes nothing (the locked, unscheduled wipe is the only deleter, and it treats a delisted ticker like any other). The cron heartbeat message names anything newly flagged, or says
`delisted sync skipped (index_membership off)` / `delisted list incomplete` (a page failed; the
next weekly run retries).
**To manually clear a flag** (normally unnecessary now; use it when the automatic re-check cannot, e.g. FMP's profile still reads inactive):
```
uv run python -c "
from sqlmodel import Session
from core.db import engine
from core.models import TickerScore
with Session(engine) as s:
    row = s.get(TickerScore, 'TICKER')
    row.delisted_at = None
    s.add(row); s.commit()
"
```
It re-flags on the next weekly run only if FMP still lists the ticker as delisted.

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

### Daily prices: FMP-first (P2, 2026-09-24)

Daily bars (`SharedBarsCache` "1d") come from FMP `/historical-price-eod/full` for US-listed
tickers (data group `daily_prices`) -- the only provider (Massive was removed in Phase 6a, Yahoo in Phase 6b). Non-US
listings get no nightly bars (the P3 `daily_prices_intl` group and phantom-bar filter were removed in
the Phase 6a follow-up, 2026-09-26). Only `pipeline.nightly_trend_calculation` (1:05) fetches; LZ/Sector/Breadth/Momentum read
its warm cache.

- **Nightly:** per ticker one call from `last cached bar - 7d` (overlap). The last cached bar is
  overwritten; any earlier overlapping close off by > 0.5% means FMP restated history (split,
  spin-off, symbol reuse) and that ticker is refetched over its full window and REPLACED. ~600
  calls, ~1-2 min. **Sundays (UTC)** the 1:05 job passes `force=True` -> every ticker gets a full
  refetch + replace (the weekly resync).
- **Heartbeat message** of each daily-bar job: `N not served by FMP (cached bars kept)`.
  A large N means FMP is failing/empty for those tickers. Their cached bars are left as they are.
- **Group off / master off / not on plan / restricted:** there is no fallback provider (Yahoo removed
  in Phase 6b). Every daily-bar job (Weinstein, Liquidity Zones, Sector Heatmap, Market Breadth, Momentum)
  reports a real `skipped` cron status instead of computing on stale bars; nothing is wiped, the last
  cached bars keep serving (chip "Cached only"). The Chart tab's daily ranges render EMPTY.
- **Re-backfill (already run once, 2026-09-24):** `uv run python -m pipeline.backfills.
  backfill_fmp_daily_bars [--dry-run] [--report out.json]` (replace per ticker, one
  transaction; a ticker FMP cannot serve keeps its rows). Take `pipeline.backup_db` first and
  check free disk. `pipeline.backfills.backfill_market_breadth --rebuild` re-derives the
  `is_backfilled` breadth rows (never a live row).
- **Basis:** FMP `full` is split- AND spin-off-adjusted (not dividend-adjusted); see
  `docs/specs/fmp-data-and-bar-cache.md`.

#### Long history (P3, 2026-09-25)

- **`daily_prices_long`** (Settings > FMP data groups; history beyond the nightly ~5y: Chart W_4Y and the
  Analyst overlay). Off = cached-only for an existing long-history row, otherwise an empty chart /
  overlay (no Yahoo fallback). Its 402 canary is AAPL; `pipeline.stale_data_health_check` re-probes a restricted one weekly.
  (`daily_prices_intl` was removed 2026-09-26.)
- **`LongHistoryBars` table** (~10y/ticker, filled lazily on a ticker-page view, ~1.6-2.1 s the first
  time): no cron job touches it and `prune_cache` never trims it. It only grows (~250 rows/yr/ticker,
  ~0.6 MB each). To force a re-fetch of one ticker (e.g. after a suspected restatement) delete its rows:
  `DELETE FROM longhistorybars WHERE ticker = 'KO'` -- the next view refetches 10y. Nothing else depends
  on it.
- `backfill_fmp_daily_bars` no longer has `--scope`/a parity gate (US only; non-US tickers are skipped).

### History protection and the cache history audit (2026-10-02)

A shorter, empty or error FMP answer never shortens a cached statement history (`core/history_merge.py`; spec: docs/specs/fmp-data-and-bar-cache.md,
"History protection"). What you will see:

- **`nightly_fundamentals_fetch` message** gains `, N history-clamped` (tickers whose answer had fewer periods than cached, older ones kept) and
  `, M empty-body kept` (an empty/error body ignored over a non-empty row). Both are informational: the job does not go red for them. The log
  has one `History clamped for TICKER (key): ...` or `Empty/invalid body ignored for TICKER ...` line per ticker per run. A count near the size of
  the universe after a plan change means the new plan serves less history than the cache holds: the cache is intact; decide whether the shorter
  window matters.
- **Compare before and after a plan change** (read-only, no FMP call, opens the file `mode=ro`):

  ```bash
  cd backend
  uv run python -m pipeline.cache_history_audit --json > ~/audit-before.json     # before changing the plan
  uv run python -m pipeline.cache_history_audit --json > ~/audit-after.json      # after a nightly run or two
  diff ~/audit-before.json ~/audit-after.json
  uv run python -m pipeline.cache_history_audit                                  # human-readable table
  ```

  Per cache key: tickers per number of periods held and the oldest period (statements, ratios, key metrics, estimates, segmentation, grades
  history), bars and span per ticker (daily, 60m, long history), rows per ticker (corporate events). Nothing should get shorter.
- **Refresh button**: history rows are kept and marked stale (`fetched_at` = 1970-01-01) rather than deleted, so the refetch merges. A `fetched_at`
  of 1970 on a statement row is that marker, not corruption; `prune_cache` leaves such rows alone.

### Restricted request variants (2026-10-02)

If FMP refuses one way of asking (say `period=quarter`) the `fundamentals` group stays **Live**; only that request variant is
recorded as restricted (table `datagroupvariant`, created by `init_db` on the next start) and Settings > FMP data groups shows
"Quarterly data not on plan: ..." under the group with a **Re-test** button. Spec: docs/specs/fmp-data-and-bar-cache.md, "Request variants".

- **List / re-test / clear** (no API needed):

  ```bash
  cd backend
  uv run python -m pipeline.data_groups variants        # restricted variants, since when, last re-test
  uv run python -m pipeline.data_groups retest          # replays each with its own request; clears only on a 200 (a few FMP calls)
  uv run python -m pipeline.data_groups clear-variant --group fundamentals --key '/income-statement?limit=12&period=quarter'
  ```

- **Logs:** one line when a variant becomes restricted (`FMP request variant RESTRICTED ...`) and one when it clears (`... CLEARED ...`); the
  nightly fundamentals message carries `N variant-unavailable (V request types refused by the plan)`. That count is informational: the job stays green;
  decide from it whether the missing data matters (today Step 5 is `insufficient_data` for Standard/REIT stocks without quarterly balance sheets).
- **Weekly re-probe** (`stale_data_health_check`, Sunday) and a plan edit re-test every restricted variant with its own request, so an upgrade
  self-heals and a still-refused variant stays restricted without flapping.
- A symbol-scoped 402 (BRK.B, BF.B, 0941.HK), a 429, a 5xx or a timeout restricts nothing.

### Cron job heartbeat / health monitoring

Cross-cutting, not one specific script — `core/cron_health.py` wraps every
one of the 15 cron jobs currently in `crontab.txt` (`core/cron_health.py::
CRON_JOB_NAMES` is the single source of truth for the current list) in a
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
job's expected cadence (36h for the 6 daily jobs, ~8 days for the 7
weekly-Sunday jobs, ~35 days for the 2 monthly ones — `core/cron_health.py`'s
`_EXPECTED_CADENCE_HOURS`), else `"ok"`. Settings > Scheduled Jobs
(`ScheduledJobsSection`) lists every job's health there — the old
site-wide `CronHealthBanner`/`FmpPausedBanner` pair was deleted and folded
into this Settings section instead, so a healthy day no longer shows
anything outside Settings; nobody needs to proactively check this endpoint
or tail a log.

**Status messages and the failure threshold (2026-10-02).** A job that tracks per-ticker work sets
`run.message` (stored in `CronRunLog.error_summary`, shown on the Scheduled Jobs page) and runs its failed
count through one shared rule, `core/cron_health.py::check_failure_threshold(attempted, failed, summary)`:
the run is marked `failure` (the existing red state; no new health value) when **failed / attempted >= 5%**
(`FAILURE_RATE_THRESHOLD`) **or everything attempted failed**. The 5% rate rule only applies from **25
attempted** (`FAILURE_RATE_MIN_ATTEMPTED`), so a tiny run (a `--tickers` test, a short watchlist) cannot flip
on one error; "no data" and "skipped" counts appear in the message but never in the rule. What each job now
reports: price-target "N written, M no analyst data, K skipped (ETF), F failed"; fundamentals "N refreshed, F
failed, C FMP calls, D min"; BB+RSI and Warren "N computed, F failed, S swept, P pruned"; score recompute "N
scored, S skipped (no cached profile), F failed" (skips are not in the denominator); backup "X MB, N old
backup(s) pruned" (no threshold: any error raises). Limits: fundamentals only counts an exception that escapes a
ticker's refresh -- most per-statement FMP errors are swallowed inside `get_stepN_data` (`safe_fetch`) and are
invisible to this count. What to do when a run goes red on the threshold: the red text starts with the normal
counts and ends "-- N% failed (limit 5%)" or "-- all N attempted failed"; the per-ticker reasons are in the
job's own `backend/logs/<job>.log` ("Tickers with failures: ...").

A job commented out of the crontab on purpose goes in `core/cron_health.py::DISABLED_CRON_JOBS` (job -> date + reason): it stays in
`CRON_JOB_NAMES`, shows as "Skipped — Disabled since <date>: <reason>" instead of aging into Overdue, and `test_cron_wiring.py`
requires it to be absent from `crontab.txt`. Currently: `nightly_corporate_events`.

`CRON_JOB_NAMES` in `core/cron_health.py` is the single source of truth for
which 15 jobs exist — `tests/test_cron_wiring.py` fails loudly if
`crontab.txt` and this list ever drift apart, or if a listed job's script
stops calling `cron_heartbeat(...)`, so a future 16th cron job can't ship
unmonitored by accident.

**`CRON_HEALTH_ENABLED=false`** (`.env`, default `true`, requires a
backend restart — same read-once convention) mutes the endpoint and the
Scheduled Jobs section's cron-health display without touching heartbeat
writes: `GET /api/config/cron-health` returns `{"enabled": false, "jobs":
[]}` and the section renders nothing for it. `CronRunLog` rows keep
accumulating normally the whole time — this is a display kill-switch, not
a pause of the monitoring itself, useful for an extended FMP pause where
that display would just be noise the operator already knows about.

## Tracked universe (which tickers the nightly jobs process), opt-in since 2026-10-03

Spec: `docs/specs/tracked-universe.md`. One helper, `data/tracked_universe.py::load_tracked_universe` (stocks) plus `load_etf_universe`: a ticker is in
through an index (S&P 500 / Nasdaq-100 / Dow), any watchlist, the system set (seed ETFs, the benchmark, the live `rs_benchmark`), manual data (Moat, custom
valuation, bank capital, growth-catalyst note) or because it was **added** (`TickerView.added_at`, any idle age); never when it is delisted-flagged. A ticker that
was only opened is `browsed` (30 days) then `expired`, or `untracked` (no view record): not in the universe, data kept. Opening a page records a view
(`TickerView.last_viewed_at`, at most one write per ticker per day, touched at the start of the request) but never admits it. `GET/POST/DELETE
/api/tickers/{t}/universe` reads, adds and removes. The wipe (`pipeline/wipe_untouched_tickers.py`) is the only thing that deletes a ticker: dry run by default,
`--apply` locked behind `FATHOM_ALLOW_WIPE_APPLY=1`, not in the crontab.

**Verify (read-only):**
1. `cd backend && uv run python -m pipeline.tracked_universe_report`: by reason, live on 2026-10-03 after the flip: stocks `index 518, manual 32, added 18, watchlist 13,
   delisted 5` (581 in the stock universe), ETFs `system 12, added 7` (19 in the ETF universe); `TickerView` rows 597. A newly opened ticker shows as `browsed`
   (not in the universe) until it is added; browsed tickers become `expired` after 30 idle days (the report lists them, `--days N` previews).
2. `uv run python -m pipeline.wipe_untouched_tickers` (dry run, writes nothing, needs no env var): 0 wipes today; the 25 grandfathered tickers are protected by
   `added`; at 2026-11-03 only the delisted AVB, EQR, TWTR, WBA (4,088 rows) plus 5 adoptions (CROX, DXC, ROKU, SNAP, VFC). Once the wipe is scheduled, every `expired`
   ticker and every unprotected, unadded delisted ticker idle over 30 days shows here first.
3. SQL: `SELECT COUNT(*), COUNT(added_at) FROM tickerview;` (rows, added) and `SELECT ticker, added_source FROM tickerview WHERE added_at IS NOT NULL;`.
4. The nightly messages and sizes: the stock jobs process the stock universe (581 tickers on 2026-10-03, minus the 5 delisted that are skipped by the flag), the ETF job
   the 19 ETFs; a ticker opened but not added appears in none of them.

**Opening a ticker and adding it.** A newly opened ticker works but is in no screener and no nightly job. Until the Add button ships (step 3b) the only ways in are
`POST /api/tickers/{t}/universe` (stock: a live score compute, about 10-20 FMP calls; ETF: its screener row, about 2-4 calls), a watchlist add, or a Moat / custom
valuation / bank-capital entry. Remove (`DELETE`) is refused while the ticker is protected.

**First start after the 2026-10-02 deploy (history).** `init_db()` created `tickerview` and, because it was empty, seeded one row per existing ticker with
`last_viewed_at = now` (a second `init_db()` does nothing). Since the opt-in flip a seeded view admits nobody. The 2026-10-03 grandfather backfill marked the 25
tickers that were then in the universe only through a view as added (pre-write snapshot `backend/backups/pre_universe_step2_20261003.db.gz`); its script was removed
at the flip.

**Roll back the flip:** revert the flip commit and restart (the `added_at` / `added_source` columns are inert for the old code; no table changed). Under the old rule any
view in the last 30 days admits a ticker again, and the 25 grandfathered tickers are in through their (seed or real) views until about 2026-11-01. A cleared delisted flag is
restored with `UPDATE tickerscore SET delisted_at = datetime('now') WHERE ticker = '...'`.

## Monitored-watchlist rename (W1-W5 -> E1-E5), 2026-10-02

The nightly Liquidity Zone / BB+RSI / Warren jobs read every watchlist named `E<number>` or exactly `ETF`
(rule: `data/watchlists.py`, `MONITORED_WATCHLIST_PATTERN`). `pipeline/rename_monitored_watchlists.py` renames
the old `W1`..`W5` lists to `E1`..`E5`. It changes only `watchlist.name` (everything else references a list by id),
matches those five exact names only (never `W score passed`, `W6`, ...), and is idempotent.

    cd backend
    uv run python -m pipeline.rename_monitored_watchlists --dry-run     # preview, writes nothing
    uv run python -m pipeline.rename_monitored_watchlists               # logical backup + full DB backup, then rename
    uv run python -m pipeline.rename_monitored_watchlists --rollback    # E1..E5 back to W1..W5, by id

- **Backups, in order, before any write:** a JSON dump of `watchlist`, `watchlistticker` and `savedscreenerfilter`
  to `backend/backups/watchlist_rename_<ts>.json` (the rename plan lives in it; `--rollback` reads the newest one,
  or `--backup-file PATH`), then `pipeline.backup_db.create_backup`. The full backup needs ~1.25x the DB size free;
  if it refuses, the script exits 1 having written nothing. Free space (prune `backend/backups/`) and re-run, or pass
  `--skip-full-backup` to rely on the logical backup plus the nightly backup.
- **Run it** with no nightly job mid-flight and before the 01:15 UTC slot (the first monitored-list job, Liquidity Zones) (jobs read list names once, at start).
  If code ships without the migration the three jobs log "No watchlist matching ... exists", process nothing,
  and the sweep only clears readings after 7 days.
- **Verify:** the log (`logs/rename_monitored_watchlists.log`) lists each `Renamed id N: W<n> -> E<n>`; then
  `GET /api/watchlists` shows E1-E5 with the same ids and ticker counts, and the next morning each of the three
  nightly logs reads `... for <n> tickers across ['E1', 'E2', ...]`.
- **Rollback:** `--rollback` (above); a list the user has since renamed again is skipped, and it aborts if a
  list called `W<n>` has been re-created. Last resort: restore the full backup.
- Not a cron job, so no `CRON_JOB_NAMES`/crontab entry.

## Weekly index constituent refresh (S&P 500 / Nasdaq-100 / Dow)

Cron: `crontab.txt`, Sundays 12:00 AM (S&P 500), 12:05 AM (Nasdaq-100), and
12:10 AM (Dow), before the 1:00 AM daily chain (moved from 1:00-1:10 on 2026-10-02). Scripts: `scrapers/refresh_sp500_list.py`,
`scrapers/refresh_nasdaq_list.py`, `scrapers/refresh_dow_list.py`.

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
   tail -20 backend/logs/nasdaq_list_refresh_cron.log
   tail -20 backend/logs/dow_list_refresh_cron.log
   ```
   A run that instead shows a Python traceback (e.g.
   `sqlalchemy.exc.IntegrityError`) or an `ERROR` line means the sync
   failed and the stored list was left unchanged.
2. Check `last_synced_at` directly against today's date -- it should
   never be more than ~7 days stale (all three jobs run weekly):
   ```
   uv run python -c "
   from sqlmodel import Session, select
   from core.db import engine
   from core.models import IndexConstituent
   with Session(engine) as session:
       for idx in ['sp500', 'nasdaq', 'dow']:
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
  + Settings > Scheduled Jobs (the old site-wide `CronHealthBanner` was
  deleted and folded into that section) -- see "Cron job heartbeat /
  health monitoring" below. Purely additive: the wrapper always re-raises the
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
    `tests/test_step3_data.py`, documented in `docs/specs/valuation.md` /
    `docs/specs/company-type-variations.md`.
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
and the FMP pause mechanism (superseded 2026-09-24 by per-group data toggles) was all in place as CLAUDE.md describes -- not
re-run for this pass, carried forward as still current.
