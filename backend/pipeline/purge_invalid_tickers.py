"""Standalone script: deletes FundamentalsCache (and any TickerScore) rows
for tickers that FMP has definitively confirmed don't resolve to a real
company, rather than leaving them as permanent dead weight -- found during
the IREN/SEZL/POOL missing-Overall-pill investigation, which turned up 35
tickers with cached data but no TickerScore row. Most of those 35 turned
out to be real tickers that simply never went through a
compute_ticker_score call site (nightly_score_recompute.py now sweeps
those); a small number had a genuinely empty `profile` fetch.

Detection is deliberately narrow, to avoid ever purging a real ticker that
happens to be temporarily unreachable (an FMP outage, or a real
access-tier gap like BRK.B/BF.B's known 402 -- see CLAUDE.md's Debt/CET1
section for that precedent). A ticker only qualifies if ALL of:

  1. A `profile` FundamentalsCache row exists at all -- i.e. FMP actually
     responded (no httpx exception was raised; see cache.py::safe_fetch,
     which swallows httpx.HTTPError to `{}` and never persists a row on
     failure). A ticker with no `profile` row is ambiguous (never
     attempted, or attempted and failed/paywalled) and is never touched
     here.
  2. That row's parsed JSON has no non-empty `companyName` -- FMP's actual
     "no such symbol" shape (an empty list, distinct from a real profile
     dict). This is the closest thing to a positive "FMP confirms this
     isn't a real ticker" signal the data supports.
  3. The ticker is not an IndexConstituent -- defense in depth: a real
     S&P 500/Dow member must never be purged even if some future FMP
     response shape confused check 2.

Low blast radius even for a rare false positive: unlike the fabricated-
data-masquerading-as-real "Acme Corp" incident (CLAUDE.md), this only ever
removes a thin, already-empty cache footprint -- if a purged ticker turns
out to be real and is searched again, it simply re-fetches from FMP on
the next view.

Run (deletes for real):
    uv run python -m pipeline.purge_invalid_tickers

Preview without deleting:
    uv run python -m pipeline.purge_invalid_tickers --dry-run
"""

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, select

from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import FundamentalsCache, IndexConstituent, TickerScore
from helpers.first import _first

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "purge_invalid_tickers.log"

logger = logging.getLogger(__name__)


def find_invalid_tickers(session: Session) -> list[str]:
    """Returns tickers with a confirmed-empty `profile` fetch that aren't a
    real index member -- see this module's docstring for the exact
    criteria."""
    index_tickers = set(session.exec(select(IndexConstituent.ticker)).all())
    profile_rows = session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "profile")).all()

    invalid = []
    for row in profile_rows:
        if row.ticker in index_tickers:
            continue
        try:
            data = json.loads(row.raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not _first(data).get("companyName"):
            invalid.append(row.ticker)
    return sorted(invalid)


def purge_invalid_tickers(dry_run: bool = False) -> list[str]:
    """Returns the tickers removed (or that would be removed, under
    --dry-run)."""
    with Session(engine) as session:
        tickers = find_invalid_tickers(session)
        if tickers and not dry_run:
            session.execute(delete(FundamentalsCache).where(FundamentalsCache.ticker.in_(tickers)))
            # Structurally shouldn't exist (compute_ticker_score refuses to
            # write a row when company_name is None), but delete defensively
            # rather than assume.
            session.execute(delete(TickerScore).where(TickerScore.ticker.in_(tickers)))
            session.commit()
    return tickers


def main(dry_run: bool = False) -> list[str]:
    configure_logging(LOG_PATH)
    init_db()
    tickers = purge_invalid_tickers(dry_run=dry_run)
    if not tickers:
        logger.info("No invalid ticker rows found.")
    elif dry_run:
        logger.info("Dry run: %d invalid ticker(s) would be purged: %s", len(tickers), ", ".join(tickers))
    else:
        logger.info("Purged %d invalid ticker(s): %s", len(tickers), ", ".join(tickers))
    return tickers


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete cache rows for tickers with a confirmed-empty FMP profile.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted without deleting.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    main(dry_run=cli_args.dry_run)
