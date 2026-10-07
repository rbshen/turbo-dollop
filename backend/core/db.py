import logging
from datetime import datetime

from sqlalchemy import DateTime, bindparam, inspect, text
from sqlmodel import SQLModel, create_engine

from core.config import BASE_DIR, settings

import core.models  # noqa: F401  (registers tables on SQLModel.metadata)
from core.models import SavedScreenerFilter

logger = logging.getLogger(__name__)

DB_PATH = (BASE_DIR / settings.database_path).resolve()
# How long a connection waits for another connection's lock before raising "database is locked" (sqlite3's `timeout`,
# which SQLite applies as PRAGMA busy_timeout; sqlite3's own default is 5 s). The journal mode is still the default
# (delete, not WAL), so a writer blocks readers while it commits and a long reader (the 03:30 UTC backup) blocks a
# commit. Most request handlers are `async def` calling the synchronous session, so a lock wait also freezes the event
# loop's single thread: 15 s is the compromise between riding out a long writer and stalling the API. Every engine that
# writes is this one (see docs/OPS_RUNBOOK.md, "Database locking"); read-only engines open the file with mode=ro.
SQLITE_BUSY_TIMEOUT_SECONDS = 15

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_SECONDS},
)

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
    # Economic Moat became a multiplier on the Steps score (2026-10-07): the per-tier points are gone. The three config columns
    # were NOT NULL, so they must really be dropped (a re-created config row could not insert without them); the stored points
    # on each TickerScore row meant nothing under the new formula (steps_score / moat_multiplier replace them).
    ("moatscoreconfig", "wide_moat_score"),
    ("moatscoreconfig", "narrow_moat_score"),
    ("moatscoreconfig", "no_moat_score"),
    ("tickerscore", "moat_score"),
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


_SAVED_FILTER_UNIQUE_NAME = "uq_saved_screener_filter_name_kind"


def _migrate_saved_filter_kind() -> bool:
    """SavedScreenerFilter gained `kind` ("stock" / "etf") with its name unique PER KIND (2026-10-02). The
    live table was created with UNIQUE(name) as a table constraint, which SQLite cannot drop or alter, and
    _add_missing_columns could only add `kind` as a plain nullable column: so this rebuilds the table once.
    Idempotent: a table whose DDL already names the per-kind constraint (a fresh create_all, or a table
    already rebuilt) is left alone. Every existing row is copied with kind = 'stock', ids and timestamps kept,
    all in one transaction (SQLite DDL is transactional, so a failure leaves the old table exactly as it
    was). Returns True when it rebuilt. Must run before _add_missing_columns."""
    inspector = inspect(engine)
    if not inspector.has_table("savedscreenerfilter"):
        return False
    with engine.begin() as conn:
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'savedscreenerfilter'")).scalar()
        if ddl is None or _SAVED_FILTER_UNIQUE_NAME in ddl:
            return False
        old_columns = {col["name"] for col in inspector.get_columns("savedscreenerfilter")}
        # sqlite3 opens a transaction only before DML, so BEGIN explicitly to put the DDL inside one.
        conn.exec_driver_sql("BEGIN")
        conn.execute(text('ALTER TABLE "savedscreenerfilter" RENAME TO "savedscreenerfilter_old"'))
        conn.execute(text('DROP INDEX IF EXISTS "ix_savedscreenerfilter_name"'))
        SavedScreenerFilter.__table__.create(bind=conn)
        copied = [c.name for c in SavedScreenerFilter.__table__.columns if c.name != "kind" and c.name in old_columns]
        cols = ", ".join(f'"{c}"' for c in copied)
        conn.execute(
            text(
                f'INSERT INTO "savedscreenerfilter" ({cols}, "kind") SELECT {cols}, \'stock\' FROM "savedscreenerfilter_old"'
            )
        )
        conn.execute(text('DROP TABLE "savedscreenerfilter_old"'))
    logger.info("Rebuilt savedscreenerfilter with a per-kind unique name (existing views kept as kind 'stock').")
    return True


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


def _log_journal_mode() -> str | None:
    """Logs the live file's journal mode at startup: INFO when it is "wal" (the intended mode since 2026-10-04, see
    docs/OPS_RUNBOOK.md, "WAL"), WARNING otherwise (a restore of an older backup brings back "delete", and a hand
    copy of the file loses the mode). `PRAGMA journal_mode` with no argument only reads: it never changes the mode and
    writes nothing. Never raises (a startup log line must not stop the app or a cron job). Returns the mode, or None."""
    try:
        with engine.connect() as conn:
            mode = str(conn.exec_driver_sql("PRAGMA journal_mode").scalar()).lower()
    except Exception as exc:  # noqa: BLE001 -- informational only
        logger.warning("Could not read the SQLite journal mode: %s: %s", type(exc).__name__, exc)
        return None
    if mode == "wal":
        logger.info("SQLite journal_mode=wal (busy timeout %d s).", SQLITE_BUSY_TIMEOUT_SECONDS)
    else:
        logger.warning(
            "SQLite journal_mode=%s, expected wal: readers block writers and the 03:30 UTC backup can stall commits "
            "(re-enable with the steps in docs/OPS_RUNBOOK.md, \"WAL\").",
            mode,
        )
    return mode


def _migrate_moat_and_overall_weights() -> dict:
    """One-time data migration for the Moat multiplier redesign (2026-10-07), run after _add_missing_columns and idempotent.

    1. The Moat config row gained `narrow_moat_multiplier` as a plain nullable column, so an existing row reads NULL: set the
       default 0.85.
    2. The four Overall weights used to add up to 69 (Moat was the other 31); they now add up to 100. A saved set that still
       adds up to 69 is converted: the old defaults (24/10/20/15) become the new defaults (30/20/20/30); a customised set is
       rescaled proportionally to 100 (scoring/weights.py::rescale_overall_to_100) and logged as a WARNING so it is not silent.
       Either way weights_version goes up by one. A set already adding up to 100 (a fresh seed, or this ran before) is left
       alone. Returns what it did, for the log and the report: {"moat_default_set", "weights": None | "defaults" | "rescaled", ...}.
    """
    from scoring.weights import DEFAULT_WEIGHTS, OLD_DEFAULT_OVERALL, as_dict, rescale_overall_to_100

    result: dict = {"moat_default_set": False, "weights": None}
    inspector = inspect(engine)
    # Inspected up front, not inside the transaction: on a single shared connection (the tests' StaticPool engine) the inspector's
    # own checkout would roll the open transaction back.
    has_moat_config, has_weights = inspector.has_table("moatscoreconfig"), inspector.has_table("scoreweightsettings")
    with engine.begin() as conn:
        if has_moat_config:
            # Read first, write only when needed: an already-migrated database (every start after the first, and every test that
            # boots the app against the real engine) must issue no write at all.
            if conn.execute(text("SELECT 1 FROM moatscoreconfig WHERE narrow_moat_multiplier IS NULL LIMIT 1")).first():
                conn.execute(text("UPDATE moatscoreconfig SET narrow_moat_multiplier = 0.85 WHERE narrow_moat_multiplier IS NULL"))
                result["moat_default_set"] = True
        if not has_weights:
            return result
        row = conn.execute(
            text(
                "SELECT overall_financials, overall_growth, overall_profitability, overall_debt FROM scoreweightsettings "
                "WHERE key = 'default'"
            )
        ).first()
        if row is None or sum(row) != 69:
            return result
        old = {"financials": row[0], "growth": row[1], "profitability": row[2], "debt": row[3]}
        if old == OLD_DEFAULT_OVERALL:
            new, kind = as_dict(DEFAULT_WEIGHTS.overall), "defaults"
        else:
            new, kind = rescale_overall_to_100(old), "rescaled"
        conn.execute(
            text(
                "UPDATE scoreweightsettings SET overall_financials = :f, overall_growth = :g, overall_profitability = :p, "
                "overall_debt = :d, weights_version = weights_version + 1, updated_at = :now WHERE key = 'default'"
            ).bindparams(bindparam("now", type_=DateTime())),
            {"f": new["financials"], "g": new["growth"], "p": new["profitability"], "d": new["debt"], "now": datetime.now()},
        )
        result.update(weights=kind, old=old, new=new)
    if kind == "rescaled":
        logger.warning("Overall weights were CUSTOM (%s, adding up to 69): rescaled proportionally to 100 -> %s.", old, new)
    else:
        logger.info("Overall weights were the old defaults %s: replaced with the new defaults %s.", old, new)
    return result


def _migrate_step5_weights() -> dict:
    """One-time data migration for the Step 5 hard-fail removal (2026-10-07), run after _migrate_moat_and_overall_weights and idempotent.

    Step 5 now has no hard fail, so the weights alone keep a breach below the Pass line, and its bounds got tighter (Debt/EBITDA at
    least 35, Debt Servicing and Current Ratio at most 30) with a strict order Debt/EBITDA > Servicing > Current Ratio. A saved
    Step 5 set that breaks any of that (the old 33/33/34 does) is replaced by the new defaults (scoring/weights.py) and
    weights_version goes up by one; a customised set that still satisfies the new rules is left alone. A set read from the row
    that is valid is never touched, so this issues no write on an already-migrated database. Returns {"weights": None | "defaults",
    "old": ...}."""
    from scoring.weights import DEFAULT_WEIGHTS, as_dict, validate_group

    result: dict = {"weights": None}
    if not inspect(engine).has_table("scoreweightsettings"):
        return result
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT step5_current_ratio, step5_debt_to_ebitda, step5_debt_servicing FROM scoreweightsettings WHERE key = 'default'"
            )
        ).first()
        if row is None:
            return result
        old = {"current_ratio": row[0], "debt_to_ebitda": row[1], "debt_servicing": row[2]}
        if not validate_group("step5", old):
            return result
        new = as_dict(DEFAULT_WEIGHTS.step5)
        conn.execute(
            text(
                "UPDATE scoreweightsettings SET step5_current_ratio = :c, step5_debt_to_ebitda = :d, step5_debt_servicing = :s, "
                "weights_version = weights_version + 1, updated_at = :now WHERE key = 'default'"
            ).bindparams(bindparam("now", type_=DateTime())),
            {"c": new["current_ratio"], "d": new["debt_to_ebitda"], "s": new["debt_servicing"], "now": datetime.now()},
        )
        result.update(weights="defaults", old=old, new=new)
    logger.warning("Step 5 weights %s broke the new bounds/ordering (no hard fail since 2026-10-07): replaced with the defaults %s.", old, new)
    return result


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_saved_filter_kind()
    _add_missing_columns()
    _migrate_moat_and_overall_weights()
    _migrate_step5_weights()
    _ensure_unique_indexes()
    _drop_obsolete_columns()
    _seed_ticker_views()
    _log_journal_mode()
