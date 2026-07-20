import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

import bulk_refresh_step4_annual as bulk_refresh
from models import FundamentalsCache, IndexConstituent


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(bulk_refresh, "engine", engine)
    # Same reasoning as test_nightly_fundamentals_fetch.py: configure_logging's
    # force=True reconfigures the ROOT logger for the rest of the pytest
    # process -- point it at a tmp_path file so tests don't pollute the real
    # backend/logs/bulk_refresh_step4_annual.log.
    monkeypatch.setattr(bulk_refresh, "LOG_PATH", tmp_path / "test_bulk_refresh.log")
    return engine


def _seed_stale_free_cache_row(engine, ticker: str, statement_type: str) -> None:
    """Seeds a row that's deliberately FRESH (fetched_at=now), so a test can
    prove force_fetch refetches it anyway -- get_or_fetch would skip it."""
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker,
                statement_type=statement_type,
                period="annual",
                fetched_at=datetime.now(),
                raw_json="[{\"old\": true, \"count\": 5}]",
            )
        )
        session.commit()


def _patch_fmp_calls(monkeypatch, calls):
    async def fake_balance_sheet(ticker, period, limit):
        calls.append((ticker, "balance_sheet_statement", limit))
        if ticker == "BADCO":
            raise RuntimeError(f"simulated failure fetching balance sheet for {ticker}")
        return [{"new": True, "count": limit}]

    async def fake_key_metrics(ticker, period, limit):
        calls.append((ticker, "key_metrics", limit))
        return [{"new": True, "count": limit}]

    monkeypatch.setattr(bulk_refresh.fmp_client, "get_balance_sheet_statement", fake_balance_sheet)
    monkeypatch.setattr(bulk_refresh.fmp_client, "get_key_metrics", fake_key_metrics)
    monkeypatch.setattr(bulk_refresh.fmp_client, "request_count", 0)
    monkeypatch.setattr(bulk_refresh.fmp_client, "min_request_interval", 0.0)


def test_only_touches_balance_sheet_and_key_metrics_annual(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, str, int]] = []
    _patch_fmp_calls(monkeypatch, calls)

    asyncio.run(bulk_refresh.main(tickers=["AAPL"]))

    assert {c[1] for c in calls} == {"balance_sheet_statement", "key_metrics"}
    assert {c[2] for c in calls} == {10}  # DISPLAY_ANNUAL_WINDOW, not the old limit=5


def test_force_refetches_even_when_cache_row_is_fresh(monkeypatch, tmp_path):
    """Regression guard for the whole point of this script: a normal
    get_or_fetch-based fetch would skip a fresh row entirely, silently
    leaving the ticker stuck at its old limit=5 data."""
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_stale_free_cache_row(engine, "AAPL", "balance_sheet_statement")
    _seed_stale_free_cache_row(engine, "AAPL", "key_metrics")
    calls: list[tuple[str, str, int]] = []
    _patch_fmp_calls(monkeypatch, calls)

    asyncio.run(bulk_refresh.main(tickers=["AAPL"]))

    assert len(calls) == 2  # both fetched despite being "fresh"

    with Session(engine) as session:
        rows = session.exec(
            select(FundamentalsCache).where(FundamentalsCache.ticker == "AAPL")
        ).all()
    assert len(rows) == 2
    for row in rows:
        assert "new" in row.raw_json
        assert "count\": 10" in row.raw_json


def test_a_failing_ticker_does_not_abort_the_run(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, str, int]] = []
    _patch_fmp_calls(monkeypatch, calls)

    summary = asyncio.run(bulk_refresh.main(tickers=["AAPL", "BADCO", "MSFT"]))

    assert {c[0] for c in calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["processed"] == 3
    assert summary["failed"] == 1
    assert summary["failures"] == [("BADCO", "simulated failure fetching balance sheet for BADCO")]


def test_summary_reports_all_five_expected_fields(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, str, int]] = []
    _patch_fmp_calls(monkeypatch, calls)

    summary = asyncio.run(bulk_refresh.main(tickers=["AAPL"]))

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["failures"] == []
    # request_count is incremented inside fmp_client.get() itself, which
    # these tests bypass by faking get_balance_sheet_statement/get_key_metrics
    # directly -- calls_made just needs to be present, same as the nightly
    # script's equivalent test.
    assert "calls_made" in summary
    assert "duration_seconds" in summary


def test_pacing_is_configured_before_the_run_starts(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, str, int]] = []
    _patch_fmp_calls(monkeypatch, calls)

    asyncio.run(bulk_refresh.main(tickers=["AAPL"]))

    expected_interval = 60.0 / bulk_refresh.TARGET_REQUESTS_PER_MINUTE
    assert bulk_refresh.fmp_client.min_request_interval == expected_interval


def test_load_sp500_tickers_reused_from_nightly_script(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="other-index", ticker="XYZ", company_name="Not S&P", last_synced_at=datetime.now()))
        session.commit()
    calls: list[tuple[str, str, int]] = []
    _patch_fmp_calls(monkeypatch, calls)

    asyncio.run(bulk_refresh.main(tickers=None))

    assert {c[0] for c in calls} == {"AAPL"}


def test_empty_ticker_list_is_handled_without_crashing(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(bulk_refresh.main(tickers=[]))

    assert summary == {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}
