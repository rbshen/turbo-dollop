"""Standalone script: reports how many tickers in the stored S&P 500 + Dow
universe haven't had their FundamentalsCache "profile" row refreshed within
the staleness threshold -- a readable freshness report, not a silent check.
"profile" is fetched on every nightly refresh cycle (see
nightly_fundamentals_fetch.py::_refresh_one_ticker), so its fetched_at is a
reliable proxy for "did this ticker's nightly refresh actually happen
recently." Cache-only, zero FMP calls, safe to run anytime.

Run:
    uv run python -m pipeline.stale_data_health_check

Override the staleness threshold for one run:
    uv run python -m pipeline.stale_data_health_check --days 14
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import FundamentalsCache
from pipeline.nightly_fundamentals_fetch import load_universe_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "stale_data_health_check.log"

# cache_staleness_days (7) is when a row becomes ELIGIBLE for refetch, not a
# guarantee it actually was -- this adds a buffer for one missed nightly run
# before flagging a ticker, so ordinary jitter doesn't read as a real outage.
DEFAULT_STALE_THRESHOLD_DAYS = 10

logger = logging.getLogger(__name__)


def check_staleness(tickers: list[str], threshold_days: int) -> dict:
    """Returns {"fresh": [...], "stale": [(ticker, days), ...], "never_fetched": [...]}."""
    fresh: list[str] = []
    stale: list[tuple[str, int]] = []
    never_fetched: list[str] = []
    now = datetime.now()
    with Session(engine) as session:
        for ticker in tickers:
            row = session.exec(
                select(FundamentalsCache).where(
                    FundamentalsCache.ticker == ticker, FundamentalsCache.statement_type == "profile"
                )
            ).first()
            if row is None:
                never_fetched.append(ticker)
                continue
            days = (now - row.fetched_at).days
            if days > threshold_days:
                stale.append((ticker, days))
            else:
                fresh.append(ticker)
    return {"fresh": fresh, "stale": stale, "never_fetched": never_fetched}


def _format_report(result: dict, total: int, threshold_days: int) -> str:
    lines = [
        f"Stale-data health check ({total} tickers, staleness threshold {threshold_days} days):",
        f"  Fresh:         {len(result['fresh'])}",
        f"  Stale:         {len(result['stale'])}",
        f"  Never fetched: {len(result['never_fetched'])}",
    ]
    if result["stale"]:
        lines.append("  Stale tickers (ticker: days since last fetch):")
        for ticker, days in sorted(result["stale"], key=lambda pair: -pair[1]):
            lines.append(f"    {ticker}: {days}d")
    if result["never_fetched"]:
        lines.append("  Never-fetched tickers: " + ", ".join(sorted(result["never_fetched"])))
    return "\n".join(lines)


def main(threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS) -> dict:
    configure_logging(LOG_PATH)
    init_db()
    with Session(engine) as session:
        tickers = load_universe_tickers(session)
    result = check_staleness(tickers, threshold_days)
    report = _format_report(result, len(tickers), threshold_days)
    logger.info("\n%s", report)
    print(report)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report tickers whose cached fundamentals haven't refreshed recently.")
    parser.add_argument("--days", type=int, default=DEFAULT_STALE_THRESHOLD_DAYS, help="Staleness threshold in days.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.stale_data_health_check"):
        main(cli_args.days)
