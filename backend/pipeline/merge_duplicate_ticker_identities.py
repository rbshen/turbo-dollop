"""Standalone script: merges duplicate ticker identities left over from
before `normalize_ticker()` (core/tickers.py) existed as a single ingest
choke point -- e.g. BRK.B and BRK-B, both live independently across
FundamentalsCache/TickerScore/TickerMoat/WatchlistTicker/etc for the same
real company, because no entry point normalized dot vs hyphen notation
before now. See CLAUDE.md's "Ticker dot/hyphen normalization" section for
the full investigation.

Every ticker-bearing table is handled by one generic merge primitive,
dispatched by TABLE_CONFIGS below, rather than one algorithm per table:
for each ticker value V anywhere in a table where normalize_ticker(V) !=
V, every row under V or its canonical form is grouped (by whatever columns
make a row's identity distinct from a duplicate, e.g. FundamentalsCache's
(statement_type, period) -- empty for a table where ticker alone is
already the primary key). Within each group, the freshest row (or, for a
table with no meaningful freshness column, whichever row is already on
the canonical ticker) wins: every other row in the group is deleted, and
the winner is renamed to the canonical ticker if it wasn't already there.

Idempotent and safe to re-run: a run that finds no non-canonical ticker
value anywhere makes zero writes, dry-run or not.

Run (merges for real):
    uv run python -m pipeline.merge_duplicate_ticker_identities

Preview without changing anything:
    uv run python -m pipeline.merge_duplicate_ticker_identities --dry-run
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, update
from sqlmodel import Session, SQLModel, select

from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import (
    FundamentalsCache,
    GrowthCatalystNote,
    IndexConstituent,
    NewsCache,
    PriceTargetSnapshot,
    TickerBankCapitalMetrics,
    TickerCustomValuation,
    TickerMoat,
    TickerScore,
    WatchlistTicker,
)
from core.tickers import normalize_ticker

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "merge_duplicate_ticker_identities.log"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableMergeConfig:
    model: type[SQLModel]
    # Columns (besides ticker) that make a row's identity distinct from a
    # duplicate under the other ticker spelling -- e.g. FundamentalsCache
    # rows only collide if they share (statement_type, period) too. Empty
    # for a table where ticker alone is the primary key.
    group_by: tuple[str, ...]
    # Column identifying a single row for UPDATE/DELETE -- "ticker" itself
    # for a ticker-primary-keyed table, else the surrogate "id".
    pk_attr: str
    # Column to prefer-freshest by when two rows collide in the same group.
    # None for a table with no meaningful freshness signal (WatchlistTicker
    # membership), in which case whichever row is already on the canonical
    # ticker wins instead.
    freshness_attr: str | None


TABLE_CONFIGS = [
    TableMergeConfig(TickerScore, (), "ticker", "computed_at"),
    TableMergeConfig(TickerMoat, (), "ticker", "updated_at"),
    TableMergeConfig(TickerBankCapitalMetrics, (), "ticker", "updated_at"),
    TableMergeConfig(TickerCustomValuation, (), "ticker", "saved_at"),
    TableMergeConfig(GrowthCatalystNote, (), "ticker", "updated_at"),
    TableMergeConfig(NewsCache, (), "ticker", "fetched_at"),
    TableMergeConfig(FundamentalsCache, ("statement_type", "period"), "id", "fetched_at"),
    TableMergeConfig(WatchlistTicker, ("watchlist_id",), "id", None),
    TableMergeConfig(IndexConstituent, ("index_name",), "id", "last_synced_at"),
    TableMergeConfig(PriceTargetSnapshot, ("snapshot_date",), "id", "fetched_at"),
]


@dataclass(frozen=True)
class _DeleteAction:
    config: TableMergeConfig
    pk_value: Any
    ticker: str
    group: tuple


@dataclass(frozen=True)
class _RenameAction:
    config: TableMergeConfig
    pk_value: Any
    old_ticker: str
    new_ticker: str
    group: tuple


_Action = _DeleteAction | _RenameAction


def find_ticker_pairs(session: Session) -> list[tuple[str, str]]:
    """Scans every configured table for a ticker value whose
    normalize_ticker() output differs from itself -- returns (dot_form,
    canonical) pairs, deduped and sorted. Deliberately does not hardcode
    which tickers are dot-form: any table drifting from canonical in the
    future (not just BRK.B/BF.B) is picked up the same way."""
    pairs: set[tuple[str, str]] = set()
    for config in TABLE_CONFIGS:
        values = session.exec(select(config.model.ticker).distinct()).all()
        for value in values:
            canonical = normalize_ticker(value)
            if canonical != value:
                pairs.add((value, canonical))
    return sorted(pairs)


def _plan_pair(session: Session, config: TableMergeConfig, dot_form: str, canonical: str) -> list[_Action]:
    model = config.model
    rows = session.exec(select(model).where(model.ticker.in_([dot_form, canonical]))).all()
    if not rows:
        return []

    groups: dict[tuple, list] = {}
    for row in rows:
        key = tuple(getattr(row, col) for col in config.group_by)
        groups.setdefault(key, []).append(row)

    actions: list[_Action] = []
    for key, group_rows in groups.items():
        if len(group_rows) > 1:
            if config.freshness_attr is not None:
                group_rows = sorted(
                    group_rows,
                    key=lambda r: (getattr(r, config.freshness_attr), r.ticker == canonical),
                    reverse=True,
                )
            else:
                group_rows = sorted(group_rows, key=lambda r: r.ticker == canonical, reverse=True)
        winner, *losers = group_rows

        for loser in losers:
            actions.append(_DeleteAction(config, getattr(loser, config.pk_attr), loser.ticker, key))
        if winner.ticker != canonical:
            actions.append(_RenameAction(config, getattr(winner, config.pk_attr), winner.ticker, canonical, key))

    return actions


def _apply_action(session: Session, action: _Action) -> None:
    model = action.config.model
    pk_col = getattr(model, action.config.pk_attr)
    if isinstance(action, _DeleteAction):
        session.execute(delete(model).where(pk_col == action.pk_value))
    else:
        session.execute(update(model).where(pk_col == action.pk_value).values(ticker=action.new_ticker))


def _describe(action: _Action) -> str:
    table = action.config.model.__tablename__
    if isinstance(action, _DeleteAction):
        return f"{table}: delete {action.config.pk_attr}={action.pk_value!r} (ticker={action.ticker}, group={action.group})"
    return f"{table}: rename {action.config.pk_attr}={action.pk_value!r} from {action.old_ticker} to {action.new_ticker} (group={action.group})"


def merge_duplicate_ticker_identities(dry_run: bool = False) -> list[str]:
    """Returns the human-readable list of changes made (or that would be
    made, under --dry-run) -- dry_run performs zero writes, mirroring
    purge_invalid_tickers.py's own convention."""
    with Session(engine) as session:
        pairs = find_ticker_pairs(session)
        actions: list[_Action] = []
        for dot_form, canonical in pairs:
            for config in TABLE_CONFIGS:
                actions.extend(_plan_pair(session, config, dot_form, canonical))

        descriptions = [_describe(a) for a in actions]
        if actions and not dry_run:
            for action in actions:
                _apply_action(session, action)
            session.commit()
    return descriptions


def main(dry_run: bool = False) -> list[str]:
    configure_logging(LOG_PATH)
    init_db()
    changes = merge_duplicate_ticker_identities(dry_run=dry_run)
    if not changes:
        logger.info("No duplicate ticker identities found.")
    elif dry_run:
        logger.info("Dry run: %d change(s) would be made:", len(changes))
        for line in changes:
            logger.info("  %s", line)
    else:
        logger.info("Merged duplicate ticker identities, %d change(s):", len(changes))
        for line in changes:
            logger.info("  %s", line)
    return changes


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge duplicate dot/hyphen ticker identities across every ticker-bearing table.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without changing anything.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    main(dry_run=cli_args.dry_run)
