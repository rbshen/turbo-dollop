"""Standalone script: the one-time grandfather backfill of the opt-in universe (step 2). Spec:
docs/specs/tracked-universe.md ("Planned: opt-in universe and wipe") and docs/decisions.md (2026-10-03).

Marks every ticker that is in the universe TODAY ONLY through the "viewed" reason as added
(`TickerView.added_at = now (UTC)`, `added_source = 'grandfathered'`), so that when the classification later flips
`viewed` to `added`, nothing that is in a screener today drops out (18 stocks would leave the Stocks Screener and 7 ETF
rows would be deleted by the 1:45 ETF job). The set is computed from the live classification
(`classify_known_tickers` for stocks, `classify_etf_tickers` for ETFs: reason == "viewed"), never hard-coded.

Guards: a ticker with ANY protection (index of any name, watchlist, seed/benchmark, manual data) is refused, because
protections need no state (re-checked from the raw sets, independent of the reason); a ticker already added is skipped
and never overwritten (idempotent). The classification itself is NOT changed by this script or by the columns it
writes: `_classify` does not read them.

**Not registered anywhere** (no crontab line, no CRON_JOB_NAMES entry, no heartbeat). DRY-RUN IS THE DEFAULT and
writes nothing (read-only connection, no `init_db`, no log file). `--apply` writes exactly the selected tickers in ONE
transaction (BEGIN IMMEDIATE), and rolls back if the row count is not exactly the number selected.

Run by hand (from backend/):
    uv run python -m pipeline.grandfather_universe              # dry run: the list, split stock / ETF, with last_viewed_at
    uv run python -m pipeline.grandfather_universe --apply      # writes added_at / added_source for exactly that list
"""

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from core.logging_config import configure_logging
from core.models import TickerView
from data.tracked_universe import (
    VIEWED,
    classify_etf_tickers,
    classify_known_tickers,
    classify_wipe_candidates,
)
from pipeline.wipe_untouched_tickers import read_only_engine

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "grandfather_universe.log"
SOURCE = "grandfathered"

logger = logging.getLogger(__name__)


@dataclass
class GrandfatherPlan:
    stocks: dict[str, datetime | None] = field(default_factory=dict)  # ticker -> last_viewed_at
    etfs: dict[str, datetime | None] = field(default_factory=dict)
    already_added: list[str] = field(default_factory=list)  # viewed-only reason, but added_at already set: skipped
    refused: dict[str, tuple[str, ...]] = field(default_factory=dict)  # reason "viewed" but a protection exists

    @property
    def tickers(self) -> list[str]:
        return sorted(set(self.stocks) | set(self.etfs))


def plan_grandfather(session: Session, now: datetime | None = None) -> GrandfatherPlan:
    """The set to mark, from the live classification. Reads only."""
    now = now or datetime.now()
    views = {row.ticker: row for row in session.exec(select(TickerView)).all()}
    plan = GrandfatherPlan()
    viewed: dict[str, dict] = {"stock": {}, "etf": {}}
    for side, reasons in (("stock", classify_known_tickers(session, now)), ("etf", classify_etf_tickers(session, now))):
        for ticker, reason in reasons.items():
            if reason == VIEWED:
                viewed[side][ticker] = reason

    candidates = sorted(set(viewed["stock"]) | set(viewed["etf"]))
    # Independent re-check from the raw protection sets (an empty added set: this is about protections only).
    checks = classify_wipe_candidates(session, now, added=(), tickers=candidates) if candidates else {}
    for side, target in (("stock", plan.stocks), ("etf", plan.etfs)):
        for ticker in sorted(viewed[side]):
            row = views.get(ticker)
            protections = checks[ticker].protections
            if protections:
                plan.refused[ticker] = protections
            elif row is not None and row.added_at is not None:
                plan.already_added.append(ticker)
            else:
                target[ticker] = row.last_viewed_at if row is not None else None
    return plan


def apply_plan(engine: Engine, tickers: list[str], now_utc: datetime) -> int:
    """Sets added_at/added_source for exactly `tickers`, only where added_at is still NULL, in one BEGIN IMMEDIATE
    transaction. Rolls back and raises unless exactly len(tickers) rows changed."""
    if not tickers:
        return 0
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            params = {f"t{i}": t for i, t in enumerate(tickers)}
            statement = text(
                "UPDATE tickerview SET added_at = :now, added_source = :source "
                f"WHERE added_at IS NULL AND ticker IN ({', '.join(':' + k for k in params)})"
            ).bindparams(bindparam("now", type_=DateTime()))
            result = conn.execute(statement, {"now": now_utc, "source": SOURCE, **params})
            if result.rowcount != len(tickers):
                raise RuntimeError(f"Expected to mark {len(tickers)} tickers, would have marked {result.rowcount}: rolled back")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return len(tickers)


def run(engine: Engine, *, apply: bool = False, now: datetime | None = None) -> GrandfatherPlan:
    """Plans (always read-only) and, with `apply`, writes. Returns the plan."""
    now = now or datetime.now()
    with Session(engine) as session:
        plan = plan_grandfather(session, now)
    prefix = "" if apply else "[dry run] "
    for label, group in (("stock", plan.stocks), ("ETF", plan.etfs)):
        for ticker, viewed in group.items():
            logger.info("%s%s %s: last_viewed_at %s -> added (%s)", prefix, label, ticker, viewed.strftime("%Y-%m-%d %H:%M") if viewed else "-", SOURCE)
    for ticker in plan.already_added:
        logger.info("%s%s: already added, skipped", prefix, ticker)
    for ticker, protections in plan.refused.items():
        logger.warning("%s%s: REFUSED, has protection %s (needs no state)", prefix, ticker, ",".join(protections))
    logger.info(
        "%sGrandfather plan: %d to mark (%d stocks, %d ETFs), %d already added, %d refused.",
        prefix, len(plan.tickers), len(plan.stocks), len(plan.etfs), len(plan.already_added), len(plan.refused),
    )
    if apply:
        marked = apply_plan(engine, plan.tickers, datetime.now(timezone.utc).replace(tzinfo=None))
        logger.info("Marked %d ticker(s) added (source %s).", marked, SOURCE)
    return plan


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mark today's viewed-only tickers as added (grandfathered). Dry run unless --apply.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="The default: read the database read-only and print the list.")
    mode.add_argument("--apply", action="store_true", help="Write added_at/added_source for exactly the listed tickers, in one transaction.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> GrandfatherPlan:
    args = _parse_args(argv)
    if args.apply:
        configure_logging(LOG_PATH)
        from core.db import engine, init_db

        init_db()  # the cron/script convention; adds the two columns when a database lacks them
        return run(engine, apply=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # stdout only: a dry run creates no log file
    from core.db import DB_PATH

    return run(read_only_engine(DB_PATH), apply=False)


if __name__ == "__main__":
    main()
