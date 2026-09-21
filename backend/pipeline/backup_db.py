"""Standalone script: timestamped, compressed backup of backend/fathom.db to
backend/backups/ (gitignored) -- no backup mechanism existed before this.
Uses sqlite3's own backup API (Connection.backup()), not a raw file copy, so
the snapshot is transactionally consistent even if the app is writing to the
DB at the same moment this runs. Prunes older backups each run with a tiered
retention rule (see BACKUP_KEEP_DAILY/BACKUP_KEEP_WEEKLY below).

Run:
    uv run python -m pipeline.backup_db
"""

import gzip
import logging
import re
import shutil
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

from core.config import BASE_DIR, settings
from core.cron_health import cron_heartbeat
from core.logging_config import configure_logging

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "backup_db.log"

# Tiered retention. Backed-up rows are mostly JSON text
# (FundamentalsCache.raw_json), which gzip compresses ~9x, but the DB is
# ~1.2GB now (~130MB per compressed backup) and lives on a disk with little
# headroom, so a flat "last 14 dailies" (~1.85GB at today's size) is more
# than this box should spend. Instead:
#   - daily tier: the newest BACKUP_KEEP_DAILY distinct backup DATES.
#   - weekly tier: the newest BACKUP_KEEP_WEEKLY calendar weeks (ISO,
#     Mon-Sun) *outside* the daily window, each represented by that week's
#     last backup -- the Sunday one under normal operation, falling back to
#     the latest earlier day if a Sunday run failed, so one bad night can't
#     cost a whole week. Weekly copies are additional to the daily window,
#     not carved out of it: 7 + 4 = 11 dates at steady state, reaching
#     back ~5 weeks.
# Both tiers count distinct dates present on disk, not calendar days back, so
# an outage never shrinks retention below 7 daily copies.
BACKUP_KEEP_DAILY = 7
BACKUP_KEEP_WEEKLY = 4

# Free-space preflight. Each run writes an UNCOMPRESSED copy of the DB
# (~1.0x its size) next to the backups, then gzips it (~0.11x today) and only
# then deletes the copy, so peak need is ~1.1x the DB. 1.25x leaves slack for
# a worse compression ratio. Prompted by the 2026-08-09 run that died with
# "database or disk is full" mid-copy, leaving a partial file behind.
BACKUP_FREE_SPACE_FACTOR = 1.25

# A run's temp files that are older than this are stranded by a killed process
# (SIGKILL/power loss skip the `finally` cleanup) and are swept at the start of
# the next run. Well above a run's real duration (a minute or two) so a
# concurrent live run's temp file is never touched, and well below the 24h
# cadence so a stranded ~1.2GB copy is gone before the next preflight needs
# the space.
STALE_TEMP_MIN_AGE_HOURS = 6

DEFAULT_DB_PATH = (BASE_DIR / settings.database_path).resolve()
DEFAULT_BACKUP_DIR = BASE_DIR / "backups"

logger = logging.getLogger(__name__)


class InsufficientDiskSpaceError(RuntimeError):
    """Raised before anything is written when the disk can't hold the backup's
    temporary uncompressed copy."""


def _remove_quietly(path: Path) -> None:
    """Best-effort unlink for cleanup paths. Never raises: this runs in a
    `finally`, and a cleanup failure (e.g. a permissions error) must not mask
    the original exception that got us here."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove temporary backup file %s", path, exc_info=True)


def _sweep_stale_temp_files(
    backup_dir: Path, stem: str, min_age_hours: float = STALE_TEMP_MIN_AGE_HOURS
) -> list[Path]:
    """Removes this job's own temp files stranded by a killed run. Matches only
    the exact names create_backup writes (`.<stem>_<ts>.db.tmp`, `.<stem>_<ts>.
    db.gz.tmp`, plus SQLite's `-journal` sidecar), and only when older than
    `min_age_hours`, so finished backups and anything else in the directory --
    or a run still in progress -- are never touched."""
    temp_re = re.compile(rf"^\.{re.escape(stem)}_\d{{8}}_\d{{6}}\.db(\.gz)?\.tmp(-journal)?$")
    cutoff = time.time() - min_age_hours * 3600
    removed = []
    for path in backup_dir.iterdir():
        if not temp_re.match(path.name):
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        _remove_quietly(path)
        removed.append(path)
    if removed:
        logger.warning(
            "Removed %d stale temp file(s) from a previous interrupted run: %s",
            len(removed),
            ", ".join(p.name for p in removed),
        )
    return removed


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _check_free_space(db_path: Path, backup_dir: Path) -> None:
    needed = int(db_path.stat().st_size * BACKUP_FREE_SPACE_FACTOR)
    free = _free_bytes(backup_dir)
    if free < needed:
        raise InsufficientDiskSpaceError(
            f"Refusing to start backup: {free / 1e9:.2f} GB free on the volume holding {backup_dir}, "
            f"but the temporary uncompressed copy needs ~{needed / 1e9:.2f} GB "
            f"({BACKUP_FREE_SPACE_FACTOR}x the {db_path.stat().st_size / 1e9:.2f} GB DB). Nothing was written."
        )


def create_backup(
    db_path: Path = DEFAULT_DB_PATH,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    keep_daily: int = BACKUP_KEEP_DAILY,
    keep_weekly: int = BACKUP_KEEP_WEEKLY,
) -> Path:
    """Creates one new compressed backup and prunes old ones per the tiered
    retention rule (`select_backups_to_prune`).
    Returns the path to the new backup file. `db_path`/`backup_dir` are
    explicit parameters (not hardcoded to the real DB path) so tests can
    point this at a throwaway SQLite file instead of the real DB -- see
    CLAUDE.md's "Ad-hoc reproduction scripts must not touch the real
    database"."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    _sweep_stale_temp_files(backup_dir, db_path.stem)
    _check_free_space(db_path, backup_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = backup_dir / f"{db_path.stem}_{timestamp}.db.gz"
    tmp_path = backup_dir / f".{db_path.stem}_{timestamp}.db.tmp"
    gz_tmp_path = backup_dir / f".{db_path.stem}_{timestamp}.db.gz.tmp"

    # The compressed file is written under a dot-prefixed temp name and only
    # renamed to its final `fathom_<ts>.db.gz` name once complete, so a
    # truncated file can never sit under a name that retention would count as
    # a valid backup. Both temp files are removed on ANY exit from this block
    # -- success (the uncompressed copy; the gz temp was already renamed away)
    # or failure at any step -- so a failed run leaves nothing behind. (A
    # SIGKILL/power loss skips `finally` entirely; `_sweep_stale_temp_files`
    # above clears anything that strands, at the start of the next run.)
    try:
        source_conn = sqlite3.connect(str(db_path))
        try:
            dest_conn = sqlite3.connect(str(tmp_path))
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()

        with open(tmp_path, "rb") as src, gzip.open(gz_tmp_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        gz_tmp_path.replace(dest_path)
    finally:
        _remove_quietly(tmp_path)
        _remove_quietly(gz_tmp_path)

    pruned = _prune_old_backups(backup_dir, db_path.stem, keep_daily, keep_weekly)
    if pruned:
        logger.info("Pruned %d old backup(s): %s", len(pruned), ", ".join(p.name for p in pruned))
    return dest_path


def select_backups_to_prune(paths: list[Path], stem: str, keep_daily: int, keep_weekly: int) -> list[Path]:
    """Pure retention decision: which of `paths` should be deleted.

    Only files named exactly `<stem>_YYYYMMDD_HHMMSS.db.gz` are considered --
    anything else in the directory (a hand-made `fathom_before_migration.
    db.gz`, another DB's backups) is never returned, so it can't be deleted
    by a rule that doesn't understand it. Retention works on dates: every
    file on a kept date is kept (a manual same-day re-run doesn't displace
    anything), and every file on a dropped date is dropped."""
    name_re = re.compile(rf"^{re.escape(stem)}_(\d{{8}})_\d{{6}}\.db\.gz$")
    by_date: dict[date, list[Path]] = {}
    for path in paths:
        match = name_re.match(path.name)
        if not match:
            continue
        try:
            backup_date = datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        by_date.setdefault(backup_date, []).append(path)

    newest_first = sorted(by_date, reverse=True)
    kept = set(newest_first[: max(keep_daily, 0)])

    # Newest-first, so setdefault records each ISO week's LAST backup date.
    last_of_week: dict[tuple[int, int], date] = {}
    for backup_date in newest_first:
        last_of_week.setdefault(backup_date.isocalendar()[:2], backup_date)
    weekly_candidates = sorted((d for d in last_of_week.values() if d not in kept), reverse=True)
    kept |= set(weekly_candidates[: max(keep_weekly, 0)])

    return sorted(path for backup_date, files in by_date.items() if backup_date not in kept for path in files)


def _prune_old_backups(backup_dir: Path, stem: str, keep_daily: int, keep_weekly: int) -> list[Path]:
    to_delete = select_backups_to_prune(list(backup_dir.glob(f"{stem}_*.db.gz")), stem, keep_daily, keep_weekly)
    for path in to_delete:
        path.unlink()
    return to_delete


def main() -> Path:
    configure_logging(LOG_PATH)
    backup_path = create_backup()
    size_mb = backup_path.stat().st_size / (1024 * 1024)
    logger.info(
        "Backup created: %s (%.1f MB). Retention: %d daily + %d weekly kept.",
        backup_path,
        size_mb,
        BACKUP_KEEP_DAILY,
        BACKUP_KEEP_WEEKLY,
    )
    return backup_path


if __name__ == "__main__":
    with cron_heartbeat("pipeline.backup_db"):
        main()
