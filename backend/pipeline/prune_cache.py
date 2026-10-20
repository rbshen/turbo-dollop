"""Standalone script: (1) deletes FundamentalsCache rows older than
Settings.cache_retention_days (default 180) -- distinct from
cache_staleness_days, which only controls when a row is refetched, never
when it's deleted -- but only for tickers that are NOT in the tracked
universe. A tracked ticker (stock or ETF, data/tracked_universe.py) keeps its
last-known rows whatever their age: a slow reporter or an on-demand row type
can sit unrefreshed for more than 180 days, and deleting it would leave the
ticker's page blank for viewers (who read the cache only). Growth comes from
tickers outside the universe (browsed, expired, untracked, delisted, orphans
and non-ticker keys such as forex_rate), which this age rule still removes.
The dead `treasury_rates` type stays on the plain age rule for every ticker.

Fail-safe: if the tracked set cannot be built, comes back empty, or is below
MIN_TRACKED_TICKERS, the age rule is skipped entirely (nothing deleted), a
warning is logged and the job reports "skipped" with the reason. The bars trim
below still runs.

(2) Trims SharedBarsCache bars older than each interval's retention window
(clients/shared_bars_cache.py::RETENTION_DAYS -- 6y of "1d", 3y of "60m"),
which otherwise only ever grows. Not tunable from the CLI: the windows are
tied to what the nightly consumers fetch (see RETENTION_DAYS' own comment),
not a free knob; --dry-run still previews both.

Run (deletes for real):
    uv run python -m pipeline.prune_cache

Preview without deleting:
    uv run python -m pipeline.prune_cache --dry-run

Override the FundamentalsCache retention window for one run (the SharedBarsCache
windows are fixed -- see above):
    uv run python -m pipeline.prune_cache --retention-days 90
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, select

from clients.shared_bars_cache import RETENTION_DAYS, prune_old_bars
from core.config import settings
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.history_merge import INVALIDATED_AT
from core.logging_config import configure_logging
from core.models import FundamentalsCache
from data.tracked_universe import OUT_OF_UNIVERSE, classify_etf_tickers, classify_known_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "prune_cache.log"

# A tracked set smaller than this is treated as a failed build, not a real universe (the live one is ~600).
MIN_TRACKED_TICKERS = 100
# Zero code references; never "kept forever" because its ticker is tracked.
AGE_RULE_ONLY_TYPES = frozenset({"treasury_rates"})
DELETE_CHUNK = 500

logger = logging.getLogger(__name__)


@dataclass
class PruneResult:
    deleted: int  # rows deleted (under dry_run: that would be deleted)
    kept_tracked: int  # aged rows spared because their ticker is tracked
    skipped_reason: str | None = None  # set when the age rule was skipped entirely


def _load_tracked_tickers(session: Session) -> set[str]:
    """Stock side plus ETF side, minus the out-of-universe reasons (the `load_tracked_universe` /
    `load_etf_universe` rule, applied to the two classifications together)."""
    reasons = {**classify_known_tickers(session), **classify_etf_tickers(session)}
    return {t for t, reason in reasons.items() if reason not in OUT_OF_UNIVERSE}


def prune_cache_result(retention_days: int, dry_run: bool = False) -> PruneResult:
    cutoff = datetime.now() - timedelta(days=retention_days)
    with Session(engine) as session:
        try:
            tracked = _load_tracked_tickers(session)
        except Exception as exc:
            logger.warning("Age prune skipped: could not build the tracked set (%s: %s).", type(exc).__name__, exc)
            return PruneResult(0, 0, f"tracked set unavailable ({type(exc).__name__})")
        if len(tracked) < MIN_TRACKED_TICKERS:
            logger.warning(
                "Age prune skipped: tracked set has %d ticker(s), below the floor of %d.", len(tracked), MIN_TRACKED_TICKERS
            )
            return PruneResult(0, 0, f"tracked set {len(tracked)} below floor {MIN_TRACKED_TICKERS}")
        # A row an explicit Refresh marked stale (fetched_at == INVALIDATED_AT, pipeline/refresh.py) holds history that
        # has not been re-fetched yet; it is not "old", so it is never pruned by age.
        aged = session.exec(
            select(FundamentalsCache.id, FundamentalsCache.ticker, FundamentalsCache.statement_type).where(
                FundamentalsCache.fetched_at < cutoff, FundamentalsCache.fetched_at > INVALIDATED_AT
            )
        ).all()
        doomed = [row_id for row_id, ticker, stype in aged if ticker not in tracked or stype in AGE_RULE_ONLY_TYPES]
        kept = len(aged) - len(doomed)
        if doomed and not dry_run:
            for i in range(0, len(doomed), DELETE_CHUNK):
                session.execute(delete(FundamentalsCache).where(FundamentalsCache.id.in_(doomed[i : i + DELETE_CHUNK])))
            session.commit()
    return PruneResult(len(doomed), kept)


def prune_cache(retention_days: int, dry_run: bool = False) -> int:
    """Returns the number of rows deleted (or that would be deleted, under
    --dry-run)."""
    return prune_cache_result(retention_days, dry_run=dry_run).deleted


def main(retention_days: int | None = None, dry_run: bool = False) -> tuple[PruneResult, dict[str, int]]:
    """Returns (FundamentalsCache result, SharedBarsCache bars deleted per
    interval) -- both under dry_run meaning "would be deleted"."""
    configure_logging(LOG_PATH)
    init_db()
    retention = retention_days if retention_days is not None else settings.cache_retention_days
    result = prune_cache_result(retention, dry_run=dry_run)
    verb = "would be deleted" if dry_run else "deleted"
    logger.info(
        "FundamentalsCache: %d row(s) older than %d days %s; %d spared (tracked ticker).",
        result.deleted,
        retention,
        verb,
        result.kept_tracked,
    )
    bars = prune_old_bars(dry_run=dry_run)
    for interval, n in bars.items():
        logger.info("SharedBarsCache: %d '%s' bar(s) older than %d days %s.", n, interval, RETENTION_DAYS[interval], verb)
    return result, bars


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete FundamentalsCache rows past the retention window.")
    parser.add_argument(
        "--retention-days", type=int, default=None, help="Override Settings.cache_retention_days for this run."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted without deleting.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.prune_cache") as run:
        result, bars = main(cli_args.retention_days, dry_run=cli_args.dry_run)
        verb = "would be deleted (dry run)" if cli_args.dry_run else "deleted"
        detail = f"{result.deleted} FundamentalsCache row(s), " + ", ".join(f"{n} {k} bar(s)" for k, n in bars.items())
        message = f"{detail} {verb}; {result.kept_tracked} aged row(s) kept (tracked ticker)"
        if result.skipped_reason:
            run.skip(f"age prune skipped: {result.skipped_reason}; bars: " + ", ".join(f"{n} {k}" for k, n in bars.items()))
        else:
            run.message = message
