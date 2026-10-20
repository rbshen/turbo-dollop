"""Low-disk early warning (2026-10-20), after the Sunday 2026-10-18 backup refused to run on 1.58 GB free and nothing said so until the
next night's success hid it. Reads the free space on the volume holding the database (`os.statvfs`, the same figure `backup_db`'s
pre-check uses) and records it in the cron heartbeat message. Reads only: no FMP call, no file written, no table written but its own
`CronRunLog` heartbeat row (and the read of its previous row).

    free >= 3.5 GB                         -> success, "N GB free ..."
    2.0 GB <= free < 3.5 GB, first night   -> success, message "Low disk warning: ... (night 1 of 2)"
    2.0 GB <= free < 3.5 GB, a second night in a row -> failure (red)
    free < 2.0 GB                          -> failure (red) at once

`cron_heartbeat` has no `partial`/amber status (decisions 2026-10-02 rejected a warning health value), so the first warning night is a
success whose message names it; the page's red appears on the second night or below the hard limit. "In a row" is the previous run of this
job, if it started within 36 h and its message says "Low disk". Scheduled 03:28 UTC: after the 03:25 score recompute (finished 03:25:48 at the
latest over 20 nights, 03:26:22 worst) and before the 03:30 backup, so it reads the space the backup will see. Docs: backend/OPS_RUNBOOK.md ("Disk space"),
docs/decisions.md (2026-10-20).

    uv run python -m pipeline.disk_space_check
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

import core.cron_health as cron_health
from core.cron_health import cron_heartbeat
from core.db import DB_PATH
from core.logging_config import configure_logging
from core.models import CronRunLog

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "disk_space_check.log"
JOB_NAME = "pipeline.disk_space_check"

# Decimal GB, the unit backup_db's own message uses. 3.5 GB is about twice the backup's real peak (the DB copy plus its gzip, ~1.6 GB at a
# 1.41 GB database) with room for the next weekly copy and database growth; 2.0 GB sits just above the backup's 1.25x pre-check (1.76 GB).
WARN_FREE_BYTES = int(3.5e9)
HARD_FREE_BYTES = int(2.0e9)
# The previous run only counts as "the night before" inside the daily cadence window (cron_health._DAILY_HOURS), so a long gap resets the streak.
CONSECUTIVE_WINDOW = timedelta(hours=36)
LOW_MARKER = "Low disk"

logger = logging.getLogger(__name__)


class LowDiskSpaceError(RuntimeError):
    """Raised for the red cases, so cron_heartbeat records a failure with the message."""


def free_bytes(path: Path) -> int:
    """Bytes available to this user on the volume holding `path` (f_bavail x f_frsize, what `shutil.disk_usage(...).free` reports)."""
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize


def _gb(value: float) -> str:
    return f"{value / 1e9:.1f} GB"


def previous_night_was_low(now: datetime | None = None, session: Session | None = None) -> bool:
    """True when the last finished run of this job started within CONSECUTIVE_WINDOW and its message (the success message or the failure
    summary) says "Low disk". Read-only."""
    now = now or datetime.now()

    def read(db: Session) -> bool:
        row = db.exec(
            select(CronRunLog)
            .where(CronRunLog.job_name == JOB_NAME, CronRunLog.status.in_(["success", "failure"]))
            .order_by(CronRunLog.started_at.desc())
            .limit(1)
        ).first()
        return row is not None and now - row.started_at <= CONSECUTIVE_WINDOW and LOW_MARKER in (row.error_summary or "")

    if session is not None:
        return read(session)
    with Session(cron_health.engine) as db:
        return read(db)


def evaluate(free: int, previous_low: bool, warn: int = WARN_FREE_BYTES, hard: int = HARD_FREE_BYTES) -> tuple[str, str]:
    """Pure decision: (level, message), level one of "ok", "warn" (success, night 1), "red" (failure). Every message states the free GB and
    the threshold it was compared with."""
    if free < hard:
        return "red", f"{LOW_MARKER}: {_gb(free)} free, below the {_gb(hard)} hard limit (warn level {_gb(warn)})."
    if free < warn:
        if previous_low:
            return "red", f"{LOW_MARKER}: {_gb(free)} free, below the {_gb(warn)} warn threshold for a second night in a row (hard limit {_gb(hard)})."
        return "warn", f"{LOW_MARKER} warning: {_gb(free)} free, below the {_gb(warn)} warn threshold (night 1 of 2; hard limit {_gb(hard)})."
    return "ok", f"{_gb(free)} free on the database volume (warn below {_gb(warn)}, hard limit {_gb(hard)})."


def main(db_path: Path = DB_PATH) -> str:
    """Returns the heartbeat message; raises LowDiskSpaceError for the red cases."""
    configure_logging(LOG_PATH)
    free = free_bytes(db_path.parent)
    level, message = evaluate(free, previous_night_was_low())
    if level == "red":
        logger.error(message)
        raise LowDiskSpaceError(message)
    if level == "warn":
        logger.warning(message)
    else:
        logger.info(message)
    return message


if __name__ == "__main__":
    with cron_heartbeat("pipeline.disk_space_check") as run:
        run.message = main()
