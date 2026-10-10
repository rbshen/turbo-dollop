"""The data-quality flag store and its callers: upsert/clear logic (data/data_quality_data.py), the endpoints, the nightly job and its
cron wiring. Fresh in-memory engine throughout (CLAUDE.md, "Ad-hoc reproduction scripts"). The checks themselves are tested in
scoring/test_data_quality.py; here they run over cached rows shaped like the known cases (MU, WTW, an SBC gap)."""

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import pipeline.nightly_data_quality as job
from core.cron_health import CRON_JOB_NAMES, JOB_METADATA, CronRunContext
from core.models import DataQualityFlag, FundamentalsCache, TickerView, Watchlist, WatchlistTicker
from data import data_quality_data as dq_data
from data.data_quality_data import SyncResult, flags_for_ticker, list_flags, mark_reviewed, sync_flags, ticker_note_flags

M = 1_000_000
T0 = datetime(2026, 10, 10, 3, 26)
T1 = T0 + timedelta(days=1)


@pytest.fixture
def engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(job, "engine", engine)
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "nightly_data_quality.log")
    return engine


@pytest.fixture
def client(engine):
    return TestClient(main.app)


def cache(session, ticker, statement_type, period, rows):
    session.add(FundamentalsCache(ticker=ticker, statement_type=statement_type, period=period, fetched_at=datetime.now(), raw_json=json.dumps(rows)))


def cf_row(date, cfo, capex, sbc=100 * M, ni=0.0):
    return {"date": date, "fiscalYear": date[:4], "netCashProvidedByOperatingActivities": cfo, "capitalExpenditure": capex,
            "stockBasedCompensation": sbc, "netIncome": ni}


def inc_row(date, ni=500 * M, revenue=10_000 * M):
    return {"date": date, "fiscalYear": date[:4], "revenue": revenue, "netIncome": ni}


def add_ticker(session, ticker, capex_newest=0.0, sbc=(100, 100, 100, 100), ni_cash=500 * M, watched=False):
    """Annual rows 2026 (newest) back to 2023: capex 0 in the newest year (the MU shape), quarters carrying capex."""
    session.add(TickerView(ticker=ticker, last_viewed_at=T0, added_at=datetime(2026, 10, 1)))
    dates = ["2026-09-03", "2025-08-28", "2024-08-29", "2023-08-31"]
    capex = [capex_newest, -900 * M, -800 * M, -700 * M]
    annual = [cf_row(d, 5000 * M, c, sbc=s * M, ni=ni_cash if i == 0 else 500 * M) for i, (d, c, s) in enumerate(zip(dates, capex, sbc))]
    quarterly = [cf_row("2026-09-03", 1000 * M, -200 * M), cf_row("2026-05-28", 1000 * M, -200 * M)]
    cache(session, ticker, "cash_flow_statement", "annual", annual)
    cache(session, ticker, "cash_flow_statement", "quarterly", quarterly)
    cache(session, ticker, "income_statement", "annual", [inc_row(d) for d in dates])
    cache(session, ticker, "income_statement", "quarterly", [inc_row("2026-09-03"), inc_row("2026-05-28")])
    cache(session, ticker, "profile", "latest", [{"sector": "Technology", "industry": "Semiconductors"}])
    if watched:
        watch(session, ticker)


def watch(session, ticker):
    wl = session.exec(select(Watchlist)).first()
    if wl is None:
        wl = Watchlist(name="Mine", created_at=T0, updated_at=T0)
        session.add(wl)
        session.commit()
        session.refresh(wl)
    session.add(WatchlistTicker(watchlist_id=wl.id, ticker=ticker, added_at=T0))


def all_flags(engine):
    with Session(engine) as session:
        return {(f.ticker, f.check, f.fiscal_year): f for f in session.exec(select(DataQualityFlag)).all()}


# --- sync ------------------------------------------------------------------------------------------------------------------------


def test_sync_adds_the_flags_that_hold_and_reports_the_counts(engine):
    with Session(engine) as session:
        add_ticker(session, "MU")
        add_ticker(session, "OK", capex_newest=-950 * M)  # a healthy ticker: no flag
        session.commit()
        result = sync_flags(session, T0)
    assert (result.universe, result.scanned, result.no_data, result.errors) == (2, 2, 0, 0)
    assert (result.added, result.kept, result.cleared) == (1, 0, 0)
    flags = all_flags(engine)
    assert set(flags) == {("MU", "zero_newest_capex", "2026")}
    f = flags[("MU", "zero_newest_capex", "2026")]
    assert (f.field, f.kind, f.fmp_value, f.found_at, f.last_seen_at, f.reviewed_at) == ("capitalExpenditure", "zero_line", 0.0, T0, T0, None)
    assert "FY2026 capex is 0" in f.detail


def test_second_run_is_idempotent_and_only_moves_last_seen(engine):
    with Session(engine) as session:
        add_ticker(session, "MU")
        session.commit()
        sync_flags(session, T0)
        first = all_flags(engine)[("MU", "zero_newest_capex", "2026")]
        before = (first.id, first.found_at, first.detail)
        result = sync_flags(session, T1)
    again = all_flags(engine)[("MU", "zero_newest_capex", "2026")]
    assert (result.added, result.kept, result.cleared) == (0, 1, 0)
    assert (again.id, again.found_at, again.detail) == before
    assert again.last_seen_at == T1
    assert len(all_flags(engine)) == 1


def test_a_healed_row_clears_its_flag_and_a_later_return_is_a_new_row(engine):
    with Session(engine) as session:
        add_ticker(session, "MU")
        session.commit()
        sync_flags(session, T0)
        first_id = all_flags(engine)[("MU", "zero_newest_capex", "2026")].id
        row = session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "cash_flow_statement", FundamentalsCache.period == "annual")).one()
        rows = json.loads(row.raw_json)
        healed = [dict(rows[0], capitalExpenditure=-950 * M)] + rows[1:]
        row.raw_json = json.dumps(healed)
        session.add(row)
        session.commit()
        cleared = sync_flags(session, T1)
        assert (cleared.added, cleared.kept, cleared.cleared) == (0, 0, 1)
        assert all_flags(engine) == {}
        row.raw_json = json.dumps(rows)  # FMP serves the bad row again
        session.add(row)
        session.commit()
        sync_flags(session, T1 + timedelta(days=1))
    back = all_flags(engine)[("MU", "zero_newest_capex", "2026")]
    assert back.id != first_id or back.found_at == T1 + timedelta(days=1)
    assert back.found_at == T1 + timedelta(days=1) and back.reviewed_at is None


def test_review_survives_later_runs_and_a_changed_kind_reopens_the_flag(engine):
    with Session(engine) as session:
        add_ticker(session, "MU")
        session.commit()
        sync_flags(session, T0)
        flag = all_flags(engine)[("MU", "zero_newest_capex", "2026")]
        reviewed = mark_reviewed(session, flag.id, now=T0 + timedelta(hours=5))
        assert reviewed.reviewed_at == T0 + timedelta(hours=5)
        sync_flags(session, T1)
        session.expire_all()
        kept = session.exec(select(DataQualityFlag)).one()
        assert kept.reviewed_at == T0 + timedelta(hours=5) and kept.found_at == T0
        kept.kind = "something_else"  # as if the finding had been of another kind when it was reviewed
        session.add(kept)
        session.commit()
        sync_flags(session, T1 + timedelta(days=1))
    reopened = all_flags(engine)[("MU", "zero_newest_capex", "2026")]
    assert reopened.kind == "zero_line" and reopened.reviewed_at is None


def test_mark_reviewed_is_idempotent_and_none_for_a_missing_flag(engine):
    with Session(engine) as session:
        add_ticker(session, "MU")
        session.commit()
        sync_flags(session, T0)
        fid = all_flags(engine)[("MU", "zero_newest_capex", "2026")].id
        first = mark_reviewed(session, fid, now=T1)
        second = mark_reviewed(session, fid, now=T1 + timedelta(days=3))
        assert first.reviewed_at == second.reviewed_at == T1
        assert mark_reviewed(session, 9999) is None


def test_ticker_with_nothing_cached_or_a_failing_check_is_left_as_it_was(engine, monkeypatch):
    with Session(engine) as session:
        add_ticker(session, "MU")
        add_ticker(session, "BAD")
        session.commit()
        sync_flags(session, T0)
        assert ("MU", "zero_newest_capex", "2026") in all_flags(engine)
        for row in session.exec(
            select(FundamentalsCache).where(FundamentalsCache.ticker == "MU", FundamentalsCache.statement_type == "income_statement")
        ).all():
            session.delete(row)  # MU has other cached rows (still tracked) but no income statement: nothing to judge
        session.commit()
        real = dq_data.flags_for_ticker

        def boom(session_, ticker):
            if ticker == "BAD":
                raise ValueError("bad row")
            return real(session_, ticker)

        monkeypatch.setattr(dq_data, "flags_for_ticker", boom)
        result = sync_flags(session, T1)
    assert (result.scanned, result.no_data, result.errors, result.cleared) == (0, 1, 1, 0)
    assert {k[0] for k in all_flags(engine)} == {"MU", "BAD"}  # both untouched


def test_flags_of_a_ticker_that_left_the_universe_are_deleted(engine):
    with Session(engine) as session:
        add_ticker(session, "MU")
        session.commit()
        sync_flags(session, T0)
        session.delete(session.get(TickerView, "MU"))
        session.commit()
        result = sync_flags(session, T1)
    assert result.cleared == 1 and all_flags(engine) == {}


def test_flags_for_ticker_returns_none_without_annual_income_rows(engine):
    with Session(engine) as session:
        assert flags_for_ticker(session, "NOPE") is None


# --- reads -----------------------------------------------------------------------------------------------------------------------


def test_list_scopes_hide_reviewed_and_order_newest_first(engine):
    with Session(engine) as session:
        add_ticker(session, "MU", watched=True)
        add_ticker(session, "AAA", capex_newest=-950 * M, sbc=(100, 0, 100, 100))
        session.commit()
        sync_flags(session, T0)
        later = [DataQualityFlag(ticker="MU", check="sbc_gap", field="stockBasedCompensation", fiscal_year="2025", kind="zero_between",
                                 detail="x", found_at=T1, last_seen_at=T1)]
        session.add_all(later)
        session.commit()
        watched = list_flags(session, "watchlisted")
        everything = list_flags(session, "all")
        assert [f.ticker for f in watched] == ["MU", "MU"] and watched[0].found_at == T1
        assert {f.ticker for f in everything} == {"MU", "AAA"}
        mark_reviewed(session, watched[0].id)
        assert len(list_flags(session, "watchlisted")) == 1
        assert len(list_flags(session, "watchlisted", include_reviewed=True)) == 2
        assert dq_data.count_open(session) == (1, 2)


def test_ticker_note_flags_order_data_errors_before_sbc_and_definitions(engine):
    with Session(engine) as session:
        for check, kind, fy in (("net_income_disagreement", "definition", "2025"), ("sbc_gap", "zero_newest", "2025"),
                                ("zero_newest_capex", "zero_line", "2026"), ("net_income_disagreement", "sign_differs", "2024")):
            session.add(DataQualityFlag(ticker="X", check=check, field="f", fiscal_year=fy, kind=kind, detail=kind, found_at=T0, last_seen_at=T0))
        session.commit()
        assert [f.kind for f in ticker_note_flags(session, "x")] == ["zero_line", "sign_differs", "zero_newest", "definition"]


# --- endpoints -------------------------------------------------------------------------------------------------------------------


def test_endpoints_list_review_and_ticker_note(engine, client):
    with Session(engine) as session:
        add_ticker(session, "MU", watched=True)
        add_ticker(session, "AAA", capex_newest=-950 * M, sbc=(100, 0, 100, 100))
        session.commit()
        sync_flags(session, T0)
    body = client.get("/api/data-quality/flags").json()
    assert body["scope"] == "watchlisted" and body["open_watchlisted"] == 1 and body["open_all"] == 2
    assert [f["ticker"] for f in body["flags"]] == ["MU"]
    assert {f["ticker"] for f in client.get("/api/data-quality/flags?scope=all").json()["flags"]} == {"MU", "AAA"}
    assert client.get("/api/data-quality/flags?scope=bogus").status_code == 422

    flag = body["flags"][0]
    assert flag["check"] == "zero_newest_capex" and flag["fiscal_year"] == "2026" and flag["reviewed_at"] is None
    note = client.get("/api/tickers/mu/data-quality").json()
    assert [f["id"] for f in note] == [flag["id"]]

    reviewed = client.post(f"/api/data-quality/flags/{flag['id']}/review")
    assert reviewed.status_code == 200 and reviewed.json()["reviewed_at"] is not None
    assert client.post(f"/api/data-quality/flags/{flag['id']}/review").json()["reviewed_at"] == reviewed.json()["reviewed_at"]
    assert client.get("/api/tickers/MU/data-quality").json() == []
    assert client.get("/api/data-quality/flags").json()["open_watchlisted"] == 0
    assert client.post("/api/data-quality/flags/99999/review").status_code == 404


def test_endpoints_never_write_scores_or_other_tables(engine, client):
    """Informational only: reading and reviewing touch the flag table and nothing else."""
    with Session(engine) as session:
        add_ticker(session, "MU")
        session.commit()
        sync_flags(session, T0)
        before = {t: len(session.exec(select(m)).all()) for t, m in (("cache", FundamentalsCache), ("view", TickerView))}
    client.get("/api/data-quality/flags?scope=all")
    client.post(f"/api/data-quality/flags/{next(iter(all_flags(engine).values())).id}/review")
    with Session(engine) as session:
        after = {t: len(session.exec(select(m)).all()) for t, m in (("cache", FundamentalsCache), ("view", TickerView))}
    assert before == after


# --- the job ---------------------------------------------------------------------------------------------------------------------


def test_job_main_runs_the_sweep_and_record_outcome_writes_the_message(engine):
    with Session(engine) as session:
        add_ticker(session, "MU")
        session.commit()
    result = job.main()
    assert isinstance(result, SyncResult) and result.added == 1
    run = CronRunContext()
    job.record_outcome(result, run)
    assert run.message == "1 open flags (1 new, 0 cleared) over 1 tickers"


def test_record_outcome_mentions_missing_cache_and_fails_on_a_high_error_rate():
    run = CronRunContext()
    job.record_outcome(SyncResult(universe=30, scanned=29, no_data=1, errors=0, added=0, kept=4, cleared=2), run)
    assert "1 without cached statements" in run.message and "4 open flags" in run.message
    with pytest.raises(RuntimeError):
        job.record_outcome(SyncResult(universe=40, scanned=30, no_data=0, errors=10, added=0, kept=0, cleared=0), CronRunContext())
    job.record_outcome(SyncResult(universe=40, scanned=39, no_data=0, errors=1, added=0, kept=0, cleared=0), CronRunContext())  # 2.5%: fine


def test_job_is_registered_for_health_monitoring():
    assert "pipeline.nightly_data_quality" in CRON_JOB_NAMES
    assert JOB_METADATA["pipeline.nightly_data_quality"].time_label == "3:26 AM"
