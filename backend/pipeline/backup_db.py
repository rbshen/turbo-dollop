"""Standalone script: timestamped, compressed backup of backend/fathom.db to
backend/backups/ (gitignored) -- no backup mechanism existed before this.
Uses sqlite3's own backup API (Connection.backup()), not a raw file copy, so
the snapshot is transactionally consistent even if the app is writing to the
DB at the same moment this runs. Keeps the most recent BACKUP_RETENTION_COUNT
compressed backups, pruning older ones each run.

Run:
    uv run python -m pipeline.backup_db
"""

import gzip
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from core.config import BASE_DIR, settings
from core.cron_health import cron_heartbeat
from core.logging_config import configure_logging

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "backup_db.log"

# Daily cadence (see crontab.txt) -- 14 keeps two weeks of recovery points.
# Backed-up rows are mostly JSON text (FundamentalsCache.raw_json), which
# gzip compresses well, keeping 14 daily copies of an ~800MB DB from being
# unreasonable on disk.
BACKUP_RETENTION_COUNT = 14

DEFAULT_DB_PATH = (BASE_DIR / settings.database_path).resolve()
DEFAULT_BACKUP_DIR = BASE_DIR / "backups"

logger = logging.getLogger(__name__)


def create_backup(
    db_path: Path = DEFAULT_DB_PATH, backup_dir: Path = DEFAULT_BACKUP_DIR, keep: int = BACKUP_RETENTION_COUNT
) -> Path:
    """Creates one new compressed backup and prunes old ones beyond `keep`.
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

    _prune_old_backups(backup_dir, db_path.stem, keep)
    return dest_path


def _prune_old_backups(backup_dir: Path, stem: str, keep: int) -> list[Path]:
    existing = sorted(backup_dir.glob(f"{stem}_*.db.gz"))
    to_delete = existing[:-keep] if keep > 0 else existing
    for path in to_delete:
        path.unlink()
    return to_delete


def main() -> Path:
    configure_logging(LOG_PATH)
    backup_path = create_backup()
    size_mb = backup_path.stat().st_size / (1024 * 1024)
    logger.info("Backup created: %s (%.1f MB). Retention: last %d kept.", backup_path, size_mb, BACKUP_RETENTION_COUNT)
    return backup_path


if __name__ == "__main__":
    with cron_heartbeat("pipeline.backup_db"):
        main()
