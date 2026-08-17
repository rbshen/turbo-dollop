"""Standalone script: lightweight log rotation for backend/logs/ -- no
system logrotate involved. Confirmed logrotate isn't even installed in this
environment, and a project-wide /etc/logrotate.d entry would need root with
no passwordless sudo available here -- a self-contained script that runs
under the same cron user as everything else is simpler and more portable.

Any *.log file over ROTATE_SIZE_THRESHOLD_BYTES gets its current contents
gzip-compressed to a timestamped .gz archive, then the original file is
truncated in place (not deleted/recreated) via a fresh file handle opened
"r+b" -- the same "copytruncate" approach logrotate's own copytruncate mode
uses. This is safe here even for a long-running writer that already has the
file open (e.g. `uvicorn --reload` redirected into uvicorn_dev.log by
bin/start.sh, or Python's own logging.FileHandler, default mode='a'):
both open the file with O_APPEND, which repositions to the file's true
end-of-file before every write, so the next write after a truncate lands
cleanly at the new (empty) end rather than at some stale remembered offset
-- confirmed directly, not assumed. The only real caveat, shared with
logrotate's copytruncate, is a narrow race window between reading the
file's contents for the archive and truncating it: a line written by a
live process in that exact window is lost, not duplicated or gapped.

Run:
    uv run python -m pipeline.rotate_logs

Override the size threshold for one run (e.g. to force-rotate a specific
file on demand rather than waiting for it to grow):
    uv run python -m pipeline.rotate_logs --threshold-mb 1
"""

import argparse
import gzip
import logging
import os
from datetime import datetime
from pathlib import Path

from core.cron_health import cron_heartbeat
from core.logging_config import configure_logging

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_PATH = LOGS_DIR / "rotate_logs.log"

ROTATE_SIZE_THRESHOLD_BYTES = 5 * 1024 * 1024  # 5MB -- skips small/empty logs, targets the genuinely large ones.
# Weekly cadence (see crontab.txt) -- 8 keeps roughly 2 months of history.
ROTATE_KEEP_COUNT = 8

logger = logging.getLogger(__name__)


def _rotate_one(log_path: Path, threshold_bytes: int = ROTATE_SIZE_THRESHOLD_BYTES) -> Path | None:
    size = log_path.stat().st_size
    if size <= threshold_bytes:
        logger.info("%s: %d bytes, under threshold, skipping.", log_path.name, size)
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = log_path.with_name(f"{log_path.name}.{timestamp}.gz")

    with open(log_path, "rb") as src:
        data = src.read()
    with gzip.open(archive_path, "wb") as dst:
        dst.write(data)

    with open(log_path, "r+b") as f:
        f.truncate(0)
        os.fsync(f.fileno())

    logger.info("%s: rotated %d bytes -> %s.", log_path.name, size, archive_path.name)
    return archive_path


def _prune_old_archives(log_path: Path, keep: int) -> list[Path]:
    existing = sorted(log_path.parent.glob(f"{log_path.name}.*.gz"))
    to_delete = existing[:-keep] if keep > 0 else existing
    for path in to_delete:
        path.unlink()
        logger.info("%s: pruned old archive %s.", log_path.name, path.name)
    return to_delete


def rotate_all(logs_dir: Path = LOGS_DIR, threshold_bytes: int = ROTATE_SIZE_THRESHOLD_BYTES) -> list[Path]:
    rotated = []
    for log_path in sorted(logs_dir.glob("*.log")):
        archive = _rotate_one(log_path, threshold_bytes)
        if archive is not None:
            rotated.append(archive)
        _prune_old_archives(log_path, ROTATE_KEEP_COUNT)
    return rotated


def main(threshold_mb: float | None = None) -> list[Path]:
    configure_logging(LOG_PATH)
    threshold_bytes = int(threshold_mb * 1024 * 1024) if threshold_mb is not None else ROTATE_SIZE_THRESHOLD_BYTES
    rotated = rotate_all(threshold_bytes=threshold_bytes)
    logger.info("Log rotation complete. %d file(s) rotated.", len(rotated))
    return rotated


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rotate backend/logs/*.log files over the size threshold.")
    parser.add_argument(
        "--threshold-mb", type=float, default=None, help="Override ROTATE_SIZE_THRESHOLD_BYTES (5MB) for this run."
    )
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.rotate_logs"):
        main(cli_args.threshold_mb)
