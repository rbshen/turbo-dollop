"""pipeline/grandfather_universe.py: the one-time backfill that marks today's viewed-only tickers as added. Temp databases
only; the live database is never opened (the session-wide write guard in conftest.py would fail the run if it were)."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text
from sqlmodel import Session, select

import core.db as db
import data.tracked_universe as tu
import pipeline.grandfather_universe as gf
from core.models import FundamentalsCache, TickerView
from wipe_seed import NOW, add_protection, make_engine

_STOCK_PROFILE = '{"companyName": "x"}'
_ETF_PROFILE = '{"companyName": "x", "isEtf": true}'


def _known(engine, ticker, *, etf=False, viewed_days_ago=3):
    """A known ticker (cached profile) with a TickerView row."""
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW,
                raw_json=_ETF_PROFILE if etf else _STOCK_PROFILE,
            )
        )
        if viewed_days_ago is not None:
            session.add(TickerView(ticker=ticker, last_viewed_at=NOW - timedelta(days=viewed_days_ago)))
        session.commit()


def _plan(engine, now=NOW):
    with Session(engine) as session:
        return gf.plan_grandfather(session, now)


def _views(engine):
    with Session(engine) as session:
        return {v.ticker: (v.last_viewed_at, v.added_at, v.added_source) for v in session.exec(select(TickerView)).all()}


# --- selection ----------------------------------------------------------------------------------------------------


def test_selects_viewed_only_tickers_split_into_stocks_and_etfs():
    engine = make_engine()
    _known(engine, "STK1", viewed_days_ago=2)
    _known(engine, "STK2", viewed_days_ago=20)
    _known(engine, "ETF1", etf=True, viewed_days_ago=1)
    plan = _plan(engine)
    assert sorted(plan.stocks) == ["STK1", "STK2"] and sorted(plan.etfs) == ["ETF1"]
    assert plan.stocks["STK1"] == NOW - timedelta(days=2)  # last_viewed_at is carried for the printout
    assert plan.tickers == ["ETF1", "STK1", "STK2"] and not plan.already_added and not plan.refused


def test_an_expired_ticker_is_not_selected():
    engine = make_engine()
    _known(engine, "OLD", viewed_days_ago=45)
    assert _plan(engine).tickers == []


@pytest.mark.parametrize("kind", ["index:sp500", "index:dow", "index:nasdaq", "watchlist", "moat", "custom_valuation", "bank_capital", "growth_note"])
def test_a_ticker_with_a_protection_the_classification_sees_is_not_selected(kind):
    engine = make_engine()
    _known(engine, "PROT", viewed_days_ago=2)
    add_protection(engine, kind, "PROT")
    plan = _plan(engine)
    assert plan.tickers == []  # classified index/watchlist/manual, not "viewed"


@pytest.mark.parametrize("kind, reason", [("index:russell2000", "index"), ("rs_benchmark", "rs_benchmark")])
def test_a_protection_the_classification_cannot_see_is_refused_not_marked(kind, reason):
    """An index name outside the three the universe knows, or the live rs_benchmark: the reason still reads "viewed",
    so the independent raw-set re-check must refuse it."""
    engine = make_engine()
    _known(engine, "HIDDEN", viewed_days_ago=2)
    add_protection(engine, kind, "HIDDEN")
    plan = _plan(engine)
    assert plan.tickers == [] and plan.refused == {"HIDDEN": (reason,)}
    assert gf.apply_plan(engine, plan.tickers, NOW) == 0
    assert _views(engine)["HIDDEN"][1] is None


def test_seed_etfs_and_delisted_tickers_are_not_selected():
    from core.models import TickerScore

    engine = make_engine()
    _known(engine, "XLK", etf=True, viewed_days_ago=2)  # a seed: reason "system"
    _known(engine, "DEAD", viewed_days_ago=2)
    with Session(engine) as session:
        session.add(TickerScore(ticker="DEAD", computed_at=NOW, delisted_at=NOW))
        session.commit()
    assert _plan(engine).tickers == []


def test_an_already_added_ticker_is_skipped_and_never_overwritten():
    engine = make_engine()
    _known(engine, "DONE", viewed_days_ago=2)
    _known(engine, "NEW", viewed_days_ago=2)
    earlier = NOW - timedelta(days=9)
    with Session(engine) as session:
        row = session.get(TickerView, "DONE")
        row.added_at, row.added_source = earlier, "user"
        session.add(row)
        session.commit()
    plan = _plan(engine)
    assert plan.tickers == ["NEW"] and plan.already_added == ["DONE"]
    gf.run(engine, apply=True, now=NOW)
    assert _views(engine)["DONE"][1:] == (earlier, "user")


# --- apply --------------------------------------------------------------------------------------------------------


def test_apply_marks_exactly_the_selected_rows_and_nothing_else(tmp_path):
    engine = make_engine(tmp_path)
    _known(engine, "STK", viewed_days_ago=2)
    _known(engine, "ETF", etf=True, viewed_days_ago=2)
    _known(engine, "OLD", viewed_days_ago=45)  # expired: untouched
    _known(engine, "IDX", viewed_days_ago=2)
    add_protection(engine, "index:sp500", "IDX")
    before = _views(engine)

    plan = gf.run(engine, apply=True, now=NOW)

    after = _views(engine)
    assert plan.tickers == ["ETF", "STK"]
    for ticker in ("STK", "ETF"):
        last, added_at, source = after[ticker]
        assert last == before[ticker][0]  # last_viewed_at identical
        assert source == "grandfathered" and added_at is not None
        assert datetime.now(timezone.utc).replace(tzinfo=None) - added_at < timedelta(minutes=5)  # stamped at apply time, UTC
    for ticker in ("OLD", "IDX"):
        assert after[ticker] == before[ticker]
    assert set(after) == set(before)


def test_apply_is_idempotent(tmp_path):
    engine = make_engine(tmp_path)
    _known(engine, "STK", viewed_days_ago=2)
    gf.run(engine, apply=True, now=NOW)
    first = _views(engine)["STK"]
    second_plan = gf.run(engine, apply=True, now=NOW)
    assert second_plan.tickers == [] and second_plan.already_added == ["STK"]
    assert _views(engine)["STK"] == first


def test_apply_rolls_back_unless_every_selected_row_changes(tmp_path):
    engine = make_engine(tmp_path)
    _known(engine, "REAL", viewed_days_ago=2)
    with pytest.raises(RuntimeError, match="rolled back"):
        gf.apply_plan(engine, ["REAL", "NOPE"], NOW)
    assert _views(engine)["REAL"][1] is None


def test_the_classification_is_unchanged_by_grandfathering(tmp_path):
    engine = make_engine(tmp_path)
    _known(engine, "STK", viewed_days_ago=2)
    _known(engine, "ETF", etf=True, viewed_days_ago=2)
    _known(engine, "OLD", viewed_days_ago=45)
    with Session(engine) as session:
        before = (tu.classify_known_tickers(session, NOW), tu.classify_etf_tickers(session, NOW))
    gf.run(engine, apply=True, now=NOW)
    with Session(engine) as session:
        assert (tu.classify_known_tickers(session, NOW), tu.classify_etf_tickers(session, NOW)) == before
        assert tu.load_added_tickers(session) == {"STK", "ETF"}


# --- dry run is write-free ------------------------------------------------------------------------------------------

_NON_READ = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE", "VACUUM", "REINDEX")


def test_dry_run_executes_no_write_statement(tmp_path):
    engine = make_engine(tmp_path)
    _known(engine, "STK", viewed_days_ago=2)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    plan = gf.run(engine, apply=False, now=NOW)
    assert plan.tickers == ["STK"] and statements and not [s for s in statements if s.startswith(_NON_READ)]
    assert _views(engine)["STK"][1] is None


def test_cli_dry_run_is_read_only_and_leaves_the_file_byte_identical(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    _known(engine, "STK", viewed_days_ago=2)
    engine.dispose()
    path = tmp_path / "wipe.db"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(gf, "configure_logging", lambda *_: pytest.fail("a dry run must not create a log file"))
    monkeypatch.setattr(db, "init_db", lambda: pytest.fail("a dry run must not migrate"))
    assert gf.main([]).tickers == ["STK"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_cli_apply_runs_init_db_then_writes_on_the_patched_temp_engine(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    _known(engine, "STK", viewed_days_ago=2)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(gf, "configure_logging", lambda *_: None)
    assert gf.main(["--apply"]).tickers == ["STK"]
    assert _views(engine)["STK"][2] == "grandfathered"


def test_dry_run_and_apply_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        gf._parse_args(["--dry-run", "--apply"])


def test_the_script_is_not_registered_anywhere():
    from pathlib import Path

    from core.cron_health import CRON_JOB_NAMES

    backend = Path(gf.__file__).resolve().parent.parent
    assert not any("grandfather" in name for name in CRON_JOB_NAMES)
    assert "grandfather" not in (backend / "crontab.txt").read_text()
    assert "cron_heartbeat(" not in Path(gf.__file__).read_text().split('"""', 2)[2]
