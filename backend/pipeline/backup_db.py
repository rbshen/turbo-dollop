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

DEFAULT_DB_PATH = (BASE_DIR / settings.database_path).resolve()
DEFAULT_BACKUP_DIR = BASE_DIR / "backups"

logger = logging.getLogger(__name__)


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = backup_dir / f"{db_path.stem}_{timestamp}.db.gz"
    tmp_path = backup_dir / f".{db_path.stem}_{timestamp}.db.tmp"

    source_conn = sqlite3.connect(str(db_path))
    try:
        dest_conn = sqlite3.connect(str(tmp_path))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    with open(tmp_path, "rb") as src, gzip.open(dest_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    tmp_path.unlink()

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
