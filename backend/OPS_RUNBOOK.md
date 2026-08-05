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
| Weekly S&P 500 list refresh | `sp500_list_refresh.log` / `_cron.log` |
| Weekly Dow list refresh | `dow_list_refresh.log` / `_cron.log` |
| Cache pruning | `prune_cache.log` / `_cron.log` |
| Log rotation | `rotate_logs.log` / `_cron.log` |
| Fixture-contamination audit | `_cron.log` only — the script itself prints to stdout rather than calling `configure_logging()`, so there's no separate plain `.log` file, just the cron redirect |
| Stale-data health check | `stale_data_health_check.log` / `_cron.log` |
| Monthly price-target snapshot | `monthly_price_target_snapshot.log` / `_cron.log` |
| Daily SQLite backup | `backup_db.log` / `_cron.log` |

```bash
tail -50 backend/logs/nightly_fundamentals_fetch.log
tail -50 backend/logs/audit_fixture_contamination_cron.log   # no plain .log for this one
```

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
