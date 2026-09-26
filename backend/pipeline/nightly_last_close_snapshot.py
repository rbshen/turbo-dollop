"""Standalone script: nightly cache of each tracked US-listed ticker's last official
close, from FMP (Phase 6a). This is the fallback tier for the ticker header's price
(data/ticker_summary.py serves it when the live FMP quote fails or `profile_quote` is
off) -- see data/last_close_data.py for the mechanism.

Universe: the same US-listed tracked universe the price-target snapshot uses
(`load_us_price_target_universe`: index + ever-viewed + scored + watchlisted, US
listings only, minus delisted-flagged). One `/historical-price-eod/full` call per
ticker (~590/night, ~1 min paced). Skipped (a real `skipped` cron status) while the
`daily_prices` group is not live -- there is no other source any more.

Default schedule: 3:15 AM server time (UTC), after the 3:10 trend job and long after
the US close, so the newest completed session's close is final. Runs every day; a
weekend/holiday run re-caches the same session idempotently.

Run manually:
    uv run python -m pipeline.nightly_last_close_snapshot
    uv run python -m pipeline.nightly_last_close_snapshot --tickers AAPL,MSFT
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session

from core.cron_health import cron_heartbeat
from core.data_groups import job_skip_reason
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.tickers import normalize_ticker
from data.last_close_data import refresh_last_closes
from pipeline.nightly_price_target_snapshot import load_us_price_target_universe

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_last_close_snapshot.log"


async def main(tickers: list[str] | None = None) -> dict:
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    skip_reason = job_skip_reason("daily_prices")
    if skip_reason:
        logger.info("Last-close snapshot %s.", skip_reason)
        return {"processed": 0, "written": 0, "failed": 0, "failures": [], "skipped": True, "skip_reason": skip_reason}

    if tickers is None:
        with Session(engine) as session:
            tickers = load_us_price_target_universe(session)
    if not tickers:
        logger.error("No tickers to process.")
        return {"processed": 0, "written": 0, "failed": 0, "failures": []}

    start = time.monotonic()
    result = await refresh_last_closes(tickers)
    result["duration_seconds"] = time.monotonic() - start
    logger.info(
        "Last-close snapshot complete (as of %s). Processed: %d. Written: %d. Failed: %d. Duration: %.1fs.",
        result["as_of"], result["processed"], result["written"], result["failed"], result["duration_seconds"],
    )
    if result["failures"]:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in result["failures"]))
    return result


def record_outcome(result: dict, run) -> None:
    """A gated run is "skipped"; a run that wrote nothing at all raises (heartbeat
    "failure"); anything else is a "success" with a short message."""
    if result.get("skipped"):
        run.skip(result["skip_reason"])
    elif result["processed"] and result["written"] == 0:
        raise RuntimeError(f"last-close snapshot wrote nothing: all {result['failed']} tickers failed")
    else:
        run.message = f"{result['written']} written, {result['failed']} failed"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nightly FMP last-close cache.")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated explicit ticker list (for testing).")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    explicit = [normalize_ticker(t) for t in cli_args.tickers.split(",") if t.strip()] if cli_args.tickers else None
    with cron_heartbeat("pipeline.nightly_last_close_snapshot") as run:
        record_outcome(asyncio.run(main(explicit)), run)
