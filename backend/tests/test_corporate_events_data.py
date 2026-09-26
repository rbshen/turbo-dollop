import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.chart_events_data as ced
import data.corporate_events_data as ce
import pipeline.nightly_corporate_events as job
from core.models import CorporateEvent, CorporateEventFetch

EARNINGS = [
    {"symbol": "AAPL", "date": "2026-10-29", "epsActual": None, "epsEstimated": 1.99, "revenueActual": None, "revenueEstimated": 1.1e11},
    {"symbol": "AAPL", "date": "2026-07-30", "epsActual": 1.9, "epsEstimated": 1.8, "revenueActual": 9.0e10, "revenueEstimated": 8.9e10},
    {"symbol": "AAPL", "date": "2026-04-30", "epsActual": 1.7, "epsEstimated": 1.6, "revenueActual": 8.0e10, "revenueEstimated": 7.9e10},
]
DIVIDENDS = [
    {"symbol": "AAPL", "date": "2026-08-11", "recordDate": "2026-08-11", "paymentDate": "2026-08-14", "declarationDate": "2026-07-30",
     "adjDividend": 0.26, "dividend": 1.04, "frequency": "Quarterly"},
    {"symbol": "AAPL", "date": "2026-05-12", "adjDividend": 0.25, "dividend": 0.25},
    {"symbol": "AAPL", "date": "2026-02-09", "adjDividend": 0, "dividend": 0},
]
SPLITS = [{"symbol": "AAPL", "date": "2025-08-31", "numerator": 4, "denominator": 1, "splitType": "stock-split"}]


@pytest.fixture
def engine(monkeypatch):
    e = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(e)
    monkeypatch.setattr(ce, "engine", e)
    return e


def _fake_fmp(monkeypatch, *, earnings=EARNINGS, dividends=DIVIDENDS, splits=SPLITS, fail=()):
    calls = []

    def maker(name, payload):
        async def fake(*args, **kwargs):
            calls.append(name)
            if name in fail:
                raise httpx.ConnectError("boom")
            return payload

        return fake

    monkeypatch.setattr(ce.fmp_client, "get_earnings_history", maker("earnings", earnings))
    monkeypatch.setattr(ce.fmp_client, "get_dividends", maker("dividend", dividends))
    monkeypatch.setattr(ce.fmp_client, "get_splits", maker("split", splits))
    return calls


def test_refresh_stores_all_three_types_and_stamps_each_fetch(monkeypatch, engine):
    _fake_fmp(monkeypatch)

    result = asyncio.run(ce.refresh_ticker_events("AAPL"))

    assert result == {"earnings": 3, "dividend": 3, "split": 1}
    with Session(engine) as session:
        rows = session.exec(select(CorporateEvent)).all()
        stamps = {f.event_type: f.row_count for f in session.exec(select(CorporateEventFetch)).all()}
    assert len(rows) == 7 and stamps == {"earnings": 3, "dividend": 3, "split": 1}
    split = next(r for r in rows if r.event_type == "split")
    assert (split.split_numerator, split.split_denominator) == (4.0, 1.0)
    div = next(r for r in rows if r.event_type == "dividend" and r.event_date == date(2026, 8, 11))
    assert (div.adj_dividend, div.dividend, div.payment_date, div.frequency) == (0.26, 1.04, date(2026, 8, 14), "Quarterly")


def test_a_narrower_second_response_never_deletes_cached_rows(monkeypatch, engine):
    """Plan-downgrade safety: FMP answering with fewer rows than are cached must not lose any."""
    _fake_fmp(monkeypatch)
    asyncio.run(ce.refresh_ticker_events("AAPL"))
    with Session(engine) as session:
        before = {(r.event_type, r.event_date) for r in session.exec(select(CorporateEvent)).all()}

    _fake_fmp(monkeypatch, earnings=EARNINGS[1:2], dividends=[], splits=[])
    result = asyncio.run(ce.refresh_ticker_events("AAPL"))

    with Session(engine) as session:
        after = {(r.event_type, r.event_date) for r in session.exec(select(CorporateEvent)).all()}
        stamp = session.get(CorporateEventFetch, ("AAPL", "dividend"))
    assert after == before
    assert result == {"earnings": 3, "dividend": 3, "split": 1}  # stored counts, not response sizes
    assert stamp.row_count == 3


def test_a_refresh_inserts_new_events_and_updates_existing_ones_in_place(monkeypatch, engine):
    _fake_fmp(monkeypatch)
    asyncio.run(ce.refresh_ticker_events("AAPL"))
    with Session(engine) as session:
        ids = {r.event_date: r.id for r in session.exec(select(CorporateEvent).where(CorporateEvent.event_type == "earnings")).all()}

    revised = [dict(EARNINGS[0], epsActual=2.05), {"date": "2026-01-29", "epsActual": 1.5, "epsEstimated": 1.4, "revenueActual": 7e10}, *EARNINGS[1:]]
    _fake_fmp(monkeypatch, earnings=revised)
    asyncio.run(ce.refresh_ticker_events("AAPL"))

    with Session(engine) as session:
        rows = {r.event_date: r for r in session.exec(select(CorporateEvent).where(CorporateEvent.event_type == "earnings")).all()}
    assert len(rows) == 4
    assert rows[date(2026, 10, 29)].eps_actual == 2.05 and rows[date(2026, 10, 29)].id == ids[date(2026, 10, 29)]


def test_a_failed_endpoint_keeps_old_rows(monkeypatch, engine):
    _fake_fmp(monkeypatch)
    asyncio.run(ce.refresh_ticker_events("AAPL"))
    _fake_fmp(monkeypatch, fail=("split",))
    result = asyncio.run(ce.refresh_ticker_events("AAPL"))
    assert result["split"] == "error: ConnectError"
    with Session(engine) as session:
        assert len(session.exec(select(CorporateEvent).where(CorporateEvent.event_type == "split")).all()) == 1


def test_retention_prunes_by_event_date_and_keeps_the_boundary(engine):
    today = date(2026, 9, 26)
    cutoff = ce.retention_cutoff(today)
    assert cutoff == date(2022, 9, 27)  # 1460 days back
    with Session(engine) as session:
        for d in (cutoff - timedelta(days=1), cutoff, today):
            session.add(CorporateEvent(ticker="AAPL", event_type="earnings", event_date=d))
        session.commit()

    assert ce.prune_old_events(today) == 1

    with Session(engine) as session:
        assert {r.event_date for r in session.exec(select(CorporateEvent)).all()} == {cutoff, today}


def test_incoming_rows_older_than_retention_are_not_stored(monkeypatch, engine):
    old = {"date": "2015-01-01", "epsActual": 1.0, "epsEstimated": 1.0, "revenueActual": 1.0}
    _fake_fmp(monkeypatch, earnings=[old, *EARNINGS], dividends=[], splits=[])
    result = asyncio.run(ce.refresh_ticker_events("AAPL"))
    assert result["earnings"] == 3


def test_prune_is_independent_of_the_fmp_response_and_the_plan(monkeypatch, engine):
    """Rows older than the cap go even when FMP still returns them (deliberate cap)."""
    with Session(engine) as session:
        session.add(CorporateEvent(ticker="AAPL", event_type="dividend", event_date=date(2015, 1, 1)))
        session.commit()
    assert ce.prune_old_events() == 1


def test_retention_matches_the_chart_tabs_longest_view():
    from data.chart_data import RANGE_CONFIG

    assert ce.RETENTION_DAYS == max(c["visible_days"] for c in RANGE_CONFIG.values())


def test_splits_are_due_only_when_never_fetched_or_a_week_old(engine):
    now = datetime(2026, 9, 26, 3, 12)
    with Session(engine) as session:
        session.add(CorporateEventFetch(ticker="FRESH", event_type="split", fetched_at=now - timedelta(days=2)))
        session.add(CorporateEventFetch(ticker="WEEKOLD", event_type="split", fetched_at=now - timedelta(days=7, seconds=-30)))
        session.add(CorporateEventFetch(ticker="STALE", event_type="split", fetched_at=now - timedelta(days=9)))
        session.add(CorporateEventFetch(ticker="EARNONLY", event_type="earnings", fetched_at=now))
        session.commit()
    assert ce.splits_due(["FRESH", "WEEKOLD", "STALE", "EARNONLY", "NEW"], now) == {"WEEKOLD", "STALE", "EARNONLY", "NEW"}


def test_a_nightly_run_makes_two_calls_per_ticker_and_the_splits_run_three(monkeypatch, engine, tmp_path):
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "x.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    calls = _fake_fmp(monkeypatch)

    first = asyncio.run(job.main(["AAPL", "MSFT"]))  # never fetched -> splits due
    assert first["fmp_calls"] == 6 and sorted(calls) == ["dividend", "dividend", "earnings", "earnings", "split", "split"]

    calls.clear()
    second = asyncio.run(job.main(["AAPL", "MSFT"]))  # splits fetched moments ago -> not due
    assert second["fmp_calls"] == 4 and "split" not in calls


def test_an_error_body_served_with_http_200_keeps_the_old_rows(monkeypatch, engine):
    _fake_fmp(monkeypatch)
    asyncio.run(ce.refresh_ticker_events("AAPL"))
    _fake_fmp(monkeypatch, dividends={"Error Message": "Limit Reach"})

    result = asyncio.run(ce.refresh_ticker_events("AAPL"))

    assert str(result["dividend"]).startswith("error: ValueError")
    with Session(engine) as session:
        assert len(session.exec(select(CorporateEvent).where(CorporateEvent.event_type == "dividend")).all()) == 3


def test_cached_chart_events_apply_the_same_rules_as_the_live_path(monkeypatch, engine):
    _fake_fmp(monkeypatch)
    asyncio.run(ce.refresh_ticker_events("AAPL"))

    events = ce.read_cached_chart_events("AAPL")

    assert events.source == "fmp"
    # The scheduled report (no actuals) is dropped; only real reports count, oldest first.
    assert [e.event_date for e in events.earnings] == [date(2026, 4, 30), date(2026, 7, 30)]
    assert (events.earnings[1].eps_actual, events.earnings[1].eps_estimated) == (1.9, 1.8)
    # Split-adjusted amount, zero-amount row dropped.
    assert [(d.event_date, d.amount) for d in events.dividends] == [(date(2026, 5, 12), 0.25), (date(2026, 8, 11), 0.26)]


def test_a_ticker_that_pays_no_dividend_is_cached_as_empty_not_missing(monkeypatch, engine):
    _fake_fmp(monkeypatch, dividends=[], splits=[])
    asyncio.run(ce.refresh_ticker_events("TSLA"))

    events = ce.read_cached_chart_events("TSLA")

    assert events is not None and events.dividends == [] and len(events.earnings) == 2


def test_the_reader_returns_none_unless_earnings_and_dividends_were_both_fetched(monkeypatch, engine):
    assert ce.read_cached_chart_events("NEVER") is None
    _fake_fmp(monkeypatch, fail=("dividend",))
    asyncio.run(ce.refresh_ticker_events("HALF"))
    assert ce.read_cached_chart_events("HALF") is None  # dividends never succeeded


def test_the_chart_reads_the_cache_first_and_makes_no_fmp_or_yahoo_call(monkeypatch, engine):
    _fake_fmp(monkeypatch)
    asyncio.run(ce.refresh_ticker_events("AAPL"))

    async def fail(*a, **k):
        raise AssertionError("must not be reached when the cache answers")

    monkeypatch.setattr(ced, "_fetch_fmp", fail)
    monkeypatch.setattr(ced, "_fetch_yahoo", fail)

    out = asyncio.run(ced.fetch_chart_events("AAPL"))

    assert out.source == "fmp" and len(out.earnings) == 2 and len(out.dividends) == 2


def test_the_chart_falls_through_to_the_live_path_for_an_uncached_ticker(monkeypatch, engine):
    async def live(ticker):
        return [], []

    monkeypatch.setattr(ced, "_fetch_fmp", live)

    assert asyncio.run(ced.fetch_chart_events("UNCACHED")).source == "fmp"


def test_the_chart_serves_the_cache_while_corporate_events_is_off(monkeypatch, engine):
    import core.data_groups as dg

    _fake_fmp(monkeypatch)
    asyncio.run(ce.refresh_ticker_events("AAPL"))
    dg.set_group_enabled("corporate_events", False)

    assert asyncio.run(ced.fetch_chart_events("AAPL")).source == "fmp"


def test_the_job_refreshes_every_ticker_and_records_failures(monkeypatch, engine, tmp_path):
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "x.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    _fake_fmp(monkeypatch)

    async def fake_refresh(ticker, types=None):
        return {"earnings": 1, "dividend": "error: ConnectError", "split": 0} if ticker == "BAD" else {"earnings": 2, "dividend": 1, "split": 0}

    monkeypatch.setattr(job, "refresh_ticker_events", fake_refresh)

    result = asyncio.run(job.main(["AAPL", "BAD"]))

    assert (result["processed"], result["failed"], result["rows_written"]) == (2, 1, 4)  # BAD: 1 earnings + 0 splits; AAPL: 2 + 1 + 0
    assert result["failures"] == [("BAD", "dividend: error: ConnectError")]


def test_the_job_is_skipped_while_corporate_events_is_off(monkeypatch, tmp_path):
    import core.data_groups as dg

    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "x.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    dg.set_group_enabled("corporate_events", False)

    result = asyncio.run(job.main(["AAPL"]))

    assert result["skipped"] is True and result["processed"] == 0


def test_record_outcome_raises_only_when_every_ticker_failed():
    class Run:
        message = None

        def skip(self, reason):
            pass

    run = Run()
    job.record_outcome({"processed": 3, "failed": 1}, run)
    assert run.message == "2 refreshed, 1 with a failed endpoint"
    with pytest.raises(RuntimeError):
        job.record_outcome({"processed": 3, "failed": 3}, Run())
