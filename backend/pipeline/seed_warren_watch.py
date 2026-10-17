"""Run the Warren Signals watch step on its own (docs/specs/warren-signals-page.md): the same stateless replay the nightly Warren
job ends with. Every monitored ticker is replayed from the fixed anchor (`data.warren_watch_data.REPLAY_ANCHOR`) and a row is
written only if its result differs from the stored one; a ticker with no row gets one only with an up arrow in the last 3 months
(`ROW_MONTHS`), a removed ticker stays removed until an up arrow falls after its removal. Idempotent: a second run writes nothing.

Reads the 60m bars through the shared bars cache exactly as the nightly job does (a warm cache means no FMP call; a stale
row is topped up, and the `intraday_bars` data group gates it the same way).

--dry-run reports what the step WOULD change and writes nothing: it reads the cached bars only (no FMP call, no top-up), never runs
`init_db` (so it does not migrate the file) and never creates a settings row. Use it to check the step against the live database.

Run:
    uv run python -m pipeline.seed_warren_watch [--dry-run]
"""

import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session

from clients.shared_bars_cache import INTRADAY_INTERVAL, _load_frames, get_or_fetch_bars_batch
from core.data_groups import job_skip_reason
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.watchlists import list_monitored_tickers
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS, update_watch_table

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "seed_warren_watch.log"

logger = logging.getLogger(__name__)


async def main(dry_run: bool = False) -> dict:
    if dry_run:
        with Session(engine) as session:
            tickers, _ = list_monitored_tickers(session)
            bars_by_ticker = _load_frames(session, tickers, INTRADAY_INTERVAL, (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date())
        return update_watch_table(tickers, bars_by_ticker, dry_run=True)
    configure_logging(LOG_PATH)
    init_db()
    skip_reason = job_skip_reason("intraday_bars")
    if skip_reason:
        logger.info("Warren watch seed %s.", skip_reason)
        return {"skipped": True, "skip_reason": skip_reason}
    with Session(engine) as session:
        tickers, _ = list_monitored_tickers(session)
    bars_by_ticker = await get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, LOOKBACK_DAYS, auto_adjust=False)
    return update_watch_table(tickers, bars_by_ticker)


def _print_dry_run(summary: dict) -> None:
    print(f"DRY RUN (nothing written): {summary['watch_attempted']} tickers, {summary['watch_created']} would be created, "
          f"{summary['watch_changed']} would change, {summary['watch_failed']} failed; {summary['watch_lp_calls']} LP calls; {summary['watch_seconds']:.1f}s")
    for ticker, outcome, changes in sorted(summary["watch_details"]):
        print(f"  {ticker}: {outcome}")
        for name, (old, new) in changes.items():
            print(f"      {name}: {old} -> {new}")
    for ticker, why in summary["watch_failures"]:
        print(f"  FAILED {ticker}: {why}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report what would change; read the cache only, write nothing")
    args = parser.parse_args()
    result = asyncio.run(main(args.dry_run))
    if args.dry_run:
        _print_dry_run(result)
    else:
        print(result)
