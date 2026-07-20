"""Standalone script: nightly fundamentals refresh for every S&P 500
ticker in the stored constituent list (see sp500_scraper.py /
IndexConstituent), via the app's existing cache-aware fetch pipeline --
get_step1_data / get_step2_data / get_step4_data / get_step5_data /
get_summary. Nothing bespoke here: these are the exact same functions
Step 1/2/4/5 and the ticker header already call, each already going through
get_or_fetch's cache-freshness check internally. The first run against a
cold cache does a full fetch (~7,000 calls, ~30 min at the paced rate
below); every run after that is mostly cache hits, since get_or_fetch only
calls FMP for a ticker/statement whose cache has actually gone stale.

Default schedule: 2am server time, nightly (see crontab.txt in this
directory). To change the schedule, edit that one crontab line -- nothing
in this script needs touching for a schedule change.

Run manually against the full stored list:
    uv run python nightly_fundamentals_fetch.py

Run against a small subset first (recommended before ever doing a first
full cold-cache run):
    uv run python nightly_fundamentals_fetch.py --limit 15
    uv run python nightly_fundamentals_fetch.py --tickers AAPL,MSFT,ZZZZINVALID
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session, select

from db import engine, init_db
from fmp_client import fmp_client
from models import IndexConstituent
from step1_data import get_step1_data
from step2_data import get_step2_data
from step4_data import get_step4_data
from step5_data import get_step5_data
from ticker_summary import get_summary

LOG_PATH = Path(__file__).resolve().parent / "logs" / "nightly_fundamentals_fetch.log"

# Investigation found the empirical FMP rate limit sits around 300-600
# requests/minute on a rolling window (300 concurrent requests succeeded,
# but a further batch right after started drawing 429s). 220/min leaves
# real headroom under even the conservative end of that range.
TARGET_REQUESTS_PER_MINUTE = 220


def _configure_logging() -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


def load_sp500_tickers(session: Session) -> list[str]:
    rows = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
    return [row.ticker for row in rows]


async def _refresh_one_ticker(ticker: str) -> None:
    await get_step1_data(ticker)
    await get_step2_data(ticker)
    await get_step4_data(ticker)
    await get_step5_data(ticker)
    await get_summary(ticker)


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full stored S&P 500 list" -- passing
    an explicit list (used by the CLI's --limit/--tickers and by tests)
    bypasses the DB lookup entirely. Returns the run summary dict so tests
    can assert on it directly rather than scraping the log."""
    _configure_logging()
    logger = logging.getLogger(__name__)
    init_db()

    if tickers is None:
        with Session(engine) as session:
            tickers = load_sp500_tickers(session)

    if not tickers:
        logger.error("No tickers to process -- run refresh_sp500_list.py first, or pass an explicit ticker list.")
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}

    fmp_client.min_request_interval = 60.0 / TARGET_REQUESTS_PER_MINUTE
    logger.info(
        "Starting nightly fundamentals fetch for %d tickers (pacing %.3fs/request, target %d req/min).",
        len(tickers),
        fmp_client.min_request_interval,
        TARGET_REQUESTS_PER_MINUTE,
    )

    start_time = time.monotonic()
    start_request_count = fmp_client.request_count
    failures: list[tuple[str, str]] = []

    for i, ticker in enumerate(tickers, start=1):
        try:
            await _refresh_one_ticker(ticker)
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    calls_made = fmp_client.request_count - start_request_count

    logger.info(
        "Nightly fetch complete. Processed: %d. Failed: %d. FMP calls made: %d. Duration: %.1fs (%.1f min).",
        len(tickers),
        len(failures),
        calls_made,
        duration,
        duration / 60,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(tickers),
        "failed": len(failures),
        "calls_made": calls_made,
        "duration_seconds": duration,
        "failures": failures,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nightly S&P 500 fundamentals refresh.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N stored tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the stored list (for testing)."
    )
    return parser.parse_args()


def _resolve_cli_tickers(args: argparse.Namespace) -> list[str] | None:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.limit:
        init_db()
        with Session(engine) as session:
            all_tickers = load_sp500_tickers(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
