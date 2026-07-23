from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from config import BASE_DIR, settings

import models  # noqa: F401  (registers tables on SQLModel.metadata)

DB_PATH = (BASE_DIR / settings.database_path).resolve()
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


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
