"""Standalone script: the wipe of untouched, unprotected tickers. Spec: docs/specs/tracked-universe.md
("Planned: opt-in universe and wipe", NOT YET ACTIVE) and docs/decisions.md (2026-10-03).

**Not registered anywhere**: no crontab line, no CRON_JOB_NAMES entry, no `cron_heartbeat` (registering a heartbeat
without a cron entry would trip tests/test_cron_wiring.py). It is a manual tool until the cron reschedule is done.

A ticker is wiped when ALL of: its last touch (`TickerView.last_viewed_at`) is more than 30 days old, it has no
protection (index member of any index, any watchlist, a seed ETF / the Weinstein benchmark constant / the live
`rs_benchmark`, any owner-entered data, or an added ticker), and it is not added. A ticker with stored data but no
`TickerView` row and no protection is ADOPTED (stamped `last_viewed_at = now`, logged), never wiped blind; it becomes
eligible 30 days later. The decision logic is `data/tracked_universe.py::classify_wipe_candidates`; the tables and the
deletion order are `data/ticker_data_registry.py`.

**DRY-RUN IS THE DEFAULT and writes nothing**: it opens the database read-only (`mode=ro`), never calls `init_db`,
never creates the log file, never stamps an adoption. `--apply` is LOCKED: it refuses unless the environment variable
FATHOM_ALLOW_WIPE_APPLY=1 is set. **Until the opt-in universe ships (step 2), the added set is empty**: with it empty,
every viewed-only ticker (including the 25 the live universe holds today) would be wiped on day 30, so the lock stays
on until the added loader, the `added_at` column and the grandfathering are in place.

Apply mode: one transaction per ticker, opened with BEGIN IMMEDIATE (the journal mode is not WAL, so a long delete
would block the API: each ticker is small). Inside it the decision is re-checked from scratch (a ticker touched or
protected since the pass began is skipped), then rows are deleted in the registry order, `TickerView` last. FundamentalsCache
`forex_rate` rows are never touched. A failure rolls that ticker back and the run continues; the ticker simply stays
a candidate for the next run.

Run by hand (from backend/):
    uv run python -m pipeline.wipe_untouched_tickers                      # dry run: every decision, rows that WOULD go
    uv run python -m pipeline.wipe_untouched_tickers --tickers AAP,BB     # restrict to these tickers
    uv run python -m pipeline.wipe_untouched_tickers --limit 10           # act on at most 10 tickers (wipes first, oldest touch first)
    FATHOM_ALLOW_WIPE_APPLY=1 uv run python -m pipeline.wipe_untouched_tickers --apply   # LOCKED: do not run before step 2
"""

import argparse
import contextlib
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlmodel import Session

from core.logging_config import configure_logging
from core.models import TickerView
from core.tickers import normalize_ticker
from data.ticker_data_registry import WIPE_TABLES, TickerTable, unclassified_ticker_tables
from data.tracked_universe import (
    DECISION_ADOPT,
    DECISION_IGNORED,
    DECISION_NOT_DUE,
    DECISION_PROTECTED,
    DECISION_WIPE,
    WIPE_IDLE_DAYS,
    WipeDecision,
    classify_wipe_candidates,
)

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "wipe_untouched_tickers.log"
ALLOW_APPLY_ENV = "FATHOM_ALLOW_WIPE_APPLY"

logger = logging.getLogger(__name__)

# Outcomes (what a run did, or in a dry run would do, per ticker).
WIPED = "wiped"
ADOPTED = "adopted"
SKIPPED = "skipped"  # decided wipe/adopt up front, but the in-transaction re-check no longer agreed
FAILED = "failed"
NOT_ACTED = "not acted"  # protected / not due / ignored / beyond --limit


class ApplyLockedError(RuntimeError):
    """`--apply` without FATHOM_ALLOW_WIPE_APPLY=1."""


@dataclass
class TickerOutcome:
    ticker: str
    outcome: str
    decision: str
    protections: tuple[str, ...] = ()
    last_viewed_at: datetime | None = None
    days_idle: float | None = None
    delisted: bool = False
    rows: dict[str, int] = field(default_factory=dict)  # deleted (or, in a dry run, would-be-deleted) per table
    detail: str = ""


@dataclass
class WipeSummary:
    dry_run: bool
    outcomes: list[TickerOutcome]
    rows_by_table: dict[str, int]
    unclassified_tables: list[str]

    def count(self, outcome: str) -> int:
        return sum(1 for o in self.outcomes if o.outcome == outcome)

    def count_decision(self, decision: str) -> int:
        return sum(1 for o in self.outcomes if o.decision == decision)


def check_apply_allowed(environ: dict | None = None) -> None:
    """Raises ApplyLockedError unless FATHOM_ALLOW_WIPE_APPLY is exactly "1"."""
    if (environ if environ is not None else os.environ).get(ALLOW_APPLY_ENV) != "1":
        raise ApplyLockedError(
            f"--apply is locked: it deletes data for good and the opt-in universe (the added set) is not live yet, "
            f"so every viewed-only ticker would count as unprotected. Set {ALLOW_APPLY_ENV}=1 to release the lock "
            f"(only after the step-2 checklist in docs/decisions.md 2026-10-03 is done)."
        )


def load_added_tickers(session: Session) -> set[str]:
    """The explicitly added tickers. PLACEHOLDER until step 2 (the `added_at` column on TickerView): empty."""
    return set()


def read_only_engine(db_path: str | Path) -> Engine:
    """A SQLite engine that cannot write (`mode=ro`): the dry run's connection."""
    return create_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true", connect_args={"check_same_thread": False})


def _row_filter(entry: TickerTable) -> str:
    """The WHERE for one ticker's rows in one WIPE table (bound parameter :t)."""
    clause = f'"{entry.key_column}" = :t'
    return f"{clause} AND NOT ({entry.keep_where})" if entry.keep_where else clause


def count_rows(conn, ticker: str, present: set[str]) -> dict[str, int]:
    """Rows per WIPE table that a wipe of `ticker` would delete (read-only)."""
    counts: dict[str, int] = {}
    for entry in WIPE_TABLES:
        if entry.name not in present:
            continue
        n = conn.execute(text(f'SELECT COUNT(*) FROM "{entry.name}" WHERE {_row_filter(entry)}'), {"t": ticker}).scalar_one()
        if n:
            counts[entry.name] = n
    return counts


def _delete_rows(conn, entry: TickerTable, ticker: str) -> int:
    return conn.execute(text(f'DELETE FROM "{entry.name}" WHERE {_row_filter(entry)}'), {"t": ticker}).rowcount


def apply_one(
    engine: Engine, ticker: str, now: datetime, added: Iterable[str], present: set[str]
) -> tuple[str, WipeDecision, dict[str, int]]:
    """One ticker, one transaction (BEGIN IMMEDIATE). Re-evaluates the decision inside it: only a ticker that is still
    a wipe (or adopt) candidate is acted on; anything else is rolled back untouched and reported SKIPPED with its
    fresh decision. Returns (outcome, fresh decision, rows deleted per table)."""
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            with Session(bind=conn) as session:
                fresh = classify_wipe_candidates(session, now, added=added, tickers=[ticker])[ticker]
            rows: dict[str, int] = {}
            if fresh.decision == DECISION_WIPE:
                for entry in WIPE_TABLES:  # registry order: derived tables, caches, TickerView last
                    if entry.name not in present:
                        continue
                    deleted = _delete_rows(conn, entry, ticker)
                    if deleted:
                        rows[entry.name] = deleted
                outcome = WIPED
            elif fresh.decision == DECISION_ADOPT:
                conn.execute(sqlite_insert(TickerView).values(ticker=ticker, last_viewed_at=now).on_conflict_do_nothing())
                outcome = ADOPTED
            else:
                outcome = SKIPPED
            if outcome == SKIPPED:
                conn.rollback()
            else:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return outcome, fresh, rows


def _order_for_limit(decisions: dict[str, WipeDecision]) -> list[WipeDecision]:
    """Wipes first (oldest touch first), then adoptions (by ticker): the order `--limit` takes them in."""
    wipes = sorted((d for d in decisions.values() if d.decision == DECISION_WIPE), key=lambda d: (d.last_viewed_at, d.ticker))
    adopts = sorted((d for d in decisions.values() if d.decision == DECISION_ADOPT), key=lambda d: d.ticker)
    return wipes + adopts


def _log_outcome(prefix: str, o: TickerOutcome) -> None:
    rows = ", ".join(f"{table}={n}" for table, n in o.rows.items()) or "no rows"
    idle = f"{o.days_idle:.1f}d idle" if o.days_idle is not None else "no TickerView"
    viewed = o.last_viewed_at.strftime("%Y-%m-%d") if o.last_viewed_at else "-"
    protections = f" protections={','.join(o.protections)}" if o.protections else ""
    flag = " delisted" if o.delisted else ""
    detail = f" ({o.detail})" if o.detail else ""
    logger.info("%s%s: %s [decision=%s, last touch %s, %s%s%s] %s%s", prefix, o.ticker, o.outcome, o.decision, viewed, idle, flag, protections, rows, detail)


def run(
    engine: Engine,
    *,
    apply: bool = False,
    now: datetime | None = None,
    added: Iterable[str] | None = None,
    tickers: Iterable[str] | None = None,
    limit: int | None = None,
) -> WipeSummary:
    """The whole pass. `apply=False` only reads (counts the rows a wipe would delete). `apply=True` acts, ticker by
    ticker (see `apply_one`); the caller has already passed `check_apply_allowed`. Never raises for one ticker's
    failure: it is logged, counted and left a candidate."""
    now = now or datetime.now()
    wanted = [normalize_ticker(t) for t in tickers] if tickers is not None else None
    present = set(inspect(engine).get_table_names())
    unclassified = unclassified_ticker_tables(engine)
    if unclassified:
        logger.warning("Tables with a ticker-like column that are NOT in the registry: %s", ", ".join(unclassified))
        if apply:  # a table the wipe does not know about would keep a wiped ticker's rows (or worse): do not start
            raise RuntimeError(f"Refusing to --apply: unclassified per-ticker tables {unclassified} (add them to data/ticker_data_registry.py)")

    with Session(engine) as session:
        added_set = set(added) if added is not None else load_added_tickers(session)
        decisions = classify_wipe_candidates(session, now, added=added_set, tickers=wanted)

    ordered = _order_for_limit(decisions)
    acted = {d.ticker for d in (ordered if limit is None else ordered[: max(limit, 0)])}

    outcomes: list[TickerOutcome] = []
    rows_by_table: dict[str, int] = {}
    prefix = "" if apply else "[dry run] "
    # The read connection is for dry-run counting only; apply mode counts what it actually deleted.
    with contextlib.ExitStack() as stack:
        read_conn = None if apply else stack.enter_context(engine.connect())
        for ticker in sorted(decisions):
            d = decisions[ticker]
            o = TickerOutcome(
                ticker=ticker, outcome=NOT_ACTED, decision=d.decision, protections=d.protections,
                last_viewed_at=d.last_viewed_at, days_idle=d.days_idle, delisted=d.delisted,
            )
            if ticker in acted:
                if not apply:
                    o.outcome = WIPED if d.decision == DECISION_WIPE else ADOPTED
                    if d.decision == DECISION_WIPE:
                        o.rows = count_rows(read_conn, ticker, present)
                else:
                    try:
                        o.outcome, fresh, o.rows = apply_one(engine, ticker, now, added_set, present)
                        if o.outcome == SKIPPED:
                            o.detail = f"re-check says {fresh.decision}" + (f" ({','.join(fresh.protections)})" if fresh.protections else "")
                    except Exception as exc:  # noqa: BLE001 -- one ticker must not stop the run; it stays a candidate
                        o.outcome, o.detail = FAILED, f"{type(exc).__name__}: {exc}"
            elif d.decision in (DECISION_WIPE, DECISION_ADOPT):
                o.detail = "beyond --limit"
            outcomes.append(o)
            for table, n in o.rows.items():
                rows_by_table[table] = rows_by_table.get(table, 0) + n
            if o.outcome != NOT_ACTED or d.decision in (DECISION_WIPE, DECISION_ADOPT):
                _log_outcome(prefix, o)

    summary = WipeSummary(dry_run=not apply, outcomes=outcomes, rows_by_table=rows_by_table, unclassified_tables=unclassified)
    verb = "would be" if not apply else "were"
    logger.info(
        "%sWipe summary (idle > %d days): %d ticker(s) examined; wiped %d, adopted %d, skipped %d, failed %d; "
        "protected %d, not due %d, ignored %d. Rows %s deleted: %s.",
        prefix, WIPE_IDLE_DAYS, len(outcomes), summary.count(WIPED), summary.count(ADOPTED), summary.count(SKIPPED),
        summary.count(FAILED), summary.count_decision(DECISION_PROTECTED), summary.count_decision(DECISION_NOT_DUE),
        summary.count_decision(DECISION_IGNORED), verb,
        ", ".join(f"{t}={n}" for t, n in rows_by_table.items()) or "none",
    )
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wipe tickers untouched for 30 days that are not protected or added. Dry run unless --apply (locked)."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="The default: read the database read-only and report what would happen.")
    mode.add_argument("--apply", action="store_true", help=f"Delete for real. Refused unless {ALLOW_APPLY_ENV}=1 is set.")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated: examine only these tickers.")
    parser.add_argument("--limit", type=int, default=None, help="Act on at most N tickers (wipes first, oldest touch first, then adoptions).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> WipeSummary:
    args = _parse_args(argv)
    tickers = [t for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    if args.apply:
        check_apply_allowed()  # before anything is opened or configured
        configure_logging(LOG_PATH)
        from core.db import engine  # the real engine, imported only on the locked path

        return run(engine, apply=True, tickers=tickers, limit=args.limit)
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # stdout only: a dry run creates no log file
    from core.db import DB_PATH

    return run(read_only_engine(DB_PATH), apply=False, tickers=tickers, limit=args.limit)


if __name__ == "__main__":
    try:
        main()
    except ApplyLockedError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
