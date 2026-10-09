"""One-time standalone script: backfill the last 5 years of sector and industry average P/E (FMP) into
`SectorIndustryPe`, for the 11 sectors and every industry on FMP's industry snapshot, per exchange (NASDAQ, NYSE, AMEX).
See data/sector_industry_pe_data.py and docs/specs/sector-industry-pe.md.

Idempotent (upserts) and resumable: a series whose oldest stored row already reaches the window start is skipped
(`--force` refetches everything); a series FMP answers empty stores nothing, is logged, and is retried on the next run.
315 series (~320 calls) paced at 4 per second; observed ~9 min (FMP answers in ~1.2 s). Skipped while the `sector_industry_pe` group or the master switch is off.

Run (REAL database: this script is meant to write it):
    uv run python -m pipeline.backfills.backfill_sector_industry_pe
    uv run python -m pipeline.backfills.backfill_sector_industry_pe --exchanges NYSE --kinds sector   # a subset
"""

import argparse
import asyncio
import logging
from pathlib import Path

from clients.fmp_client import fmp_client
from core.data_groups import job_skip_reason
from core.db import init_db
from core.logging_config import configure_logging
from data.sector_industry_pe_data import (
    BACKFILL_REQUEST_INTERVAL_SECONDS,
    EXCHANGES,
    KINDS,
    BackfillResult,
    backfill_history,
    count_rows,
)

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "backfill_sector_industry_pe.log"

logger = logging.getLogger(__name__)


async def main(exchanges: tuple[str, ...] = EXCHANGES, kinds: tuple[str, ...] = KINDS, force: bool = False) -> BackfillResult | None:
    configure_logging(LOG_PATH)
    init_db()
    skip_reason = job_skip_reason("sector_industry_pe")
    if skip_reason:
        logger.info("Sector/industry P/E backfill %s.", skip_reason)
        return None
    fmp_client.min_request_interval = BACKFILL_REQUEST_INTERVAL_SECONDS
    return await backfill_history(exchanges=exchanges, kinds=kinds, force=force)


def _report(result: BackfillResult) -> None:
    print(f"Window {result.start} .. {result.end}: {result.series_total} series, {result.series_fetched} fetched, "
          f"{result.series_skipped} already complete, {len(result.empty)} empty, {len(result.failed)} failed")
    print("Rows written this run / stored in total, by kind and exchange:")
    stored = count_rows()
    for key in sorted(set(stored) | set(result.rows)):
        print(f"  {key[0]:<9}{key[1]:<8}{result.rows.get(key, 0):>8} / {stored.get(key, 0)}")
    for kind, name, exchange in result.empty:
        print(f"  EMPTY  {kind} {name!r} {exchange}")
    for kind, name, exchange, error in result.failed:
        print(f"  FAILED {kind} {name!r} {exchange}: {error}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time 5-year sector/industry P/E backfill.")
    parser.add_argument("--exchanges", default=",".join(EXCHANGES), help="Comma-separated subset of NASDAQ,NYSE,AMEX.")
    parser.add_argument("--kinds", default=",".join(KINDS), help="Comma-separated subset of sector,industry.")
    parser.add_argument("--force", action="store_true", help="Refetch series that are already complete.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    outcome = asyncio.run(
        main(
            tuple(e.strip().upper() for e in args.exchanges.split(",") if e.strip()),
            tuple(k.strip().lower() for k in args.kinds.split(",") if k.strip()),
            args.force,
        )
    )
    if outcome is None:
        print("Skipped: the sector_industry_pe data group (or the FMP master switch) is off.")
    else:
        _report(outcome)
