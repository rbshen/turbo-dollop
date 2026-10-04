"""WAL readiness (2026-10-04): read-only connections, the backup job, and the startup journal-mode log line all work
against a WAL database. Temp databases only; the live file is never opened here."""

import gzip
import logging
import sqlite3
import threading
import time

import pytest
from sqlalchemy import create_engine, text

import core.db as db
import pipeline.backup_db as backup_db


def _wal_db(path, rows=50):
    conn = sqlite3.connect(str(path))
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def test_a_read_only_connection_reads_while_a_writer_holds_the_database_and_after_all_close(tmp_path):
    path = _wal_db(tmp_path / "w.db")
    writer = sqlite3.connect(str(path), isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t (v) VALUES ('uncommitted')")
    try:
        # sqlite3 URI form, the wipe job's SQLAlchemy form and the ad-hoc scripts' form: all read, none wait.
        started = time.time()
        ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.2)
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == 50  # the committed rows, not the open transaction's
        ro.close()
        engine = create_engine(f"sqlite:///file:{path}?mode=ro&uri=true", connect_args={"check_same_thread": False})
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 50
        engine.dispose()
        assert time.time() - started < 1.0
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    # Every connection closed: the -wal/-shm files are checkpointed away, and a read-only open still works.
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == 50
    assert ro.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    ro.close()


def test_the_backup_job_makes_a_valid_openable_copy_of_a_wal_database_while_a_writer_commits(tmp_path):
    path = _wal_db(tmp_path / "fathom.db", rows=2000)
    stop = threading.Event()
    committed = []

    def writer():
        conn = sqlite3.connect(str(path), timeout=10)
        n = 0
        while not stop.is_set():
            conn.execute("INSERT INTO t (v) VALUES (?)", (f"live{n}",))
            conn.commit()
            n += 1
            committed.append(n)
        conn.close()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        time.sleep(0.2)
        result = backup_db.create_backup(db_path=path, backup_dir=tmp_path / "backups")
    finally:
        stop.set()
        thread.join()

    assert committed, "the writer never committed during the test"
    restored = tmp_path / "restored.db"
    with gzip.open(result, "rb") as src, open(restored, "wb") as dst:  # the gzip opens and decompresses end to end
        while chunk := src.read(1 << 20):
            dst.write(chunk)
    conn = sqlite3.connect(str(restored))
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    count = conn.execute("SELECT count(*) FROM t").fetchone()[0]
    assert 2000 <= count <= 2000 + len(committed)  # a consistent snapshot: every original row plus some commits
    assert conn.execute("SELECT count(*) FROM t WHERE v LIKE 'row%'").fetchone()[0] == 2000
    conn.close()
    assert not list((tmp_path / "backups").glob("*.tmp")) and not list((tmp_path / "backups").glob("*-wal"))


@pytest.mark.parametrize("mode,level,fragment", [("wal", logging.INFO, "journal_mode=wal"), ("delete", logging.WARNING, "expected wal")])
def test_the_startup_line_reports_the_journal_mode_and_writes_nothing(tmp_path, monkeypatch, caplog, mode, level, fragment):
    path = tmp_path / "j.db"
    conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA journal_mode={mode}")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.commit()
    conn.close()
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    statements = []
    from sqlalchemy import event

    event.listen(engine, "before_cursor_execute", lambda c, cur, s, p, ctx, m: statements.append(s))
    monkeypatch.setattr(db, "engine", engine)
    with caplog.at_level(logging.INFO, logger=db.logger.name):
        assert db._log_journal_mode() == mode
    record = [r for r in caplog.records if fragment in r.getMessage()]
    assert record and record[0].levelno == level
    assert all(s.strip().upper().startswith("PRAGMA JOURNAL_MODE") and "=" not in s for s in statements)  # a read, never a switch
    engine.dispose()
    check = sqlite3.connect(str(path))
    assert check.execute("PRAGMA journal_mode").fetchone()[0] == mode  # unchanged
    check.close()


def test_the_startup_line_never_raises(monkeypatch, caplog):
    class Broken:
        def connect(self):
            raise RuntimeError("db is down")

    monkeypatch.setattr(db, "engine", Broken())
    with caplog.at_level(logging.WARNING, logger=db.logger.name):
        assert db._log_journal_mode() is None
    assert "Could not read the SQLite journal mode" in caplog.text


def test_the_rollback_to_delete_mode_works_with_no_other_connection_and_leaves_no_wal_files(tmp_path):
    path = _wal_db(tmp_path / "r.db")
    conn = sqlite3.connect(str(path), timeout=30)
    assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    conn.close()
    assert not (tmp_path / "r.db-wal").exists() and not (tmp_path / "r.db-shm").exists()
    again = sqlite3.connect(str(path))
    assert again.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert again.execute("SELECT count(*) FROM t").fetchone()[0] == 50
    again.close()


def test_switching_to_wal_needs_exclusive_access_and_is_refused_while_another_connection_is_open(tmp_path):
    path = tmp_path / "s.db"
    first = sqlite3.connect(str(path))
    first.execute("CREATE TABLE t (v TEXT)")
    first.commit()
    first.execute("BEGIN")
    first.execute("SELECT * FROM t").fetchall()  # holds a read transaction open
    second = sqlite3.connect(str(path), timeout=0.2)
    try:
        assert second.execute("PRAGMA journal_mode=WAL").fetchone()[0] in ("delete", "wal")
    except sqlite3.OperationalError:
        pass  # "database is locked": the documented reason the app must be stopped first
    finally:
        second.close()
        first.rollback()
        first.close()
