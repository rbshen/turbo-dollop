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

    result = backup_db.create_backup(db_path=db_path, backup_dir=backup_dir)

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

    result = backup_db.create_backup(db_path=db_path, backup_dir=backup_dir)

    assert result.parent == backup_dir


def _touch_backups(backup_dir: Path, dates: list[str]) -> list[Path]:
    """One dummy backup per YYYYMMDD date (fixed time-of-day)."""
    backup_dir.mkdir(exist_ok=True)
    paths = []
    for d in dates:
        path = backup_dir / f"fathom_{d}_035503.db.gz"
        path.write_bytes(b"fake")
        paths.append(path)
    return paths


def _select(paths, keep_daily=7, keep_weekly=4):
    return sorted(p.name for p in backup_db.select_backups_to_prune(paths, "fathom", keep_daily, keep_weekly))


def _names(dates):
    return [f"fathom_{d}_035503.db.gz" for d in dates]


def test_prune_matches_the_real_14_backups_on_disk_on_2026_09_21(tmp_path):
    """Replays the exact set of files that existed when this policy was
    adopted (one per day, 09-08..09-21; 09-13 and 09-20 are Sundays)."""
    dates = [f"202609{d:02d}" for d in range(8, 22)]
    paths = _touch_backups(tmp_path, dates)

    deleted = _select(paths)

    # Daily tier keeps 09-15..09-21. Weekly tier: the week of 09-14 is
    # already represented by 09-20 (in the daily tier), so the next weekly
    # copy is the Sunday 09-13; the week of 09-07's other days and 09-14
    # (not its week's last backup) go.
    assert deleted == _names(["20260908", "20260909", "20260910", "20260911", "20260912", "20260914"])
    assert len(paths) - len(deleted) == 8


def test_steady_state_keeps_seven_daily_plus_four_weekly(tmp_path):
    # 60 consecutive days ending on a Wednesday (2026-09-23).
    from datetime import date, timedelta

    end = date(2026, 9, 23)
    dates = [(end - timedelta(days=i)).strftime("%Y%m%d") for i in range(60)]
    paths = _touch_backups(tmp_path, dates)

    deleted = set(_select(paths))
    kept = sorted(p.name for p in paths if p.name not in deleted)

    daily = [f"202609{d}" for d in range(17, 24)]  # 09-17..09-23 (includes Sunday 09-20)
    sundays = ["20260913", "20260906", "20260830", "20260823"]
    assert kept == sorted(_names(daily + sundays))


def test_weekly_falls_back_to_last_backup_of_the_week_when_sunday_is_missing(tmp_path):
    # Sunday 09-13 failed; Saturday 09-12 is that week's last backup.
    dates = ["20260907", "20260908", "20260912", "20260915", "20260916", "20260917", "20260918", "20260919", "20260920", "20260921"]
    paths = _touch_backups(tmp_path, dates)

    deleted = _select(paths, keep_daily=7, keep_weekly=1)

    assert deleted == _names(["20260907", "20260908"])  # 09-12 survives as the weekly copy


def test_an_outage_does_not_shrink_the_daily_tier_below_seven_copies(tmp_path):
    # Job was down for two weeks: the newest 7 backups on disk are all old,
    # but they are still the newest 7 -- retention counts backups, not days.
    dates = [f"202608{d:02d}" for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    paths = _touch_backups(tmp_path, dates)

    deleted = _select(paths, keep_daily=7, keep_weekly=0)

    assert deleted == _names(["20260801", "20260802", "20260803"])


def test_every_file_on_a_kept_date_is_kept_and_on_a_dropped_date_dropped(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    kept_a = tmp_path / "fathom_20260921_035503.db.gz"
    kept_b = tmp_path / "fathom_20260921_140000.db.gz"  # manual same-day re-run
    old_a = tmp_path / "fathom_20260901_035503.db.gz"
    old_b = tmp_path / "fathom_20260901_140000.db.gz"
    for f in (kept_a, kept_b, old_a, old_b):
        f.write_bytes(b"fake")

    deleted = backup_db.select_backups_to_prune([kept_a, kept_b, old_a, old_b], "fathom", 1, 0)

    assert sorted(deleted) == sorted([old_a, old_b])


def test_files_the_rule_does_not_understand_are_never_pruned(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    odd = [
        tmp_path / "fathom_before_migration.db.gz",  # hand-made
        tmp_path / "fathom_20269999_035503.db.gz",  # impossible date
        tmp_path / "other_20200101_000000.db.gz",  # a different DB's backup
        tmp_path / "fathom_20260101_000000.db.gz.bak",
    ]
    for f in odd:
        f.write_bytes(b"fake")

    assert backup_db.select_backups_to_prune(odd, "fathom", 0, 0) == []


def test_create_backup_prunes_per_the_tiered_rule(tmp_path):
    db_path = _make_db(tmp_path / "fathom.db", "x")
    backup_dir = tmp_path / "backups"
    old = _touch_backups(backup_dir, ["20200101", "20200102", "20200103"])

    result = backup_db.create_backup(db_path=db_path, backup_dir=backup_dir, keep_daily=2, keep_weekly=0)

    # New backup (today) + the newest old one survive; the other two are pruned.
    assert result.exists()
    assert not old[0].exists() and not old[1].exists()
    assert old[2].exists()
