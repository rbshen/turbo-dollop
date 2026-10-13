"""Weekly audit-log pruning (cleanup batch 2026-10-13): deletes `auditlog` rows older than `AUDIT_RETENTION_DAYS` (default 180) and logs how
many. The same function the manual command uses (`uv run python -m core.auth_cli prune-audit [--days N]`); this module exists so the
cron line is a registered, heartbeat-monitored job like every other (`-m package.module` with a CRON_JOB_NAMES entry). Touches the audit
table only: never a user or a session. Docs: docs/specs/auth.md, backend/OPS_RUNBOOK.md ("Login accounts").

    uv run python -m pipeline.prune_audit_log [--days N]
"""

import argparse
import logging
from pathlib import Path

from core.audit import prune_audit_log
from core.auth_cli import ensure_tables
from core.config import settings
from core.cron_health import cron_heartbeat
from core.logging_config import configure_logging

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "prune_audit_log.log"

logger = logging.getLogger(__name__)


def main(days: int | None = None) -> int:
    configure_logging(LOG_PATH)
    days = settings.audit_retention_days if days is None else days
    ensure_tables()  # the audit table may not exist yet on a database the app has not started against since step 3
    deleted = prune_audit_log(days)
    logger.info("Pruned %d audit log row(s) older than %d day(s).", deleted, days)
    return deleted


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete audit log rows older than N days.")
    parser.add_argument("--days", type=int, default=None, help="Override AUDIT_RETENTION_DAYS (180) for this run; at least 1.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.prune_audit_log") as run:
        removed = main(cli_args.days)
        run.message = f"Pruned {removed} audit row(s)."
