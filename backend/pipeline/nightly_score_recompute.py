"""Standalone script: cache-only TickerScore recompute across the FULL
tracked universe -- every ticker that has any cached FMP data or an
existing TickerScore row, not just the S&P 500 + Dow constituent lists
recompute_ticker_scores.py's own default (load_universe_tickers) is scoped
to. Reuses recompute_ticker_scores.py::recompute_all() verbatim for the
actual per-ticker work (compute_ticker_score(cache_only=True), exception
isolation, summary shape) -- only the ticker-source function differs.

Motivated by the IREN/SEZL/POOL missing-Overall-pill investigation: a
ticker viewed once (ad hoc, not via the nightly S&P 500/Dow fetch) that
got a bad/incomplete TickerScore row -- e.g. computed before its step4
inputs finished caching -- previously had nothing that would ever revisit
it, since neither the nightly fetch nor recompute_ticker_scores.py's
default scope include it. GET /api/tickers/{ticker}/score now also
self-heals a stale row on its own (see core/main.py::ticker_score_out),
but this sweep exists as a backstop for tickers that are never viewed
again after going stale, and to keep every tracked ticker's Screener row
reasonably fresh without waiting on a page view.

Pure computation, no network -- makes zero FMP calls, safe to run anytime,
no rate-limit pacing needed (unlike nightly_fundamentals_fetch.py).

Run against the full tracked universe:
    uv run python -m pipeline.nightly_score_recompute

Run against a small subset first:
    uv run python -m pipeline.nightly_score_recompute --limit 15
    uv run python -m pipeline.nightly_score_recompute --tickers AAPL,MSFT,ZZZZINVALID
"""

import argparse
import asyncio
import logging
from pathlib import Path

from sqlmodel import Session, select

from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import FundamentalsCache, IndexConstituent, TickerScore
from pipeline.nightly_fundamentals_fetch import load_universe_tickers
from pipeline.recompute_ticker_scores import recompute_all

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_score_recompute.log"

logger = logging.getLogger(__name__)


def load_full_tracked_universe(session: Session) -> list[str]:
    """Union of every ticker this app has ever touched: index constituents
    (S&P 500 + Dow), any ticker with at least one cached FMP fetch, and any
    ticker that already has a TickerScore row -- the last two are almost
    always a subset of each other (compute_ticker_score requires cached
    data to produce a row at all), but unioned defensively rather than
    assumed."""
    index_tickers = load_universe_tickers(session)
    cached_tickers = session.exec(select(FundamentalsCache.ticker).distinct()).all()
    scored_tickers = session.exec(select(TickerScore.ticker)).all()
    return sorted(set(index_tickers) | set(cached_tickers) | set(scored_tickers))


async def main(tickers: list[str] | None = None) -> dict:
    """Standalone-script entry point: sets up file+console logging and
    ensures the DB schema exists, resolves the full tracked universe if no
    explicit ticker list was passed, then delegates the actual work to
    recompute_all() (unchanged, reused as-is)."""
    configure_logging(LOG_PATH)
    init_db()

    if tickers is None:
        with Session(engine) as session:
            tickers = load_full_tracked_universe(session)

    logger.info("Starting full-universe cache-only score recompute for %d tickers.", len(tickers))
    return await recompute_all(tickers)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cache-only Screener score recompute for the full tracked ticker universe.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the full universe (for testing)."
    )
    return parser.parse_args()


def _resolve_cli_tickers(args: argparse.Namespace) -> list[str] | None:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.limit:
        init_db()
        with Session(engine) as session:
            all_tickers = load_full_tracked_universe(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
