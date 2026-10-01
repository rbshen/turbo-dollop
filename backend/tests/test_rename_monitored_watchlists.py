import json
from datetime import datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from core.models import SavedScreenerFilter, Watchlist, WatchlistTicker
from data.watchlists import list_monitored_tickers
from pipeline import rename_monitored_watchlists as migration


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(engine, name: str, tickers: list[str], sort_field: str = "overall_score") -> int:
    now = datetime.now()
    with Session(engine) as session:
        row = Watchlist(name=name, sort_field=sort_field, created_at=now, updated_at=now)
        session.add(row)
        session.commit()
        session.refresh(row)
        for t in tickers:
            session.add(WatchlistTicker(watchlist_id=row.id, ticker=t, added_at=now))
        session.commit()
        return row.id


def _names(engine) -> dict[int, str]:
    with Session(engine) as session:
        return {w.id: w.name for w in session.exec(select(Watchlist)).all()}


def _no_full_backup() -> None:
    raise AssertionError("full backup must not run")


def test_renames_w1_to_w5_keeping_ids_tickers_sort_and_saved_filter_links(tmp_path):
    engine = _fresh_engine()
    ids = {f"W{n}": _seed(engine, f"W{n}", [f"T{n}A", f"T{n}B"], sort_field=f"sort{n}") for n in range(1, 6)}
    other = _seed(engine, "W score passed", ["ZZZ"])
    sixth = _seed(engine, "W6", ["YYY"])
    now = datetime.now()
    with Session(engine) as session:
        session.add(
            SavedScreenerFilter(
                name="Scoped", universe="all", sort_field="overall_score", sort_direction="desc",
                filters_json="{}", watchlist_id=ids["W3"], created_at=now, updated_at=now,
            )
        )
        session.commit()

    full_calls = []
    with Session(engine) as session:
        plan = migration.run_rename(session, tmp_path, lambda: full_calls.append(1) or tmp_path / "full.db.gz")

    assert [(old, new) for _, old, new in plan] == [(f"W{n}", f"E{n}") for n in range(1, 6)]
    assert full_calls == [1]
    names = _names(engine)
    assert {names[ids[f"W{n}"]] for n in range(1, 6)} == {f"E{n}" for n in range(1, 6)}
    assert names[other] == "W score passed" and names[sixth] == "W6"
    with Session(engine) as session:
        for n in range(1, 6):
            row = session.get(Watchlist, ids[f"W{n}"])
            assert row.sort_field == f"sort{n}"
            tickers = {t.ticker for t in session.exec(select(WatchlistTicker).where(WatchlistTicker.watchlist_id == row.id)).all()}
            assert tickers == {f"T{n}A", f"T{n}B"}
        assert session.exec(select(SavedScreenerFilter)).one().watchlist_id == ids["W3"]
        tickers, matched = list_monitored_tickers(session)
    assert matched == ["E1", "E2", "E3", "E4", "E5"]  # now monitored; W6 / "W score passed" are not
    assert "ZZZ" not in tickers and "YYY" not in tickers


def test_second_run_is_a_noop_that_writes_no_backup(tmp_path):
    engine = _fresh_engine()
    _seed(engine, "W1", ["AAPL"])
    with Session(engine) as session:
        migration.run_rename(session, tmp_path, None)
    backups_after_first = sorted(tmp_path.glob("watchlist_rename_*.json"))
    before = _names(engine)

    with Session(engine) as session:
        plan = migration.run_rename(session, tmp_path, _no_full_backup)

    assert plan == []
    assert _names(engine) == before
    assert sorted(tmp_path.glob("watchlist_rename_*.json")) == backups_after_first


def test_a_partially_migrated_db_finishes_the_rest(tmp_path):
    engine = _fresh_engine()
    _seed(engine, "E1", ["AAPL"])
    w2 = _seed(engine, "W2", ["MSFT"])

    with Session(engine) as session:
        plan = migration.run_rename(session, tmp_path, None)

    assert [(old, new) for _, old, new in plan] == [("W2", "E2")]
    assert _names(engine)[w2] == "E2"


def test_collision_aborts_and_writes_nothing(tmp_path):
    engine = _fresh_engine()
    _seed(engine, "W1", ["AAPL"])
    _seed(engine, "E1", ["MSFT"])  # target already taken
    _seed(engine, "W2", ["GOOG"])
    before = _names(engine)

    with Session(engine) as session, pytest.raises(migration.MigrationAbort, match="W1 -> E1"):
        migration.run_rename(session, tmp_path, _no_full_backup)

    assert _names(engine) == before
    assert list(tmp_path.glob("*.json")) == []


def test_dry_run_changes_and_writes_nothing(tmp_path):
    engine = _fresh_engine()
    _seed(engine, "W1", ["AAPL"])
    before = _names(engine)

    with Session(engine) as session:
        plan = migration.run_rename(session, tmp_path, _no_full_backup, dry_run=True)

    assert [(old, new) for _, old, new in plan] == [("W1", "E1")]
    assert _names(engine) == before
    assert list(tmp_path.glob("*.json")) == []


def test_a_failing_full_backup_stops_before_any_rename(tmp_path):
    engine = _fresh_engine()
    _seed(engine, "W1", ["AAPL"])
    before = _names(engine)

    def refuse():
        raise migration.InsufficientDiskSpaceError("not enough disk")

    with Session(engine) as session, pytest.raises(migration.InsufficientDiskSpaceError):
        migration.run_rename(session, tmp_path, refuse)

    assert _names(engine) == before


def test_logical_backup_round_trips_the_three_tables_and_the_plan(tmp_path):
    engine = _fresh_engine()
    w1 = _seed(engine, "W1", ["AAPL", "MSFT"])
    _seed(engine, "Other", ["GOOG"])

    with Session(engine) as session:
        migration.run_rename(session, tmp_path, None)

    (backup,) = tmp_path.glob("watchlist_rename_*.json")
    payload = json.loads(backup.read_text())
    assert payload["renamed"] == [{"id": w1, "old": "W1", "new": "E1"}]
    assert payload["row_counts"] == {"watchlist": 2, "watchlistticker": 3, "savedscreenerfilter": 0}
    assert {w["name"] for w in payload["watchlist"]} == {"W1", "Other"}  # the pre-rename state
    assert len(payload["watchlistticker"]) == 3


def test_rollback_restores_names_by_id_and_is_idempotent(tmp_path):
    engine = _fresh_engine()
    ids = {f"W{n}": _seed(engine, f"W{n}", [f"T{n}"]) for n in (1, 2)}
    with Session(engine) as session:
        migration.run_rename(session, tmp_path, None)
    (backup,) = tmp_path.glob("watchlist_rename_*.json")

    with Session(engine) as session:
        applied = migration.run_rollback(session, backup)
    assert sorted((old, new) for _, old, new in applied) == [("E1", "W1"), ("E2", "W2")]
    assert _names(engine) == {ids["W1"]: "W1", ids["W2"]: "W2"}

    with Session(engine) as session:
        assert migration.run_rollback(session, backup) == []  # nothing left to undo


def test_rollback_skips_a_list_the_user_renamed_again_and_never_touches_an_unrelated_e_list(tmp_path):
    engine = _fresh_engine()
    w1 = _seed(engine, "W1", ["AAPL"])
    w2 = _seed(engine, "W2", ["MSFT"])
    with Session(engine) as session:
        migration.run_rename(session, tmp_path, None)
    (backup,) = tmp_path.glob("watchlist_rename_*.json")
    new_e7 = _seed(engine, "E7", ["QQQ"])  # created later by the user
    with Session(engine) as session:
        session.get(Watchlist, w2).name = "My tech list"
        session.commit()

    with Session(engine) as session:
        applied = migration.run_rollback(session, backup)

    assert [(i, old, new) for i, old, new in applied] == [(w1, "E1", "W1")]
    names = _names(engine)
    assert names[w1] == "W1" and names[w2] == "My tech list" and names[new_e7] == "E7"


def test_rollback_aborts_if_the_old_name_is_taken(tmp_path):
    engine = _fresh_engine()
    _seed(engine, "W1", ["AAPL"])
    with Session(engine) as session:
        migration.run_rename(session, tmp_path, None)
    (backup,) = tmp_path.glob("watchlist_rename_*.json")
    _seed(engine, "W1", ["MSFT"])  # someone re-created W1 meanwhile
    before = _names(engine)

    with Session(engine) as session, pytest.raises(migration.MigrationAbort):
        migration.run_rollback(session, backup)

    assert _names(engine) == before
