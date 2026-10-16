"""One-off seed of the Warren Signals watch table (docs/specs/warren-signals-page.md): the same step the nightly Warren job
ends with, run on its own. Every monitored ticker with no cursor reads the last 3 months of completed 2h candles, and a
ticker with an up arrow in that window gets a row. Idempotent: a ticker already seeded reads nothing and writes nothing, a
removed ticker is never resurrected, so running it again (or letting the next nightly run do the work) is harmless.

Reads the 60m bars through the shared bars cache exactly as the nightly job does (a warm cache means no FMP call; a stale
row is topped up, and the `intraday_bars` data group gates it the same way).

Run:
    uv run python -m pipeline.seed_warren_watch
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from clients.shared_bars_cache import INTRADAY_INTERVAL, get_or_fetch_bars_batch
from core.data_groups import job_skip_reason
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.watchlists import list_monitored_tickers
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS, update_watch_table

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "seed_warren_watch.log"

logger = logging.getLogger(__name__)


async def main() -> dict:
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


if __name__ == "__main__":
    print(asyncio.run(main()))
