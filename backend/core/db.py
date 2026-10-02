import logging
from datetime import datetime

from sqlalchemy import DateTime, bindparam, inspect, text
from sqlmodel import SQLModel, create_engine

from core.config import BASE_DIR, settings

import core.models  # noqa: F401  (registers tables on SQLModel.metadata)

logger = logging.getLogger(__name__)

DB_PATH = (BASE_DIR / settings.database_path).resolve()
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

# (table_name, column_name) pairs for columns a model USED to define and no
# longer does. Unlike a column that's merely unreferenced-but-still-present
# (fine to leave alone -- see _add_missing_columns' own docstring), a
# column that was NOT NULL with no default (like TechnicalEntrySignal's
# original `fired` boolean) breaks every future INSERT once the model
# drops it: SQLAlchemy's insert only supplies columns the model still
# knows about, so SQLite's NOT NULL constraint rejects every row. Genuinely
# dropping the column (not just ignoring it) is the only fix -- confirmed
# via a real IntegrityError when TechnicalEntrySignal.fired was replaced
# by fired_at (2026-09-09). SQLite's ALTER TABLE ... DROP COLUMN needs
# 3.35+ (bundled with Python 3.12's sqlite3 well past that).
_OBSOLETE_COLUMNS: list[tuple[str, str]] = [
    ("technicalentrysignal", "fired"),
    # Screener Country filter removed with non-US ticker support (2026-09-26).
    ("tickerscore", "country"),
    ("savedscreenerfilter", "country"),
    # Verified tick confirmed to have zero downstream effect (2026-09-27).
    ("datagroupsetting", "tier_verified"),
    # Trend-structure (swing/BOS) engine removed (2026-10-01): the TrendAnalysis trend columns, whose
    # NOT NULL ones (trend_state, persistence_count, warning_flag, blended_score, bar_level) would
    # otherwise reject every INSERT now that the model no longer supplies them.
    *[
        ("trendanalysis", col)
        for col in (
            "trend_state", "magnitude_tier", "persistence_count", "bars_since_confirmation",
            "last_confirmed_swing_json", "warning_flag", "warning_swing_json", "pullback_occurred_since_flip",
            "trend_started_json", "trend_started_is_lower_bound", "pullback_history_json", "reversal_history_json",
            "efficiency_ratio", "regime", "blended_score", "bar_level", "ad_bullish_divergence",
            "ad_divergence_swing_date", "sma20_position_pct", "sma20_cross", "sma50_position_pct", "sma50_cross",
            "sma200_position_pct", "sma200_cross",
        )
    ],
    # Screener Reversal/Pullback filters removed with the same engine.
    ("tickerscore", "reversal_status"),
    ("tickerscore", "pullback_status"),
]


def _drop_obsolete_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, column_name in _OBSOLETE_COLUMNS:
            if not inspector.has_table(table_name):
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            if column_name not in existing_columns:
                continue
            conn.execute(text(f'ALTER TABLE "{table_name}" DROP COLUMN "{column_name}"'))


def _add_missing_columns() -> None:
    """This app has no migration tooling (see DiscountRateConfig's own
    comment) -- SQLModel.metadata.create_all() only creates tables that
    don't exist yet, it never adds columns to a table that's already
    there (e.g. TickerScore gaining `moat`/`moat_score` on an existing,
    already-populated DB). SQLite's ADD COLUMN is cheap and safe for the
    nullable columns every model here uses, so this is a minimal
    add-if-missing sweep run on every startup, rather than standing up a
    real migration framework for what's so far been a rare event."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                column_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'))


# (index name, table, columns). _add_missing_columns is add-column-only and
# create_all skips indexes on pre-existing tables, so a unique index that must
# exist on an already-populated DB is created here, idempotently.
_UNIQUE_INDEXES: list[tuple[str, str, tuple[str, ...]]] = [
    ("uq_pricetargetsnapshot_ticker_date", "pricetargetsnapshot", ("ticker", "snapshot_date")),
]


def _ensure_unique_indexes() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for name, table, columns in _UNIQUE_INDEXES:
            if not inspector.has_table(table):
                continue
            cols = ", ".join(f'"{c}"' for c in columns)
            conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols})'))


# One-time seed of TickerView (data/tracked_universe.py), written when the table was introduced
# (2026-10-02). Every ticker the app already held a profile, score row, watchlist entry or index
# membership for is stamped "viewed now", so nothing leaves the nightly universe for 30 days after the
# first start on the new code. Gate: the table is empty. Once any row exists (the seed's own, or a real
# view) a later init_db() does nothing, so the grace dates never move on a repeated call, a restart or a
# cron job's init_db(). Plain SQL on purpose: core must not import data.
_SEED_TICKER_VIEWS_SQL = text(
    """
    INSERT OR IGNORE INTO tickerview (ticker, last_viewed_at)
    SELECT ticker, :now FROM (
        SELECT ticker FROM fundamentalscache WHERE statement_type = 'profile'
        UNION SELECT ticker FROM tickerscore
        UNION SELECT ticker FROM watchlistticker
        UNION SELECT ticker FROM indexconstituent WHERE index_name IN ('sp500', 'dow', 'nasdaq')
    )
    """
).bindparams(bindparam("now", type_=DateTime()))


def _seed_ticker_views(now: datetime | None = None) -> int:
    """Returns the number of rows seeded (0 when the table already has rows)."""
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM tickerview LIMIT 1")).first() is not None:
            return 0
        seeded = conn.execute(_SEED_TICKER_VIEWS_SQL, {"now": now or datetime.now()}).rowcount
    if seeded:
        logger.info("Seeded %d ticker_view rows (30-day grace from now for every existing ticker).", seeded)
    return seeded


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    _ensure_unique_indexes()
    _drop_obsolete_columns()
    _seed_ticker_views()
