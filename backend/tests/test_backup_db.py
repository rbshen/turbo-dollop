import gzip
import sqlite3
from pathlib import Path

import pipeline.backup_db as backup_db


def _make_db(path: Path, value: str) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()
    return path


def test_create_backup_produces_a_consistent_compressed_snapshot(tmp_path):
    db_path = _make_db(tmp_path / "fathom.db", "hello")
    backup_dir = tmp_path / "backups"

    result = backup_db.create_backup(db_path=db_path, backup_dir=backup_dir, keep=14)

    assert result.exists()
    assert result.name.startswith("fathom_") and result.name.endswith(".db.gz")
    # No leftover temp file.
    assert list(backup_dir.glob("*.tmp")) == []

    restored = tmp_path / "restored.db"
    with gzip.open(result, "rb") as src, open(restored, "wb") as dst:
        dst.write(src.read())
    conn = sqlite3.connect(str(restored))
    assert conn.execute("SELECT v FROM t").fetchone() == ("hello",)
    conn.close()


def test_create_backup_never_touches_the_real_db_path_unless_passed(tmp_path):
    """create_backup takes db_path/backup_dir as explicit parameters rather
    than defaulting to the real DB -- confirm passing a throwaway path is
    all that's needed for a safe test, per CLAUDE.md's ad-hoc-script policy."""
    db_path = _make_db(tmp_path / "fathom.db", "only-this-db")
    backup_dir = tmp_path / "backups"

    result = backup_db.create_backup(db_path=db_path, backup_dir=backup_dir, keep=14)

    assert result.parent == backup_dir


def test_old_backups_beyond_retention_are_pruned(tmp_path):
    # Exercises _prune_old_backups directly against manually-created dummy
    # files, rather than sleeping between real create_backup() calls to get
    # distinct second-granularity timestamps -- faster and just as valid,
    # since pruning is pure filename-sort logic independent of how each
    # file was produced.
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    names = [f"fathom_2026080{i}_120000.db.gz" for i in range(1, 6)]
    for name in names:
        (backup_dir / name).write_bytes(b"fake")

    deleted = backup_db._prune_old_backups(backup_dir, "fathom", keep=3)

    remaining = sorted(p.name for p in backup_dir.glob("fathom_*.db.gz"))
    assert remaining == names[-3:]
    assert sorted(p.name for p in deleted) == names[:2]
