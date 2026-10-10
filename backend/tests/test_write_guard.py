"""The conftest write guard (`_forbid_write`) blocks writes AND schema changes on the real fathom.db engine only.
Never touches the real file: the behaviour is proven on a temp-file engine that carries the same listener."""

import pytest
from sqlalchemy import create_engine, event, inspect, text

from core.db import engine as real_engine
from conftest import _forbid_write  # the module pytest loaded (tests/ is on sys.path), so the identity matches the listener


def _guarded_engine(tmp_path):
    path = tmp_path / "guarded.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:  # built before the listener is attached, like the real file
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, keep TEXT, extra TEXT)"))
        conn.execute(text("INSERT INTO t (keep, extra) VALUES ('a', 'b')"))
    event.listen(engine, "before_cursor_execute", _forbid_write)
    return engine


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE t DROP COLUMN extra",
        "  alter table t add column z TEXT",
        "DROP TABLE t",
        "CREATE TABLE u (id INTEGER)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix ON t (keep)",
        "REINDEX",
        "VACUUM",
    ],
)
def test_schema_changes_on_a_guarded_engine_fail_and_leave_the_file_untouched(tmp_path, statement):
    engine = _guarded_engine(tmp_path)
    with pytest.raises(RuntimeError, match="SCHEMA change"):
        with engine.begin() as conn:
            conn.execute(text(statement))
    assert [c["name"] for c in inspect(engine).get_columns("t")] == ["id", "keep", "extra"]
    assert inspect(engine).get_table_names() == ["t"]


@pytest.mark.parametrize("statement", ["INSERT INTO t (keep) VALUES ('x')", "UPDATE t SET keep='y'", "DELETE FROM t"])
def test_row_writes_on_a_guarded_engine_still_fail(tmp_path, statement):
    with pytest.raises(RuntimeError, match="write to the REAL"):
        with _guarded_engine(tmp_path).begin() as conn:
            conn.execute(text(statement))


def test_reads_on_a_guarded_engine_still_work(tmp_path):
    engine = _guarded_engine(tmp_path)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT keep FROM t")).scalar() == "a"
        assert conn.execute(text("PRAGMA table_info(t)")).fetchall()


def test_an_unguarded_in_memory_engine_can_still_create_and_alter_tables():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER, extra TEXT)"))
        conn.execute(text("ALTER TABLE t DROP COLUMN extra"))
    assert [c["name"] for c in inspect(engine).get_columns("t")] == ["id"]


def test_the_session_guard_is_attached_to_the_real_engine():
    assert event.contains(real_engine, "before_cursor_execute", _forbid_write)
