import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

import nightly_fundamentals_fetch as nightly
from models import IndexConstituent


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly, "engine", engine)
    return engine


def _patch_all_steps(monkeypatch, calls, fail_for: set[str] | None = None):
    fail_for = fail_for or set()

    def make_step(name):
        async def fn(ticker):
            calls.append((ticker, name))
            if ticker in fail_for:
                raise RuntimeError(f"simulated failure fetching {name} for {ticker}")
            return None

        return fn

    monkeypatch.setattr(nightly, "get_step1_data", make_step("step1"))
    monkeypatch.setattr(nightly, "get_step2_data", make_step("step2"))
    monkeypatch.setattr(nightly, "get_step4_data", make_step("step4"))
    monkeypatch.setattr(nightly, "get_step5_data", make_step("step5"))
    monkeypatch.setattr(nightly, "get_summary", make_step("summary"))


def test_load_sp500_tickers_reads_from_the_index_constituent_table(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="sp500", ticker="MSFT", company_name="Microsoft", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="other-index", ticker="XYZ", company_name="Not S&P", last_synced_at=datetime.now()))
        session.commit()

        tickers = nightly.load_sp500_tickers(session)

    assert set(tickers) == {"AAPL", "MSFT"}


def test_a_failing_ticker_does_not_abort_the_run(monkeypatch):
    _fresh_engine(monkeypatch)
    calls: list[tuple[str, str]] = []
    _patch_all_steps(monkeypatch, calls, fail_for={"BADCO"})
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    summary = asyncio.run(nightly.main(tickers=["AAPL", "BADCO", "MSFT"]))

    # Every ticker was attempted, including the ones after the failure --
    # a single bad ticker must not stop the rest of the run.
    assert {c[0] for c in calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["processed"] == 3
    assert summary["failed"] == 1
    assert summary["failures"] == [("BADCO", "simulated failure fetching step1 for BADCO")]


def test_summary_reports_all_five_expected_fields(monkeypatch):
    _fresh_engine(monkeypatch)
    calls: list[tuple[str, str]] = []
    _patch_all_steps(monkeypatch, calls)
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    summary = asyncio.run(nightly.main(tickers=["AAPL"]))

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["failures"] == []
    assert "calls_made" in summary
    assert "duration_seconds" in summary
    # All five existing get_*_data/get_summary functions must be called for
    # every ticker -- nothing bespoke, reusing the actual pipeline.
    assert {c[1] for c in calls} == {"step1", "step2", "step4", "step5", "summary"}


def test_pacing_is_configured_before_the_run_starts(monkeypatch):
    _fresh_engine(monkeypatch)
    calls: list[tuple[str, str]] = []
    _patch_all_steps(monkeypatch, calls)
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    asyncio.run(nightly.main(tickers=["AAPL"]))

    expected_interval = 60.0 / nightly.TARGET_REQUESTS_PER_MINUTE
    assert nightly.fmp_client.min_request_interval == expected_interval


def test_empty_ticker_list_is_handled_without_crashing(monkeypatch):
    _fresh_engine(monkeypatch)

    summary = asyncio.run(nightly.main(tickers=[]))

    assert summary == {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}
