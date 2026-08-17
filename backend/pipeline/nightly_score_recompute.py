"""Standalone script: cache-only TickerScore recompute across the FULL
tracked universe -- index constituents, any ticker with cached FMP data, any
ticker with an existing TickerScore row, and any watchlisted ticker (see
nightly_fundamentals_fetch.py::load_full_tracked_universe, reused here rather
than duplicated). Reuses recompute_ticker_scores.py::recompute_all() verbatim
for the actual per-ticker work (compute_ticker_score(cache_only=True),
exception isolation, summary shape).

As of 2026-08-15, recompute_ticker_scores.py's own tickers=None default also
resolves to this exact same full-tracked-universe function (previously it
was scoped to just S&P 500 + Dow via load_universe_tickers -- the root cause
of a confirmed staleness bug, see that module's docstring and CLAUDE.md's
Speculative Growth section), so the two modules' default scope no longer
differs. This module still exists as the dedicated nightly cron entry point
(its own log file, always resolves the universe itself rather than relying
on a caller's default) -- see the IREN/SEZL/POOL motivation below, which is
independent of the universe-scoping bug and still the reason this sweep
runs on its own schedule rather than being folded into the other module.

Motivated by the IREN/SEZL/POOL missing-Overall-pill investigation: a
ticker viewed once (ad hoc) that got a bad/incomplete TickerScore row --
e.g. computed before its step4 inputs finished caching -- previously had
nothing that would ever revisit it, back when both the nightly fetch and
recompute_ticker_scores.py's default scope were S&P 500 + Dow-only (both
have since been widened to the full tracked universe -- see above). GET
/api/tickers/{ticker}/score now also self-heals a stale row on its own
(see core/main.py::ticker_score_out), but this sweep exists as a backstop
for tickers that are never viewed again after going stale, and to keep
every tracked ticker's Screener row reasonably fresh without waiting on a
page view.

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

from sqlmodel import Session

from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.tickers import normalize_ticker
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe
from pipeline.recompute_ticker_scores import recompute_all

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_score_recompute.log"

logger = logging.getLogger(__name__)


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
        return [normalize_ticker(t) for t in args.tickers.split(",") if t.strip()]
    if args.limit:
        init_db()
        with Session(engine) as session:
            all_tickers = load_full_tracked_universe(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.nightly_score_recompute"):
        asyncio.run(main(_resolve_cli_tickers(cli_args)))
