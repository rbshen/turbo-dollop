"""Standalone, one-time (but idempotent and reversible) migration: renames the
watchlists W1..W5 to E1..E5 so they match the monitored-watchlist rule in
data/watchlists.py (E<number> or "ETF"; see MONITORED_WATCHLIST_PATTERN).

A rename touches nothing but `watchlist.name`. Every reference to a watchlist is
by id (WatchlistTicker.watchlist_id, SavedScreenerFilter.watchlist_id, the
frontend's per-id sort key), and the signal/zone tables are keyed by ticker, so
ticker membership, history, sort preferences and saved filters carry over
unchanged. Only exact names W1..W5 are matched: "W score passed", "W6", etc.
are never touched.

Safety, in order, before any write:
  1. Preflight: if a target name (E1..E5) already exists while its source (W<n>)
     still exists, abort -- nothing is written.
  2. Logical backup of the three tables a rename can touch (watchlist,
     watchlistticker, savedscreenerfilter) to backend/backups/
     watchlist_rename_<ts>.json, re-read and checked against live row counts.
     It also records the id -> (old, new) name map that --rollback restores from.
  3. Full DB backup via pipeline.backup_db.create_backup. If it refuses (it needs
     ~1.25x the DB size free), the script stops with that message and writes
     nothing, unless --skip-full-backup is passed explicitly.
Then the renames run in ONE transaction and are re-read and verified (same ids,
same per-list ticker counts, no W1..W5 left).

Idempotent: a run that finds no W1..W5 names writes nothing (no backup either).
A run where only some lists were renamed finishes the rest.

Run (real, with both backups):
    uv run python -m pipeline.rename_monitored_watchlists

Preview without changing anything:
    uv run python -m pipeline.rename_monitored_watchlists --dry-run

Undo (renames E1..E5 back, by id, from the newest logical backup):
    uv run python -m pipeline.rename_monitored_watchlists --rollback
    (--backup-file PATH to use a specific one)
"""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import SavedScreenerFilter, Watchlist, WatchlistTicker
from pipeline.backup_db import DEFAULT_BACKUP_DIR, InsufficientDiskSpaceError, create_backup

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "rename_monitored_watchlists.log"

BACKUP_PREFIX = "watchlist_rename_"

# Exact old name -> new name. Never a pattern: only these five lists are migrated.
RENAMES: dict[str, str] = {f"W{n}": f"E{n}" for n in range(1, 6)}

logger = logging.getLogger(__name__)


class MigrationAbort(RuntimeError):
    """A preflight/backup/verification failure; nothing was (or no more was) changed."""


def plan_renames(session: Session, renames: dict[str, str] = RENAMES) -> list[tuple[int, str, str]]:
    """[(watchlist_id, old_name, new_name)] for every source name that exists. Raises
    MigrationAbort if any such rename's target name is already taken."""
    by_name = {w.name: w for w in session.exec(select(Watchlist)).all()}
    plan = [(by_name[old].id, old, new) for old, new in renames.items() if old in by_name]
    blocked = [f"{old} -> {new}" for _, old, new in plan if new in by_name]
    if blocked:
        raise MigrationAbort(f"Target name already exists, nothing changed: {', '.join(blocked)}")
    return plan


def _row_counts(session: Session) -> dict[str, int]:
    return {
        "watchlist": session.exec(select(func.count()).select_from(Watchlist)).one(),
        "watchlistticker": session.exec(select(func.count()).select_from(WatchlistTicker)).one(),
        "savedscreenerfilter": session.exec(select(func.count()).select_from(SavedScreenerFilter)).one(),
    }


def _dump(rows) -> list[dict]:
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.model_dump().items()} for r in rows]


def write_logical_backup(session: Session, plan: list[tuple[int, str, str]], backup_dir: Path) -> Path:
    """Dumps the three tables a rename can touch, plus the rename plan, to JSON, then re-reads
    the file and checks it against the live row counts. Raises MigrationAbort on any mismatch."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    counts = _row_counts(session)
    payload = {
        "created_at": datetime.now().isoformat(),
        "renamed": [{"id": i, "old": old, "new": new} for i, old, new in plan],
        "row_counts": counts,
        "watchlist": _dump(session.exec(select(Watchlist)).all()),
        "watchlistticker": _dump(session.exec(select(WatchlistTicker)).all()),
        "savedscreenerfilter": _dump(session.exec(select(SavedScreenerFilter)).all()),
    }
    path = backup_dir / f"{BACKUP_PREFIX}{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    path.write_text(json.dumps(payload, indent=1))
    reread = json.loads(path.read_text())
    if any(len(reread[table]) != n for table, n in counts.items()):
        path.unlink(missing_ok=True)
        raise MigrationAbort("Logical backup did not round-trip against the live row counts; nothing changed.")
    return path


def _apply_names(session: Session, id_to_name: dict[int, str]) -> None:
    now = datetime.now()
    for watchlist_id, name in id_to_name.items():
        row = session.get(Watchlist, watchlist_id)
        row.name = name
        row.updated_at = now
        session.add(row)
    session.commit()


def _ticker_counts(session: Session) -> dict[int, int]:
    return dict(session.exec(select(WatchlistTicker.watchlist_id, func.count()).group_by(WatchlistTicker.watchlist_id)).all())


def run_rename(
    session: Session,
    backup_dir: Path,
    full_backup: Callable[[], Path] | None,
    dry_run: bool = False,
) -> list[tuple[int, str, str]]:
    """Returns the renames performed (or, for a dry run, that would be). `full_backup` is a
    callable that takes the full DB backup (None = skipped). Nothing is written before every
    backup has succeeded."""
    plan = plan_renames(session)
    if not plan or dry_run:
        return plan

    before_counts = _ticker_counts(session)
    logical = write_logical_backup(session, plan, backup_dir)
    logger.info("Logical backup written: %s", logical)
    if full_backup is not None:
        logger.info("Full DB backup written: %s", full_backup())

    _apply_names(session, {i: new for i, _, new in plan})

    session.expire_all()
    names = {w.id: w.name for w in session.exec(select(Watchlist)).all()}
    if any(names.get(i) != new for i, _, new in plan) or _ticker_counts(session) != before_counts:
        raise MigrationAbort(f"Post-rename verification failed; restore with --rollback ({logical.name}).")
    return plan


def run_rollback(session: Session, backup_file: Path) -> list[tuple[int, str, str]]:
    """Renames back, by id, from a logical backup's rename plan. A list whose current name is no
    longer the migrated one (renamed again by a user since) is skipped, not forced. Returns the
    (id, current_name, restored_name) triples applied."""
    payload = json.loads(backup_file.read_text())
    current = {w.id: w.name for w in session.exec(select(Watchlist)).all()}
    taken = set(current.values())
    todo: dict[int, str] = {}
    applied: list[tuple[int, str, str]] = []
    for entry in payload["renamed"]:
        watchlist_id, old, new = entry["id"], entry["old"], entry["new"]
        if current.get(watchlist_id) != new:
            logger.info("Skipping id %d: current name %r is not the migrated %r.", watchlist_id, current.get(watchlist_id), new)
            continue
        if old in taken:
            raise MigrationAbort(f"Cannot roll back {new} -> {old}: a list named {old} already exists. Nothing changed.")
        todo[watchlist_id] = old
        applied.append((watchlist_id, new, old))
    if todo:
        _apply_names(session, todo)
    return applied


def _latest_backup_file(backup_dir: Path) -> Path:
    files = sorted(backup_dir.glob(f"{BACKUP_PREFIX}*.json"))
    if not files:
        raise MigrationAbort(f"No {BACKUP_PREFIX}*.json logical backup found in {backup_dir}.")
    return files[-1]


def main(dry_run: bool = False, rollback: bool = False, skip_full_backup: bool = False, backup_file: Path | None = None) -> int:
    configure_logging(LOG_PATH)
    init_db()
    try:
        with Session(engine) as session:
            if rollback:
                applied = run_rollback(session, backup_file or _latest_backup_file(DEFAULT_BACKUP_DIR))
                for watchlist_id, current, restored in applied:
                    logger.info("Rolled back id %d: %s -> %s", watchlist_id, current, restored)
                if not applied:
                    logger.info("Nothing to roll back.")
                return 0
            plan = run_rename(session, DEFAULT_BACKUP_DIR, None if skip_full_backup else create_backup, dry_run=dry_run)
    except InsufficientDiskSpaceError as exc:
        logger.error("Full DB backup refused, nothing changed. %s Free space or pass --skip-full-backup.", exc)
        return 1
    except MigrationAbort as exc:
        logger.error("%s", exc)
        return 1
    if not plan:
        logger.info("No W1..W5 watchlists found; nothing to do.")
    for watchlist_id, old, new in plan:
        logger.info("%s id %d: %s -> %s", "Would rename" if dry_run else "Renamed", watchlist_id, old, new)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rename watchlists W1..W5 to E1..E5 (monitored-watchlist rule).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without changing anything.")
    parser.add_argument("--rollback", action="store_true", help="Rename E1..E5 back to W1..W5 from a logical backup.")
    parser.add_argument("--skip-full-backup", action="store_true", help="Skip the full DB backup (the logical backup is still taken).")
    parser.add_argument("--backup-file", type=Path, help="Logical backup JSON for --rollback (default: newest).")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    sys.exit(main(cli_args.dry_run, cli_args.rollback, cli_args.skip_full_backup, cli_args.backup_file))
