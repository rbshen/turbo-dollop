from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from core.config import BASE_DIR, settings

import core.models  # noqa: F401  (registers tables on SQLModel.metadata)

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


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    _drop_obsolete_columns()
