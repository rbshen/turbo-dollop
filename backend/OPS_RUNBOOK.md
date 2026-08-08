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
