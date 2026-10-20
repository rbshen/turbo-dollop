# Ops Runbook

Lightweight notes on spotting silent failures in Fathom's cron jobs, plus
what each maintenance script does, how to run it, and what to do if it
fails. Not a general operations manual — mostly entries for failure modes
that have actually happened and weren't caught quickly, plus the newer
scripts below.

## Starting / stopping the app

`./bin/start.sh --prod` from the repo root is **how the live app runs**. It brings up both
servers: preflight checks (`backend/.env` present with the required keys, `uv`/`node`/`npm`
on `PATH`), an explicit `init_db()` call, and a cheap FMP connectivity
check (`GET /quote` for AAPL — fails loud here instead of surfacing later
as an empty ticker page). Two modes, switched by flag (or the
`FATHOM_MODE=dev|prod` env var):

- **prod (the live app)** — `./bin/start.sh --prod`: a production frontend build
  (`next build`, before either server starts so its memory peak never
  overlaps the backend's), then backend (`uvicorn`, no `--reload`) and
  frontend (`next start`). Keeps the memory footprint down on this small
  VPS, but **there is no hot reload: a code change to either app takes
  effect only after `./bin/stop.sh` + `./bin/start.sh --prod`** (the
  restart rebuilds the frontend, which takes minutes, not seconds).
- **dev (development only)** — `./bin/start.sh` / `--dev` (the script's no-flag
  default, kept so day-to-day development is unchanged): backend `uvicorn --reload`
  and frontend `next dev`, no build step, so code changes hot-reload and
  startup is fast. Uses more memory, and `next dev` serves dev-only endpoints;
  do not leave it running as the live app.

Logs go to `backend/logs/uvicorn_dev.log` and `frontend/logs/next_dev.log`
(which also holds the prod build output; the `_dev` in both filenames is
historical), each server in its own process group. Runs in the
foreground with prefixed `[backend]`/`[frontend]` log lines; Ctrl-C stops
both cleanly. Success looks like both `Waiting for backend...` /
`Waiting for frontend...` lines resolving to `... is up.` — if the backend
one times out, the preflight/DB/FMP checks already ran, so the problem is
almost always in `uvicorn`'s own startup (check the log path printed in
the failure message).

**Bind address.** Both servers listen on `127.0.0.1` only (backend `:8002`, frontend `:3100`); the app is
not exposed on any public interface and is reached through an SSH tunnel (`ssh -L 3100:127.0.0.1:3100 <host>`,
then open `http://localhost:3100`). The binds change only by env var: `BACKEND_HOST` / `BACKEND_PORT` and
`FRONTEND_HOST` / `FRONTEND_PORT` (`bin/common.sh`). `frontend/package.json`'s `dev` / `start` scripts also
carry `-H 127.0.0.1`, so a bare `npm run dev` is loopback-only too. `next.config.ts` still proxies `/api/*`
to `http://localhost:8002`. Cron jobs call the DB and FMP directly and never use either port. Check with
`ss -ltnp | grep -E ':(8002|3100)'`: both must show `127.0.0.1`.

`./bin/stop.sh` stops both servers via the PID files `start.sh` wrote to
`.run/` — safe to run anytime, including when nothing is running (prints
"nothing to stop" per service, exits 0). Use this from a second shell, or
after a `start.sh` session was disconnected without a clean Ctrl-C.

**Request guard and API docs (2026-10-13).** The app has no login and is reached through an SSH tunnel, so
`core/request_guard.py` (installed in `core/main.py`) protects it from the browser side:

- **Host check, every request:** the `Host` header must be `localhost`, `127.0.0.1` or `[::1]` on port `8002`
  or `3100`, else 400 (stops DNS rebinding). `/api/health` stays public and GET-only.
- **Cross-site check, every request except GET/HEAD/OPTIONS:** an `Origin` must be one of
  `http://localhost:3100` / `http://127.0.0.1:3100`; a request with no `Origin` must carry a non-empty
  `X-Fathom-Request` header (the frontend's `lib/api/client.ts` adds it to every call) and, if it has a
  `Referer`, an allowed one. Otherwise 403.
- **Tunnel on another local port or hostname?** Set `ALLOWED_ORIGINS` (comma-separated origins),
  `ALLOWED_HOST_PORTS` and/or `ALLOWED_HOSTS` in the environment (or `backend/.env`). `bin/start.sh` derives the
  ports and origins from `BACKEND_PORT` / `FRONTEND_PORT` unless they are already set.
- **A script or curl that writes to the API** (rare; cron jobs never use the API) must send
  `-H 'X-Fathom-Request: 1'`. A 403 from a write you expected to work is almost always this.
- `/docs`, `/redoc` and `/openapi.json` return 404. `ENABLE_API_DOCS=true` (dev shell or `.env`, read at process
  start) turns them back on.

**Security headers (2026-10-13).** `frontend/next.config.ts` sends a Content-Security-Policy, `X-Frame-Options:
DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` and a `Permissions-Policy` on every page,
and `X-Powered-By` is off. No HSTS (plain http over the SSH tunnel). The CSP allows only this origin, with
`'unsafe-inline'` for scripts (Next's bootstrap scripts) and styles (chart style attributes) and `'unsafe-eval'`
only under `next dev`. If a page or chart goes blank after a frontend change, open the browser console: a
"Refused to ..." line names the directive to adjust in `next.config.ts`.

**File permissions (2026-10-13).** `backend/.env` (the FMP key), `backend/fathom.db` and its `-wal` / `-shm`
sidecars are mode `0600`, `backend/backups/` is `0700` and every file in it `0600`. SQLite gives the sidecars the
main file's mode, so they stay `0600` while `fathom.db` is. `pipeline.backup_db` creates its temp copies and
finished backups at `0600` and re-tightens the directory on every run, so the modes survive whatever umask cron
runs with. If a restored or copied DB lands with looser modes: `chmod 600 backend/.env backend/fathom.db*` and
`chmod 700 backend/backups; chmod 600 backend/backups/*`.

**Pausing the FMP subscription** (no restart, no `.env` edit): Settings > FMP data groups >
"FMP master switch" (below the group table), or from a shell

```
cd backend
uv run python -m pipeline.data_groups status      # per-group state
uv run python -m pipeline.data_groups pause-all   # master OFF: cache-only everywhere, nothing wiped
uv run python -m pipeline.data_groups resume      # master ON (per-group settings untouched)
```

Takes effect within ~5 s in every process (state is in the DB). Individual
groups (fundamentals, analyst_ratings, ...) can be toggled in Settings > FMP data groups; `start.sh`'s
FMP preflight is skipped when the master or `profile_quote` is off, and a 402
there only warns. A nightly job whose group is off records a **skipped** run
(blue dot in Scheduled Jobs, "Skipped since <date>") -- if a job shows skipped
for longer than you intended, a group is still off. See
docs/specs/fmp-data-and-bar-cache.md, "Data groups: pausing FMP", for the full mechanism, the 402 safety
net and what degrades (CLAUDE.md keeps only the standing rules).

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
| Nightly sector/industry P/E | `nightly_sector_industry_pe.log` / `_cron.log` |
| Weekly corporate-events cache (earnings/dividends/splits) | `nightly_corporate_events.log` / `_cron.log` |
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
holidays, upserting over its own rows -- harmless (the freshness check knows holidays, so no refetch happens
either; only if the XNYS calendar cannot be loaded does a holiday cost a whole-universe refetch, with a one-time
"XNYS calendar unavailable" warning in the log). **Scheduled and live** as of
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

**`nightly_corporate_events`** — **a WEEKLY job since 2026-10-14: Saturdays 6:00 AM server time (UTC)**, `0 6 * * 6` (the name is
historical: it ran nightly at 2:45 until it was disabled on 2026-10-01, about 1,165 calls per run at 406-527 requests/min, over Starter's
300/min). It refreshes the FMP-backed earnings / dividends / splits cache (`CorporateEvent`, `CorporateEventFetch`;
`data/corporate_events_data.py`) for every US-listed tracked ticker, which feeds ONLY the Chart tab's E/D markers (nothing else reads it; the
scores, the fundamentals jobs and the next-earnings date read `FundamentalsCache`'s own `earnings`/`latest` row), so a week-old cache is fine.
Three calls per ticker per run (`/earnings`, `/dividends`, `/splits`, group `corporate_events`), each asking for the **full history** and
**upserting** by (ticker, type, date) -- a stored row is never deleted because FMP omitted it (safe against a plan downgrade to a shorter
history window) -- so the first run is the backfill, a run after any downtime costs exactly a normal run, and no event is missed between runs.
The run then prunes rows whose event date is older than 4 years (`RETENTION_DAYS`, independent of FMP/plan; the log line shows `Pruned`).
**~582 tickers x 3 = ~1,750 calls, paced by the job itself at half the plan rate (150 calls/min on Starter) = about 12 minutes** (about 20 at
~1,000 tickers). Saturday 6:00 overlaps no FMP job: the last nightly FMP job (price-target) ends ~3:20, the backup 3:30-3:35, the Saturday 4:00
opportunity job uses no FMP, and the next FMP job is the Sunday 12:30 AM stale-data check. Success: `Corporate-events refresh complete.
Processed: N. With a failed endpoint: M. ... FMP calls: C. Pruned ...` in `backend/logs/nightly_corporate_events.log`. A failed endpoint keeps
that ticker's old rows for that type (listed under `Tickers with failures`); the job raises (heartbeat "failure") only if **every** ticker
failed. Skipped (real `skipped` status) while `corporate_events` is off -- the cache then keeps serving. The Scheduled Jobs page lists it under
weekly jobs ("Sat 6:00 AM", overdue after 8 days, `JOB_METADATA` + `_EXPECTED_CADENCE_HOURS`); the running backend reads those from code, so a
**backend restart** (`./bin/stop.sh` then `./bin/start.sh --prod`) is what makes the page show the weekly entry after the 2026-10-14 change.
Check it: `select event_type, count(*) from corporateevent group by 1` and `select max(fetched_at) from corporateeventfetch`. A ticker first
opened between runs has no markers until the next Saturday, or `uv run python -m pipeline.nightly_corporate_events --tickers X,Y`.
**To disable it again:** comment out its `crontab.txt` line, add a `DISABLED_CRON_JOBS` entry in `backend/core/cron_health.py` (the wiring test
fails if only one is done), then `crontab crontab.txt` from `backend/` and check `crontab -l`. **Roll back the weekly re-enable:** `git revert`
the commits and reinstall the crontab (`crontab crontab.txt`).

**`nightly_last_close_snapshot`** (1:00 AM, Phase 6a) — caches each US-listed tracked ticker's last
official close (`TickerLastClose`, latest-only; `data/last_close_data.py`), one
`/historical-price-eod/full` call each (group `daily_prices`). It is the ticker header's price
fallback: served when the live FMP quote fails or `profile_quote` is off. Success: `Last-close
snapshot complete (as of <date>). Processed: N. Written: N. Failed: M.`; a few failures (a symbol FMP
has no bars for) are normal; the job raises only if it wrote nothing at all. Skipped while
`daily_prices` is off. Weekend/holiday runs re-cache the same session idempotently (this job has no freshness
gate and always makes one call per ticker; its "as of" now names the last real session, not the holiday).

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
upserts over its own row, with no refetch (holiday-aware freshness since 2026-10-03; weekday-only fallback if the
XNYS calendar cannot be loaded). **Coverage gate:** if fewer than 97% of constituents
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

**`nightly_sector_industry_pe`** — 3:05 AM, 6 FMP calls (sector and industry snapshots for NASDAQ, NYSE, AMEX) for the last
completed trading day, upserted into `SectorIndustryPe`; ~8 s. Skipped (a real `skipped` status) while the `sector_industry_pe`
group or the master switch is off. Red when every call failed or no row was written (check whether FMP had published the
session yet); one failed call is a success with `F of 6 calls failed`. Log: `nightly_sector_industry_pe.log` / `_cron.log`.
The one-time backfill is `uv run python -m pipeline.backfills.backfill_sector_industry_pe` (idempotent, resumable, ~9 min).
Spec: `docs/specs/sector-industry-pe.md`.

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
7-day staleness window, which only controls refetching, not deletion)
**for tickers outside the tracked universe only** (since 2026-10-20: a
tracked stock or ETF keeps its last-known rows whatever their age; the dead
`treasury_rates` type is still age-pruned for everyone).
Success: a log line `FundamentalsCache: N row(s) older than 180 days
deleted; K spared (tracked ticker).` in `backend/logs/prune_cache.log`.
**Fail-safe:** if the tracked set cannot be built, is empty or has fewer than
100 tickers, the age rule deletes nothing, logs a warning and the run is
recorded as `skipped` with the reason (the bars trim still runs); look at
`classify_known_tickers` / the DB if that appears. `--dry-run` previews the
count without deleting. The same job also trims `SharedBarsCache` (FMP OHLCV bars)
to 6 years of `1d` / 3 years of `60m` (`clients/shared_bars_cache.py::
RETENTION_DAYS`) and logs one `SharedBarsCache: N '<interval>' bar(s) older
than D days deleted.` line per interval — a few thousand bars a week in
steady state, ~1M on the very first run after a long-unpruned cache. If the
FundamentalsCache N is unexpectedly huge, check the tracked universe
(docs/specs/tracked-universe.md) before anything else: a ticker wrongly
classified `browsed`/`expired`/`untracked` is eligible for pruning.

**`backup_db`** — writes a compressed, timestamped snapshot of
`fathom.db` to `backend/backups/` (gitignored, not synced anywhere else
— this is on-disk-only insurance, not an off-site backup) via SQLite's
own `Connection.backup()` API, then prunes with a tiered retention rule
(changed 2026-09-21 from a flat "last 14"; the daily tier went from 7 to 3 on 2026-10-03): the **newest 3 backup dates**
(daily tier, `BACKUP_KEEP_DAILY`) plus **4 weekly copies** from before that window (weekly tier, `BACKUP_KEEP_WEEKLY`)
— 7 dates at steady state, reaching back ~5 weeks. A week's copy is that
ISO week's (Mon–Sun) last backup: the Sunday one normally, the latest
earlier day if a Sunday run failed. Both tiers count backups actually on
disk, not calendar days, so a multi-day outage never shrinks retention below
3 copies. Every file on a **daily-tier** date is kept (a manual same-day re-run doesn't
displace anything); a **weekly-tier** date keeps only its newest file (2026-10-20); files that don't match `fathom_YYYYMMDD_HHMMSS.db.gz`
exactly are never pruned.
**Saturday runs twice (2026-10-20):** a second crontab line runs `pipeline.backup_db` at **Saturday 04:15 UTC (12:15 Hong Kong)**, 15 minutes after the
04:00 weekly opportunity job (which takes ~15 s) so the list, which cannot be rebuilt (`TrendAnalysis`/`TickerScore` are overwritten nightly), is in a backup
the same morning instead of from Monday 03:30. Same module, same lock file (`backup_db.lock`, so two backups never run at once), same log and heartbeat name,
same 1.25x pre-check; it takes ~2-5 min and the next scheduled job that morning is the 06:00 corporate-events refresh. Retention is by date: Saturday's two
files stay together while Saturday is one of the newest 3 dates (Saturday 04:15 to Tuesday 03:30) and are then pruned with it, because Sunday's 03:30 backup is the
ISO week's last and so the weekly copy; if Sunday's run fails, Saturday becomes the weekly copy and only its 04:15 file is kept. **Files on disk: 7 at steady
state, 8 from Saturday 04:15 until Tuesday 03:30, never more; at ~160 MB each that is ~1.1 GB (7) to ~1.3 GB (8), plus ~1.6 GB of temporary space while a run is going.** Tunable via `BACKUP_KEEP_DAILY`/`BACKUP_KEEP_WEEKLY`
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

### Statement recheck (2026-10-05)

After its normal pass the 2:00 fundamentals job refetches the three **quarterly** statements of tickers whose newest cached
rows look wrong or never landed (spec: docs/specs/statement-data-quality.md, section 5). What you will see:

- **Message** gains `, recheck: S selected, H healed, F still flagged, G gave up, D deferred` (and `, N guard hit(s)`) on a night
  something happened. Informational; the job does not go red for it. `D deferred` > 0 means more than 20 tickers were due (60-call cap).
- **Log** (`nightly_fundamentals_fetch.log`): one `Statement recheck TICKER: trigger ..., attempt N, rules before -> after, filingDate
  ... before -> after, result ...` line per recheck, `Statement recheck scan TICKER: new|healed|gave_up|...` for state moves, a
  warning per regression-guard veto, an info line when the cap defers tickers.
- **Derived rows (2026-10-06):** on the night a ticker turns `healed` the job also refetches `key_metrics`/`ttm` and `ratios`/`ttm`
  (`/key-metrics-ttm`, `/ratios-ttm`; 2 calls, not recheck attempts, outside the 60-call cap, own cap of 80 calls). Message clause
  `, derived rows: W written for N healed ticker(s) (C calls[, F not written])[, D deferred]`; log line `Statement recheck TICKER:
  derived rows, ...`. A row left `not written` (blocked, failed or empty answer) keeps its old content and stamp; the ticker stays healed.
- **State** is table `RecheckState` (one row per ticker): `SELECT ticker, trigger, anchor_date, status, attempts, last_attempt_at,
  last_result, days_to_heal_from_anchor FROM recheckstate ORDER BY status, anchor_date;` (`days_to_heal_from_anchor` is the heal-time evidence).
- **Nothing happens while the `fundamentals` group or the master switch is off** (the job is `skipped`), and a blocked/402/failed
  call is never counted as an attempt. A `last_result` of `blocked`/`error`/`empty` that persists for a ticker means its calls are not
  getting through: check the data-group page and the log's FMP errors.
- **Rollback:** the feature only adds fetches of rows the app already caches; to stop it, stop the job or comment out the
  `run_statement_recheck` call in `pipeline/nightly_fundamentals_fetch.py`. `RecheckState` can be dropped/emptied at any time (the
  next run re-seeds it from the cache; rows already past their 60-day window are re-recorded as `gave_up` and never retried).

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

### Cron overlap protection (2026-10-13)

Every active line in `crontab.txt` runs under `flock -n -E 99` on its own lock file, `backend/logs/locks/<job>.lock` (gitignored with `logs/`; `mkdir -p logs/locks` is part of each line, so a fresh checkout works). If the previous run of the **same** job still holds the lock, the new run does not start: it appends one line to that job's own `*_cron.log` (`<UTC date> skipped <job>: the previous run is still going`) and the cron line exits 0. Exit code 99 is flock's "busy" code, so a job that fails by itself (any other code) is never mistaken for a skip, and the lock is released however the job ends. Different jobs never block each other. A skipped run writes no `CronRunLog` row (the job never started), so the Scheduled jobs page shows that run as missing until the next one; to see skips: `grep -h "skipped" backend/logs/*_cron.log`. A stuck lock needs no cleanup (it lives in the kernel and dies with the process); to see who holds one: `fuser backend/logs/locks/<job>.lock`. No script locks on its own (`tests/test_cron_overlap.py` checks), so nothing is double-locked. **After editing `crontab.txt`, reinstall and compare:** `cd backend && crontab crontab.txt && crontab -l | diff crontab.txt -` must print nothing; install between runs, not while a job is mid-run (`pgrep -fa "python -m pipeline"`).

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

**Interrupted runs (2026-10-09).** `cron_heartbeat` catches `BaseException`, not only `Exception`, so a run that is
stopped rather than failed also closes its row (it used to stay `running` forever; row 265, `nightly_market_breadth`,
started 2026-09-23 15:44, was left open by an interrupted manual re-run). What is recorded, always followed by a re-raise
of the original exception (exit code and traceback unchanged):

| How the run ends | Row | `error_summary` |
|---|---|---|
| normal return, `SystemExit(0)` / `SystemExit(None)` | `success` (or `skipped` after `run.skip`) | the run's message |
| ordinary exception | `failure` | `ValueError: ...` (unchanged) |
| Ctrl-C (`KeyboardInterrupt`) | `failure` | `interrupted: KeyboardInterrupt` |
| `sys.exit(N)`, N non-zero or a string | `failure` | `exited with code N` |
| `kill <pid>` / service stop (SIGTERM) | `failure`, process exits 143 | `interrupted: SIGTERM (exit code 143)` |
| `kill -9`, the OOM killer, power loss (SIGKILL) | stays `running` (cannot be caught) | none |

SIGTERM is covered by a temporary handler the heartbeat installs only in the main thread and only while SIGTERM still has
the default action (it never replaces a handler the job set, and restores the previous one on exit). The finish write is
best effort: if it fails (locked DB, closed engine) a WARNING naming the job is logged and the original exception still
propagates. A stale `running` row can therefore still appear after a SIGKILL; find one with
`SELECT id, job_name, started_at FROM cronrunlog WHERE status='running' AND finished_at IS NULL`, and close it with one
`UPDATE ... WHERE id = <id> AND status = 'running' AND finished_at IS NULL` (status `failure`, `finished_at` = `started_at`,
so no duration is implied). Row 265 was closed that way on 2026-10-09 ("Stale row closed manually 2026-10-09: ...").

`GET /api/config/cron-health` computes each job's `health_status` from its
`CronRunLog` history: `"failed"` if the most recent row failed, `"unknown"`
if no row exists yet, `"overdue"` if no successful run falls within that
job's expected cadence (36h for the 6 daily jobs, ~8 days for the 7
weekly-Sunday jobs, ~35 days for the 2 monthly ones — `core/cron_health.py`'s
`_EXPECTED_CADENCE_HOURS`), else `"ok"`. **Last failure (2026-10-20):** each job also carries `last_failure`, its latest `CronRunLog` row with status `failure` that started in the last
14 days (`LAST_FAILURE_WINDOW_DAYS`), whatever the latest run is, so a success the next night no longer hides it (Sunday 2026-10-18's backup failure vanished from the page on Monday). It is display only
(`_attach_last_failures` runs after `_job_health` and sets nothing else; the status, message and overdue rule are untouched), read in one query, and `null` for a job with no failure in the window. The page shows a
quiet tertiary "Last failure 2026-10-18 03:30 UTC: <message>" line under the job's message (message cut at 140 characters, full text on hover; the stored UTC time is shown as is), and not on a row whose latest run
is that failure. Settings > Scheduled Jobs
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
failed, C FMP calls, D min"; BB+RSI and Warren "N computed, F failed, S swept, P pruned, K still stale after fetch"; score recompute "N
scored, S skipped (no cached profile), F failed" (skips are not in the denominator); backup "X MB, N old
backup(s) pruned" (no threshold: any error raises). Limits: fundamentals only counts an exception that escapes a
ticker's refresh -- most per-statement FMP errors are swallowed inside `get_stepN_data` (`safe_fetch`) and are
invisible to this count. What to do when a run goes red on the threshold: the red text starts with the normal
counts and ends "-- N% failed (limit 5%)" or "-- all N attempted failed"; the per-ticker reasons are in the
job's own `backend/logs/<job>.log` ("Tickers with failures: ...").

**Stale count on the two 2h signal jobs (2026-10-03).** BB+RSI and Warren run `stale_ticker_count(tickers, "60m")` right after their bars read and report the result as "K still stale after fetch" (message, run summary, and "Stale: K." in the log line), the same guard the daily-bar jobs use. K is how many monitored tickers' newest cached 60m bar is older than the most recently completed bar (an FMP error or empty answer leaves the old bars in place, so the job still computes and reports success on them). It is informational: it never feeds the failure threshold, and a stale ticker is still computed. The 60m freshness check knows market holidays and early closes (2026-10-03: the XNYS calendar, `pandas_market_calendars`; the last expected bar is 12:30 after a 13:00 close), so K no longer jumps on those nights; non-US tickers are left out of K (they never get 60m bars). Two things can still make K jump across the whole watchlist: an **unscheduled closure** (a market closed at short notice is unknown to the calendar until the library is upgraded: `uv lock --upgrade-package pandas-market-calendars && uv sync` from `backend/`, and the 60m jobs refetch once that night), and the calendar failing to load (the log shows one "XNYS calendar unavailable" warning and the check reverts to weekday-only logic until fixed). The DAILY-bar jobs' stale counts are still not holiday-aware and do jump on a holiday. Any other non-zero K: check the job's own log for "FMP intraday fetch failed for <ticker>" lines.

A job commented out of the crontab on purpose goes in `core/cron_health.py::DISABLED_CRON_JOBS` (job -> date + reason): it stays in
`CRON_JOB_NAMES`, shows as "Skipped — Disabled since <date>: <reason>" instead of aging into Overdue, and `test_cron_wiring.py`
requires it to be absent from `crontab.txt`. Currently: none (`nightly_corporate_events` was disabled 2026-10-01 and is weekly again since 2026-10-14).

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
(`TickerView.last_viewed_at`, touched at the start of the request, read-first: a ticker already touched today issues no write, at most one write per ticker per day) but never admits it. `GET/POST/DELETE
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
tickers that were then in the universe only through a view as added (pre-write snapshot `backend/backups/pre_universe_step2_20261003.db.gz`, since deleted 2026-10-04: the nightly backups cover the later state); its script was removed
at the flip.

**Roll back the flip:** revert the flip commit and restart (the `added_at` / `added_source` columns are inert for the old code; no table changed). Under the old rule any
view in the last 30 days admits a ticker again, and the 25 grandfathered tickers are in through their (seed or real) views until about 2026-11-01. A cleared delisted flag is
restored with `UPDATE tickerscore SET delisted_at = datetime('now') WHERE ticker = '...'`.

## Weekly opportunity snapshot (built 2026-10-11, cron enabled 2026-10-12)

Spec: `docs/specs/opportunities.md`. `uv run python -m pipeline.weekly_opportunity_snapshot [--as-of D] [--force] [--dry-run]` from `backend/`: reads stored data only (zero FMP
calls), about 12 s and 175 MB peak, writes `OpportunityRun` + `OpportunitySnapshotRow` (both KEEP in the table registry, both in the nightly backup, which copies the whole database).
Scheduled Saturdays 04:00 server time (UTC; noon in Hong Kong) in `crontab.txt`, weekly cadence in `core/cron_health.py` (overdue after 8 days); first scheduled run Saturday 2026-10-17. Disable/enable steps are in the spec ("Cron status"). A rerun for the same as-of date is a
no-op; `--force` replaces that run in one transaction. It refuses to write when fewer than 90% of the gate-passing tickers have a Weinstein row from the as-of bar (the nightly 1:05 job has
not caught up): check `CronRunLog` for `pipeline.nightly_trend_calculation` first. **Roll back a run:** `DELETE FROM opportunityoutcome WHERE run_id = N; DELETE FROM opportunitypoolrow WHERE run_id = N; DELETE FROM opportunitysnapshotrow WHERE run_id = N; DELETE FROM opportunityrun WHERE id = N;`
(tickers it listed drop out of the 180-day `opportunity` protection with it). The run now also writes its pool (`opportunitypoolrow`, every gate-passing ticker); `--force` deletes the run's pool and outcome rows with it and never touches `opportunitypick` (keyed by as_of_date; nothing deletes a pick).

**Outcome updater (scheduled nightly 03:40 UTC, 2026-10-12):** `uv run python -m pipeline.opportunity_outcome_update --once` (or `--dry-run`, `--run-id N`, `--as-of D`) from `backend/`: zero FMP calls, seconds and about 130 MB peak, a no-op (green heartbeat) unless SPY has a new bar. In `crontab.txt` and `CRON_JOB_NAMES` (daily, 36 h); log `logs/opportunity_outcome_update_cron.log`; its own result per run is a row of `opportunityoutcomerun`. Pause it by commenting the crontab line, adding a `DISABLED_CRON_JOBS` entry and running `crontab crontab.txt`. Details: `docs/specs/opportunities.md`, "Outcome tracking".

## Score recompute job (2026-10-06)

Saving or resetting the score weights, saving the Narrow moat multiplier and Settings/Screener "Recompute all scores" all start one
**background full recompute**: `python -m pipeline.score_recompute_job <run_id>`, a subprocess the API launches (own session, so a
`uvicorn --reload` does not kill it), cache only, zero FMP calls, ~40 s for the ~580 tracked tickers (about 4 s of it for 30). It
re-scores every ticker through `compute_ticker_score` at the saved weights and stamps `TickerScore.weights_version`.

- **Status:** table `ScoreRecomputeRun` (state running/done/failed, trigger, processed/total/failed, weights_version, error, heartbeat);
  the newest row is the status, also returned as `recompute` by `GET /api/config/score-weights`. Log: `backend/logs/score_recompute_job.log`
  (the worker's own) and `score_recompute_job_cron.log` (its stdout/stderr).
- **One at a time.** A second request while a run is `running` gets **409** and is not queued; a weights/Moat save is refused before
  anything is saved. A `running` row whose worker has not reported for 120 s, or whose process exited without finishing, is marked
  `failed` automatically, so a dead worker never blocks the next run.
- **Worker lifecycle (2026-10-13).** When a run is reaped (no heartbeat for 120 s, or running longer than `SCORE_RECOMPUTE_TIMEOUT_SECONDS`,
  default 3600 s, 0 = no limit) and its worker is still alive, the API **terminates it**: SIGTERM at once, SIGKILL after 5 s, on a background
  thread, and only after `/proc/<pid>/cmdline` (or `ps` where there is no /proc) shows the stored pid still runs
  `python -m pipeline.score_recompute_job <that run's id>`, so a reused pid is never signalled (log line `reaped recompute run N: worker pid P -> terminated|killed|not-ours`).
  The worker writes its heartbeat every 10 s or every 10 tickers, stops itself with a failed run at the time limit, and stops without writing
  `done` when its row is no longer `running`.
- **A failed run** keeps the saved weights; the stored rows simply stay on the older `weights_version` where the worker did not reach
  them (each score row is one atomic upsert, so none is ever half written). Retry with Screener > "Recompute all scores", or
  `uv run python -m pipeline.recompute_ticker_scores` (the old script, unchanged, still runs inline and cache-only).
- **Stuck `running` row you want gone now:** `UPDATE scorerecomputerun SET state='failed', error='manual', finished_at=datetime('now') WHERE state='running';`
- **The weights themselves** live in table `scoreweightsettings` (one row, key `default`, `weights_version`). Never edit it by hand in normal use
  (Settings > Score weighting validates it). To go back to the defaults with the API down: delete the row (the next read serves the
  defaults at version 1 and the next save re-seeds it), then run `uv run python -m pipeline.recompute_ticker_scores`.
- **Not a cron job:** the nightly `nightly_score_recompute` (3:25) is separate and not coordinated with it; it also writes the current
  `weights_version`, so a weights change made while it runs only leaves the rows it had already passed on the older version until the
  next run.

## Database locking (2026-10-04) and WAL (enabled 2026-10-04)

One SQLite file (`backend/fathom.db`), journal mode **WAL** since 2026-10-04 (it was `delete` before; see "WAL" below). Every connection that writes goes through
the one engine in `core/db.py`, whose busy timeout is `SQLITE_BUSY_TIMEOUT_SECONDS` = **15 s** (sqlite3's `timeout`; before 2026-10-04 it was sqlite3's own 5 s).
`PRAGMA busy_timeout` on that engine reads back 15000 (pinned by `tests/test_view_touch_read_first.py`). Read-only engines (`pipeline/wipe_untouched_tickers.py`'s
dry run, `pipeline/cache_history_audit.py`, the ad-hoc research scripts) open the file `mode=ro`; `pipeline/backup_db.py` uses raw `sqlite3` connections (the backup
API on the live file, a private temp file as destination) and keeps the 5 s default.

**What a "database is locked" error means now:** under WAL readers never block writers and writers never block readers, so the remaining case is **two writers at
once**: another connection held the single write lock for longer than the timeout (15 s). Before WAL (journal mode delete) a writer also blocked readers while it
committed and a long reader (the 03:30 UTC backup) blocked a commit; that was the 2026-10-03 SOXL incident (first seen 2026-08-06 03:30 too). Most request
handlers are `async def` and call the synchronous session on the event loop's single thread, so a lock wait also freezes the whole API for up to the timeout, which
is why it is 15 s and not larger.

**What to do:** a one-off error needs nothing (the view touch is best-effort and a later call retries; `grep -n 'failed for' logs/uvicorn_dev.log`). Repeats at a
pattern of times point at the second writer: a manual script writing to the live file, or a long nightly transaction. The touch writes at most once per ticker per
day (read-first, docs/specs/tracked-universe.md, "State and recording a view"). The first `wipe --apply` takes many short write transactions (one `BEGIN
IMMEDIATE` per ticker): run it outside the 00:00-03:40 UTC chain.

## WAL (enabled 2026-10-04)

**What it is.** In WAL (write-ahead log) mode a commit is appended to a side file, `fathom.db-wal`, and copied into `fathom.db` later by a "checkpoint"; readers
see a consistent snapshot and do not block the writer (and vice versa). The mode is stored in the database file itself, so it survives restarts.

**The files.** While any connection is open there are `backend/fathom.db-wal` (the log; 0 bytes right after a checkpoint, normally a few MB, up to tens of MB
during the nightly chain) and `backend/fathom.db-shm` (32 KB shared-memory index; never grows). When the last connection closes, SQLite checkpoints and deletes
both. They are not in git (`.gitignore`: `*.db`, `*.db-wal`, `*.db-shm`). Never delete them by hand while the app runs, and never delete a `-wal` next to a `fathom.db` you want to keep: committed
data may only be in the `-wal`.

**Copying the file safely.** A plain `cp fathom.db somewhere` of a live WAL database can lose committed data (it is in the `-wal`). Either use SQLite's backup
API, which is what `pipeline/backup_db.py` does (the nightly backup is safe and needs no change):

    python3 - <<'PY'
    import sqlite3
    src = sqlite3.connect("backend/fathom.db"); dst = sqlite3.connect("/path/to/copy.db")
    src.backup(dst); dst.close(); src.close()
    PY

or stop the app and every job, then copy `fathom.db`, `fathom.db-wal` and `fathom.db-shm` together. Read-only access (`sqlite3.connect("file:backend/fathom.db?mode=ro",
uri=True)`) is safe at any time and needs the directory to be writable (it creates `-shm`). A one-off snapshot: the same backup API call, then gzip (the snapshot taken before the switch,
`pre_wal_20261004.db.gz`, was since deleted 2026-10-09 once the first weekly backup copy existed).

**Check it:** `python3 -c "import sqlite3;c=sqlite3.connect('file:backend/fathom.db?mode=ro',uri=True);print(c.execute('PRAGMA journal_mode').fetchone())"` should print
`('wal',)`; `ls -la backend/fathom.db*` shows the `-wal` size; `PRAGMA wal_checkpoint(PASSIVE)` (returns busy, log frames, checkpointed frames) is a safe manual
checkpoint. Each app and cron start logs the mode (`core/db.py::_log_journal_mode`, from `init_db`): INFO `journal_mode=wal` (visible in the cron job logs; the dev
server's uvicorn log does not show app INFO lines) or a WARNING `journal_mode=<other>, expected wal` that does appear in the uvicorn log.

**Expected size behaviour.** SQLite checkpoints automatically when the log passes 1000 pages (about 4 MB) and no reader is in the way, so the `-wal` normally stays
small. A **long reader delays checkpoints**: the 03:30 UTC `backup_db` run holds a read snapshot for the whole copy (a few seconds to a minute), so the log keeps
growing during it and shrinks at the next checkpoint after it. Heavy bulk writes (nightly fundamentals, bar replaces) can push it to tens of MB; it does not
affect correctness. A `-wal` that keeps growing for days means a connection is holding an old snapshot open (find it with `lsof backend/fathom.db`); restarting
the app and any stuck job releases it.

**Morning check after the first nightly chain on WAL** (and any time something looks off): (1) `journal_mode` reads `wal`; (2) `ls -la backend/fathom.db*`: the
`-wal` is small (under about 100 MB) and the `-shm` is 32 KB; (3) `backup_db` succeeded (`GET /api/config/cron-health` or `CronRunLog`: status success, message
"... MB, N old backup(s) pruned") and `gzip -t backend/backups/fathom_<date>_033*.db.gz` passes, size within a few MB of the previous night's; (4) every cron job
`ok`; (5) `grep -c 'database is locked' backend/logs/*.log` shows nothing new.

**Rollback to the old mode.** Stop the app (`./bin/stop.sh`) and make sure no job runs (`lsof backend/fathom.db` empty), then in one Python process:
`c = sqlite3.connect("backend/fathom.db", timeout=30); c.execute("PRAGMA journal_mode=DELETE")` (it must return `delete`; it fails while any other connection is
open) and restart. The `-wal`/`-shm` files disappear. Tested on a temp database (`tests/test_wal_compat.py`). Switching to WAL is the same call with
`journal_mode=WAL` (also needs exclusive access: stop the app and jobs first). **Restoring an old backup** (`gunzip` one of `backend/backups/fathom_*.db.gz`; the earlier
`pre_wal_20261004.db.gz` was since deleted 2026-10-09) gives a file in the mode it had when it was taken: backups from before 2026-10-04 are `delete`, later ones `wal`. After restoring a
`delete`-mode file, re-enable WAL with the call above (the startup WARNING reminds you).

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

## Login accounts (security step 3, 2026-10-13)

Every `/api` route except `GET /api/health` and `POST /api/auth/login` needs a signed-in session (docs/specs/auth.md). Accounts are created **only** with the CLI, run from `backend/`:

```
uv run python -m core.auth_cli create-user <name> --role admin|viewer   # password: prompt (typed twice) or one line on stdin
uv run python -m core.auth_cli set-password <name>                       # ends that user's sessions, clears a login lock
uv run python -m core.auth_cli disable <name>  |  enable <name>          # a disable ends that user's sessions
uv run python -m core.auth_cli delete-user <name> [--yes]                # removes the account and its sessions; audit rows kept; refuses the last active admin
uv run python -m core.auth_cli list                                      # role, active, sessions, last login, lock; never a hash
uv run python -m core.auth_cli revoke-sessions [<name>]                  # no name: every session (everyone signs in again)
```

Passwords are never read from argv (12 characters minimum). Piped form: `printf '%s\n' "$PW" | uv run python -m core.auth_cli create-user alice --role admin`.
The CLI creates the three auth tables (`user`, `usersession`, `auditlog`) if they are missing, so it works before the app has restarted on this code; `init_db()` creates them
too but **never seeds a user** (cron jobs call it).

**First admin (the app is locked to everyone until one exists):** 1. `./bin/stop.sh` and `./bin/start.sh --prod` (picks up the code). 2. `cd backend && uv run python -m core.auth_cli create-user <you> --role admin`
(type the password twice). 3. `uv run python -m core.auth_cli list` shows it. 4. Sign in at `http://localhost:3100/login` (frontend step 4, 2026-10-13; the same page ends the session with Sign out in the top bar) or, for a script, see "Scripts and curl" below. The `/login` page needs the frontend rebuilt (`./bin/start.sh --prod` does a `next build`). A `viewer` sees every page read-only: no Add to watchlist, Refresh, Settings Save, Recompute, Moat or Custom valuation edits, and Scheduled jobs / FMP data groups are not listed.
**Deleting an account:** `delete-user <name>` asks you to type the name again (`--yes` skips that; piped, it reads the name from stdin). It deletes the user and that user's sessions in one transaction, keeps every `auditlog` row and adds a `user_deleted` row (`select ts, username, event from auditlog where event = 'user_deleted'`). It refuses the last active admin (create or enable another first) and an unknown name. The name can be created again afterwards as a new account. No restart is needed: the CLI works on the database whether or not the app is running.
If every admin is locked out or forgot the password: `set-password <name>` (it also clears the lock); the CLI works whether or not the app is running.

**Scripts and curl.** A write needs a session cookie **and** the `X-Fathom-Request` header (the request guard). With a cookie jar:
`curl -c jar -H 'X-Fathom-Request: 1' -H 'Content-Type: application/json' -d '{"username":"alice","password":"..."}' http://localhost:8002/api/auth/login`, then
`curl -b jar -H 'X-Fathom-Request: 1' -X PUT ... http://localhost:8002/api/...`. Cron jobs, `pipeline/`, `scripts/` and the Moat-check pipeline read and write the database and call FMP directly,
never the HTTP API, so none of them needs a login. `bin/start.sh` polls `GET /api/health`, which stays public.

**Settings (env vars, read at start).** `SESSION_IDLE_DAYS` (7), `SESSION_ABSOLUTE_DAYS` (30), `SESSION_COOKIE_SECURE` (false: leave it off on plain `http://localhost`, Safari discards Secure cookies there; turn it on only behind TLS),
`LOGIN_MAX_FAILURES` (5 wrong passwords lock a user), `LOGIN_LOCKOUT_MINUTES` (15), `LOGIN_SOURCE_MAX_FAILURES` (30) in `LOGIN_SOURCE_WINDOW_MINUTES` (15), `VIEWER_CHART_CACHE_SECONDS` (60).
A lockout is temporary by design; `set-password` clears it immediately. Behind the SSH tunnel every request comes from 127.0.0.1, so the per-source limit is one global limit.

**Audit log.** `auditlog` has one row per non-GET request outcome and per login event (never a body, password, token or hash). Read it with
`sqlite3 -readonly fathom.db "select ts, username, method, path, status, event, ip from auditlog order by id desc limit 50"`; a run of `login_fail` / `lockout` / `login_blocked` rows is someone guessing passwords.
**Pruning (2026-10-13):** the weekly job `pipeline.prune_audit_log` (Sundays 12:40 AM UTC, under flock like every cron line) deletes `auditlog` rows older than `AUDIT_RETENTION_DAYS` (default 180) and logs `Pruned N audit log row(s) older than D day(s).` in `backend/logs/prune_audit_log.log`; by hand (any time, the app can stay up): `uv run python -m core.auth_cli prune-audit [--days N]` (`N` at least 1; prints the count). Only the audit table is touched, never a user or a session. No manual `delete from auditlog` is needed any more.
Viewers (role `viewer`) are read-only, see tracked tickers only and are served from cached data; their `/chart` loads come from a 60-second in-memory cache. Docs: docs/specs/auth.md.

## Disk space (2026-10-06 and 2026-10-09 investigations)

The repo, `backend/backups`, the caches under `~/.cache`, `~/.npm` and `~/.vscode-server`, and the OS share one ext4 volume (about 25 GB). `backup_db` refuses to run
below 1.25 x the DB size free (about 1.67 GB at a 1.33 GB DB); a refusal is a failed `pipeline.backup_db` cron job with no new restore point.
Causes of sudden drops seen so far: a new ~650 MB VS Code server per update that stays on disk (four were present on 2026-10-09; old ones are removed by hand); ad-hoc pre-change DB snapshots
(~150 MB each) in `backend/backups`, `~/scratch` and `$HOME`; the frontend `.next/dev` cache (about 1.4 GB, growing about 125 MB/day); the npm, uv and Playwright caches.
Backup tiers: 3 daily + 4 weekly (`BACKUP_KEEP_DAILY`/`BACKUP_KEEP_WEEKLY`), about 160 MB each, 7 files at steady state, 8 from Saturday 04:15 to Tuesday 03:30 (the Saturday second backup); each weekly copy adds ~160 MB until then.
**Early warning (2026-10-20):** `pipeline.disk_space_check` runs daily at **03:28 UTC** (after the 03:25 recompute, 2 minutes before the backup) and records the free space on the volume holding `fathom.db`
(`os.statvfs`, decimal GB, the figure `backup_db` uses; reads only, no FMP call, nothing written but its heartbeat row). Warn **below 3.5 GB** (about twice the backup's real peak, DB copy plus its gzip),
hard **below 2.0 GB** (just above the 1.25x pre-check, 1.76 GB at a 1.41 GB DB). `cron_heartbeat` has no partial/amber status (decisions 2026-10-02 rejected a warning health value), so: healthy = success
"6.9 GB free on the database volume (warn below 3.5 GB, hard limit 2.0 GB)."; the **first** night below 3.5 GB = still a success, message "Low disk warning: 3.1 GB free, below the 3.5 GB warn threshold (night 1 of 2; hard limit 2.0 GB)."
(green pill, the message names it); a **second night in a row** below 3.5 GB (the job's previous run started within 36 h and said "Low disk") or **any night below 2.0 GB** = failure, the red row.
A good night resets the streak. Its log is `backend/logs/disk_space_check.log` / `_cron.log`. When it goes red: free space first (`du -x --max-depth=2 -h /home/shen | sort -h | tail`; old VS Code servers, `~/.cache/uv`, `.next/dev`, ad-hoc snapshots), then check the backup ran.
Check: `df -h /`, `du -x --max-depth=2 -h /home/shen | sort -h | tail`, `journalctl --disk-usage`.
Delete an ad-hoc snapshot once its change is recorded in `docs/decisions.md`. Clearing `frontend/.next/dev/cache` needs the dev servers stopped (`./bin/stop.sh`).
`uv cache prune` is not safe while the dev backend runs (shared lock, no dry-run).

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
- **Removed 2026-10-20:** the SEC EDGAR cross-check and the on-demand Financials cell lookup (next two items) no longer exist (`docs/decisions.md`, 2026-10-20). The text below is kept as history; `get_step5_data` has no `allow_sec_cross_check` flag any more, and the cached `sec_company_facts` rows stay in the database until a separate cleanup.
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
News-Sentiment references, `STEP_WEIGHTS` (and, since 2026-10-07, the Moat multipliers) match byte-for-byte
between `backend/scoring/overall.py` and `frontend/lib/overallScore.ts`,
and the FMP pause mechanism (superseded 2026-09-24 by per-group data toggles) was all in place as CLAUDE.md describes -- not
re-run for this pass, carried forward as still current.
