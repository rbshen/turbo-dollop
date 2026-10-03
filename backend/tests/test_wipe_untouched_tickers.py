"""pipeline/wipe_untouched_tickers.py and data/tracked_universe.py::classify_wipe_candidates. Everything runs on temp
databases (in-memory or tmp_path files); --apply is only ever exercised against those, and the live database is
never opened (the session-wide write guard in conftest.py would fail the run if it were)."""

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import event, text
from sqlmodel import Session, select

import core.db as db
import data.tracked_universe as tu
import pipeline.wipe_untouched_tickers as wipe
from core.models import FundamentalsCache, TickerScore, TickerView, Watchlist, WatchlistTicker
from data.ticker_data_registry import WIPE_TABLES
from wipe_seed import NOW, add_protection, count_wipe_rows, make_engine, seed_wipe_tables


def _decisions(engine, **kwargs):
    with Session(engine) as session:
        return tu.classify_wipe_candidates(session, NOW, **kwargs)


def _decision(engine, ticker, **kwargs):
    return _decisions(engine, **kwargs)[ticker]


# --- every protection blocks a wipe on its own ------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, reason",
    [
        ("index:sp500", "index"),
        ("index:nasdaq", "index"),
        ("index:dow", "index"),
        ("index:russell2000", "index"),  # an index the universe rule does not know: still protects
        ("watchlist", "watchlist"),
        ("moat", "manual:tickermoat"),
        ("custom_valuation", "manual:tickercustomvaluation"),
        ("bank_capital", "manual:tickerbankcapitalmetrics"),
        ("growth_note", "manual:growthcatalystnote"),
        ("rs_benchmark", "rs_benchmark"),
    ],
)
def test_each_protection_alone_blocks_the_wipe(kind, reason):
    engine = make_engine()
    seed_wipe_tables(engine, "PROT", view_days_ago=90)
    seed_wipe_tables(engine, "CTRL", view_days_ago=90)  # same state, no protection: the control
    add_protection(engine, kind, "PROT")
    decisions = _decisions(engine)
    assert decisions["PROT"].decision == tu.DECISION_PROTECTED
    assert decisions["PROT"].protections == (reason,)
    assert decisions["CTRL"].decision == tu.DECISION_WIPE


def test_a_seed_etf_is_protected():
    engine = make_engine()
    seed_wipe_tables(engine, "XLK", view_days_ago=90)
    d = _decision(engine, "XLK")
    assert d.decision == tu.DECISION_PROTECTED and "seed" in d.protections


def test_the_benchmark_constant_protects_even_if_it_left_the_seed_list(monkeypatch):
    monkeypatch.setattr(tu, "ETF_SEED_TICKERS", frozenset())
    engine = make_engine()
    seed_wipe_tables(engine, tu.WEINSTEIN_BENCHMARK_TICKER, view_days_ago=90)
    d = _decision(engine, tu.WEINSTEIN_BENCHMARK_TICKER)
    assert d.decision == tu.DECISION_PROTECTED and d.protections == ("benchmark",)


def test_the_live_rs_benchmark_setting_is_read_without_seeding_it():
    engine = make_engine()
    seed_wipe_tables(engine, "QQQ", view_days_ago=90)
    assert _decision(engine, "QQQ").decision == tu.DECISION_WIPE  # no settings row yet, and reading it adds none
    with Session(engine) as session:
        assert session.exec(text("SELECT COUNT(*) FROM weinsteinsettings")).one()[0] == 0
    add_protection(engine, "rs_benchmark", "QQQ")  # the owner switched the benchmark to QQQ
    assert _decision(engine, "QQQ").protections == ("rs_benchmark",)


def test_an_added_ticker_is_protected_and_the_default_added_set_is_empty():
    engine = make_engine()
    seed_wipe_tables(engine, "ADDED", view_days_ago=400)
    assert _decision(engine, "ADDED").decision == tu.DECISION_WIPE
    d = _decision(engine, "ADDED", added={"ADDED"})
    assert d.decision == tu.DECISION_PROTECTED and d.protections == (tu.PROTECTION_ADDED,)


def test_protections_are_all_reported_when_several_apply():
    engine = make_engine()
    seed_wipe_tables(engine, "MANY", view_days_ago=90)
    add_protection(engine, "index:sp500", "MANY")
    add_protection(engine, "watchlist", "MANY")
    assert _decision(engine, "MANY", added={"MANY"}).protections == ("index", "watchlist", "added")


# --- delisted, boundary, adoption, ignoring ---------------------------------------------------------------------


def test_delisted_plus_a_watchlist_is_protected_but_delisted_unprotected_is_a_candidate():
    engine = make_engine()
    seed_wipe_tables(engine, "DLWL", view_days_ago=90)
    seed_wipe_tables(engine, "DLBARE", view_days_ago=90)
    add_protection(engine, "watchlist", "DLWL")
    with Session(engine) as session:
        for ticker in ("DLWL", "DLBARE"):
            row = session.get(TickerScore, ticker)
            row.delisted_at = NOW - timedelta(days=5)
            session.add(row)
        session.commit()
        # _classify answers "delisted" first for both: the wipe must not read it from there
        assert tu.classify_known_tickers(session, NOW)["DLWL"] == tu.DELISTED
    d = _decisions(engine)
    assert d["DLWL"].decision == tu.DECISION_PROTECTED and d["DLWL"].delisted
    assert d["DLBARE"].decision == tu.DECISION_WIPE and d["DLBARE"].delisted


def test_delisted_but_recently_touched_is_not_due():
    engine = make_engine()
    seed_wipe_tables(engine, "DLNEW", view_days_ago=3)
    with Session(engine) as session:
        row = session.get(TickerScore, "DLNEW")
        row.delisted_at = NOW
        session.add(row)
        session.commit()
    assert _decision(engine, "DLNEW").decision == tu.DECISION_NOT_DUE


def test_exact_thirty_day_boundary():
    engine = make_engine()
    seed_wipe_tables(engine, "EXACT", view_days_ago=30)
    seed_wipe_tables(engine, "JUSTOVER", view_days_ago=30)
    seed_wipe_tables(engine, "JUSTUNDER", view_days_ago=30)
    with Session(engine) as session:
        for ticker, delta in (("JUSTOVER", timedelta(seconds=-1)), ("JUSTUNDER", timedelta(seconds=1))):
            row = session.get(TickerView, ticker)
            row.last_viewed_at = row.last_viewed_at + delta
            session.add(row)
        session.commit()
    d = _decisions(engine)
    assert d["EXACT"].decision == tu.DECISION_NOT_DUE  # idle exactly 30 days is not "more than"
    assert d["JUSTOVER"].decision == tu.DECISION_WIPE
    assert d["JUSTUNDER"].decision == tu.DECISION_NOT_DUE
    assert d["EXACT"].days_idle == 30.0


def test_an_orphan_with_data_and_no_tickerview_is_adopted_not_wiped():
    engine = make_engine()
    seed_wipe_tables(engine, "ORPHAN", view_days_ago=None)
    d = _decision(engine, "ORPHAN")
    assert d.decision == tu.DECISION_ADOPT and d.last_viewed_at is None and d.days_idle is None and d.has_data


def test_a_protected_ticker_without_a_tickerview_is_protected_not_adopted():
    engine = make_engine()
    seed_wipe_tables(engine, "IDX", view_days_ago=None)
    add_protection(engine, "index:sp500", "IDX")
    assert _decision(engine, "IDX").decision == tu.DECISION_PROTECTED


def test_a_ticker_with_no_data_and_no_tickerview_is_ignored():
    engine = make_engine()
    seed_wipe_tables(engine, "REAL", view_days_ago=90)
    assert set(_decisions(engine)) == {"REAL"}  # the sweep never lists it
    d = _decision(engine, "GHOST", tickers=["ghost"])  # asking for it by name: ignored, not adopted
    assert d.decision == tu.DECISION_IGNORED and not d.has_data


def test_forex_rate_rows_are_not_ticker_data():
    engine = make_engine()
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="EURUSD", statement_type="forex_rate", period="latest", fetched_at=NOW, raw_json="{}"))
        session.commit()
    assert _decisions(engine) == {}  # not adopted, not a candidate


def test_a_tickerview_only_ticker_idle_past_the_cutoff_is_a_wipe():
    engine = make_engine()
    with Session(engine) as session:
        session.add(TickerView(ticker="VIEWONLY", last_viewed_at=NOW - timedelta(days=45)))
        session.commit()
    d = _decision(engine, "VIEWONLY")
    assert d.decision == tu.DECISION_WIPE and not d.has_data


def test_the_classification_is_untouched_a_stamped_view_still_reads_viewed():
    """Adoption stamps a TickerView row; with no added state that reads as `viewed` today (docs: step 2 flips it)."""
    engine = make_engine()
    seed_wipe_tables(engine, "ADOPTEE", view_days_ago=0)
    with Session(engine) as session:
        assert tu.classify_known_tickers(session, NOW)["ADOPTEE"] == tu.VIEWED


# --- apply -------------------------------------------------------------------------------------------------------


def _run(engine, **kwargs):
    kwargs.setdefault("added", ())
    return wipe.run(engine, apply=True, now=NOW, **kwargs)


def test_apply_deletes_every_wipe_table_for_the_candidate_and_nothing_else(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "GONE", view_days_ago=45)
    seed_wipe_tables(engine, "KEPT", view_days_ago=45)
    add_protection(engine, "moat", "KEPT")
    seed_wipe_tables(engine, "FRESH", view_days_ago=2)
    with Session(engine) as session:  # a forex row, and one keyed to the candidate itself
        session.add(FundamentalsCache(ticker="EURUSD", statement_type="forex_rate", period="latest", fetched_at=NOW, raw_json="{}"))
        session.add(FundamentalsCache(ticker="GONE", statement_type="forex_rate", period="latest", fetched_at=NOW, raw_json="{}"))
        session.commit()
    before = {t: count_wipe_rows(engine, t) for t in ("KEPT", "FRESH")}
    assert {t: n for t, n in count_wipe_rows(engine, "GONE").items() if t != "fundamentalscache"} == {e.name: 1 for e in WIPE_TABLES if e.name != "fundamentalscache"}
    assert count_wipe_rows(engine, "GONE")["fundamentalscache"] == 2  # the profile row and the forex_rate row

    summary = _run(engine)

    assert [o.ticker for o in summary.outcomes if o.outcome == wipe.WIPED] == ["GONE"]
    after = count_wipe_rows(engine, "GONE")
    assert {t: n for t, n in after.items() if n} == {"fundamentalscache": 1}  # only the forex_rate row survives
    with Session(engine) as session:
        survivor = session.exec(select(FundamentalsCache).where(FundamentalsCache.ticker == "GONE")).one()
        assert survivor.statement_type == "forex_rate"
        assert session.exec(select(FundamentalsCache).where(FundamentalsCache.ticker == "EURUSD")).one()
    assert {t: count_wipe_rows(engine, t) for t in ("KEPT", "FRESH")} == before
    assert summary.rows_by_table["tickerview"] == 1 and sum(summary.rows_by_table.values()) == len(WIPE_TABLES)  # the forex row is not counted
    with Session(engine) as session:
        assert session.exec(text("SELECT COUNT(*) FROM tickermoat")).one()[0] == 1


def test_apply_deletes_in_registry_order_with_tickerview_last(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "ORDER", view_days_ago=45)
    deletes = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("DELETE"):
            deletes.append(statement.split('"')[1])

    _run(engine)
    assert deletes == [e.name for e in WIPE_TABLES]
    assert deletes[-1] == "tickerview"


def test_a_crash_mid_wipe_rolls_back_and_the_ticker_stays_a_candidate(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "CRASH", view_days_ago=45)
    calls = []
    real = wipe._delete_rows

    def flaky(conn, entry, ticker):
        calls.append(entry.name)
        if len(calls) == 5:
            raise RuntimeError("disk gone")
        return real(conn, entry, ticker)

    monkeypatch.setattr(wipe, "_delete_rows", flaky)
    summary = _run(engine)
    assert summary.outcomes[0].outcome == wipe.FAILED and "disk gone" in summary.outcomes[0].detail
    assert all(n == 1 for n in count_wipe_rows(engine, "CRASH").values())  # one transaction: all or nothing
    assert _decision(engine, "CRASH").decision == tu.DECISION_WIPE

    monkeypatch.setattr(wipe, "_delete_rows", real)
    assert _run(engine).count(wipe.WIPED) == 1


def test_a_half_committed_wipe_leaves_tickerview_so_the_ticker_is_still_a_candidate(tmp_path):
    """The invariant behind the deletion order, without relying on the transaction: derived tables and caches gone,
    TickerView still there -> the next run finishes the job."""
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "HALF", view_days_ago=45)
    with engine.begin() as conn:
        for entry in WIPE_TABLES[:-1]:
            wipe._delete_rows(conn, entry, "HALF")
    counts = count_wipe_rows(engine, "HALF")
    assert {t: n for t, n in counts.items() if n} == {"tickerview": 1}
    assert _decision(engine, "HALF").decision == tu.DECISION_WIPE
    assert _run(engine).count(wipe.WIPED) == 1
    assert not any(count_wipe_rows(engine, "HALF").values())


def test_a_ticker_touched_in_between_is_skipped_by_the_in_transaction_recheck(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "TOUCHED", view_days_ago=45)
    with Session(engine) as session:
        view = session.get(TickerView, "TOUCHED")
        view.last_viewed_at = NOW  # the user opened the page after the pass decided
        session.add(view)
        session.commit()
    outcome, fresh, rows = wipe.apply_one(engine, "TOUCHED", NOW, (), {e.name for e in WIPE_TABLES})
    assert outcome == wipe.SKIPPED and fresh.decision == tu.DECISION_NOT_DUE and rows == {}
    assert all(n == 1 for n in count_wipe_rows(engine, "TOUCHED").values())


def test_a_ticker_protected_in_between_is_skipped_through_run(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "LATE", view_days_ago=45)
    real = wipe.apply_one

    def watch_then_apply(*args, **kwargs):
        add_protection(engine, "watchlist", "LATE")  # added to a watchlist after the up-front pass
        return real(*args, **kwargs)

    monkeypatch.setattr(wipe, "apply_one", watch_then_apply)
    summary = _run(engine)
    o = summary.outcomes[0]
    assert o.outcome == wipe.SKIPPED and "watchlist" in o.detail
    assert all(n == 1 for n in count_wipe_rows(engine, "LATE").values())


def test_apply_adopts_an_orphan_and_it_becomes_eligible_thirty_days_later(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "DXC", view_days_ago=None)
    summary = _run(engine)
    assert summary.count(wipe.ADOPTED) == 1 and summary.count(wipe.WIPED) == 0
    assert all(n == 1 for k, n in count_wipe_rows(engine, "DXC").items() if k != "tickerview")  # data untouched
    with Session(engine) as session:
        assert session.get(TickerView, "DXC").last_viewed_at == NOW
        assert tu.classify_wipe_candidates(session, NOW + timedelta(days=30))["DXC"].decision == tu.DECISION_NOT_DUE
        assert tu.classify_wipe_candidates(session, NOW + timedelta(days=30, seconds=1))["DXC"].decision == tu.DECISION_WIPE


def test_limit_takes_wipes_oldest_first_then_adoptions(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "OLD90", view_days_ago=90)
    seed_wipe_tables(engine, "OLD60", view_days_ago=60)
    seed_wipe_tables(engine, "OLD40", view_days_ago=40)
    seed_wipe_tables(engine, "ORPH", view_days_ago=None)
    summary = _run(engine, limit=2)
    assert sorted(o.ticker for o in summary.outcomes if o.outcome == wipe.WIPED) == ["OLD60", "OLD90"]
    assert summary.count(wipe.ADOPTED) == 0
    left = {o.ticker: o.detail for o in summary.outcomes if o.decision in (tu.DECISION_WIPE, tu.DECISION_ADOPT) and o.outcome == wipe.NOT_ACTED}
    assert left == {"OLD40": "beyond --limit", "ORPH": "beyond --limit"}
    assert any(count_wipe_rows(engine, "OLD40").values())


def test_tickers_restricts_the_pass_and_normalizes(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "AAA", view_days_ago=90)
    seed_wipe_tables(engine, "BBB", view_days_ago=90)
    summary = _run(engine, tickers=["aaa"])
    assert [o.ticker for o in summary.outcomes] == ["AAA"] and summary.count(wipe.WIPED) == 1
    assert any(count_wipe_rows(engine, "BBB").values())


def test_apply_refuses_when_a_ticker_table_is_unclassified(tmp_path):
    engine = make_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE surprise (ticker VARCHAR)"))
    seed_wipe_tables(engine, "SAFE", view_days_ago=90)
    with pytest.raises(RuntimeError, match="surprise.ticker"):
        _run(engine)
    assert any(count_wipe_rows(engine, "SAFE").values())
    assert wipe.run(engine, apply=False, now=NOW, added=()).unclassified_tables == ["surprise.ticker"]  # a dry run only warns


# --- dry run is write-free --------------------------------------------------------------------------------------

_NON_READ = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE", "VACUUM", "REINDEX")


def test_dry_run_executes_no_write_statement_and_changes_nothing(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "WIPEME", view_days_ago=90)
    seed_wipe_tables(engine, "ORPHAN", view_days_ago=None)  # would be adopted: must NOT be stamped
    seed_wipe_tables(engine, "KEEPME", view_days_ago=1)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    summary = wipe.run(engine, apply=False, now=NOW, added=())
    assert statements and not [s for s in statements if s.startswith(_NON_READ)]
    assert summary.dry_run and summary.count(wipe.WIPED) == 1 and summary.count(wipe.ADOPTED) == 1
    assert summary.rows_by_table["sharedbarscache"] == 1 and summary.rows_by_table["tickerview"] == 1
    assert all(n == 1 for n in count_wipe_rows(engine, "WIPEME").values())
    with Session(engine) as session:
        assert session.get(TickerView, "ORPHAN") is None


def test_dry_run_through_the_cli_uses_a_read_only_connection_and_leaves_the_file_byte_identical(tmp_path, monkeypatch, capsys):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "WIPEME", view_days_ago=90)
    seed_wipe_tables(engine, "ORPHAN", view_days_ago=None)
    engine.dispose()
    path = tmp_path / "wipe.db"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(wipe, "configure_logging", lambda *_: pytest.fail("a dry run must not create a log file"))

    summary = wipe.main([])

    assert summary.dry_run and summary.count(wipe.WIPED) == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert not list(tmp_path.glob("*-journal"))
    with pytest.raises(Exception, match="readonly"):  # the connection itself cannot write
        with wipe.read_only_engine(path).begin() as conn:
            conn.execute(text("DELETE FROM tickerview"))


# --- the lock ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "2"])
def test_apply_is_locked_unless_the_variable_is_exactly_one(value):
    environ = {} if value is None else {wipe.ALLOW_APPLY_ENV: value}
    with pytest.raises(wipe.ApplyLockedError, match=wipe.ALLOW_APPLY_ENV):
        wipe.check_apply_allowed(environ)
    wipe.check_apply_allowed({wipe.ALLOW_APPLY_ENV: "1"})


def test_cli_apply_without_the_variable_refuses_before_opening_anything(monkeypatch):
    monkeypatch.delenv(wipe.ALLOW_APPLY_ENV, raising=False)
    monkeypatch.setattr(wipe, "configure_logging", lambda *_: pytest.fail("the lock must trip before logging is set up"))
    monkeypatch.setattr(wipe, "run", lambda *a, **k: pytest.fail("the lock must trip before any run"))
    with pytest.raises(wipe.ApplyLockedError):
        wipe.main(["--apply"])


def test_cli_apply_with_the_variable_runs_on_the_patched_temp_engine_only(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "WIPEME", view_days_ago=90)
    monkeypatch.setenv(wipe.ALLOW_APPLY_ENV, "1")
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(wipe, "configure_logging", lambda *_: None)
    summary = wipe.main(["--apply", "--tickers", "WIPEME"])
    assert not summary.dry_run and summary.count(wipe.WIPED) == 1
    assert not any(count_wipe_rows(engine, "WIPEME").values())


def test_dry_run_and_apply_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        wipe._parse_args(["--dry-run", "--apply"])


def test_the_job_is_not_registered_anywhere():
    from pathlib import Path

    from core.cron_health import CRON_JOB_NAMES

    backend = Path(wipe.__file__).resolve().parent.parent
    assert not any("wipe" in name for name in CRON_JOB_NAMES)
    assert "wipe_untouched" not in (backend / "crontab.txt").read_text()
    assert "cron_heartbeat(" not in Path(wipe.__file__).read_text().split('"""', 2)[2]


# --- the real added loader (opt-in universe step 2) -----------------------------------------------------------------------


def test_run_reads_the_real_added_set_from_tickerview(tmp_path):
    engine = make_engine(tmp_path)
    seed_wipe_tables(engine, "ADDED", view_days_ago=90)
    seed_wipe_tables(engine, "PLAIN", view_days_ago=90)
    with Session(engine) as session:
        row = session.get(TickerView, "ADDED")
        row.added_at, row.added_source = NOW - timedelta(days=80), "grandfathered"
        session.add(row)
        session.commit()
        assert tu.load_added_tickers(session) == {"ADDED"}
    dry = wipe.run(engine, apply=False, now=NOW)  # added=None: the real loader
    by = {o.ticker: o for o in dry.outcomes}
    assert by["ADDED"].decision == tu.DECISION_PROTECTED and by["ADDED"].protections == (tu.PROTECTION_ADDED,)
    assert by["PLAIN"].decision == tu.DECISION_WIPE
    applied = wipe.run(engine, apply=True, now=NOW)
    assert [o.ticker for o in applied.outcomes if o.outcome == wipe.WIPED] == ["PLAIN"]
    assert all(n == 1 for n in count_wipe_rows(engine, "ADDED").values())


def test_the_placeholder_loader_is_gone():
    assert wipe.load_added_tickers is tu.load_added_tickers
