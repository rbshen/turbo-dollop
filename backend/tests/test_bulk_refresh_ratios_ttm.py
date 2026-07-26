import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

import bulk_refresh_ratios_ttm as bulk_refresh
from models import FundamentalsCache, IndexConstituent


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(bulk_refresh, "engine", engine)
    # Same reasoning as test_bulk_refresh_step4_annual.py: configure_logging's
    # force=True reconfigures the ROOT logger for the rest of the pytest
    # process -- point it at a tmp_path file so tests don't pollute the real
    # backend/logs/bulk_refresh_ratios_ttm.log.
    monkeypatch.setattr(bulk_refresh, "LOG_PATH", tmp_path / "test_bulk_refresh_ratios_ttm.log")
    return engine


def _seed_stale_free_cache_row(engine, ticker: str) -> None:
    """Seeds a row that's deliberately FRESH (fetched_at=now), so a test can
    prove force_fetch refetches it anyway -- get_or_fetch would skip it."""
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker,
                statement_type="ratios",
                period="ttm",
                fetched_at=datetime.now(),
                raw_json="[{\"old\": true}]",
            )
        )
        session.commit()


def _patch_fmp_calls(monkeypatch, calls):
    async def fake_ratios_ttm(ticker):
        calls.append(ticker)
        if ticker == "BADCO":
            raise RuntimeError(f"simulated failure fetching ratios-ttm for {ticker}")
        return [{"new": True, "priceToEarningsRatioTTM": 25.0}]

    monkeypatch.setattr(bulk_refresh.fmp_client, "get_ratios_ttm", fake_ratios_ttm)
    monkeypatch.setattr(bulk_refresh.fmp_client, "request_count", 0)
    monkeypatch.setattr(bulk_refresh.fmp_client, "min_request_interval", 0.0)


def test_only_touches_ratios_ttm(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[str] = []
    _patch_fmp_calls(monkeypatch, calls)

    asyncio.run(bulk_refresh.main(tickers=["AAPL"]))

    assert calls == ["AAPL"]


def test_force_refetches_even_when_cache_row_is_fresh(monkeypatch, tmp_path):
    """Regression guard for the whole point of this script: a normal
    get_or_fetch-based fetch would skip a fresh row entirely."""
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_stale_free_cache_row(engine, "AAPL")
    calls: list[str] = []
    _patch_fmp_calls(monkeypatch, calls)

    asyncio.run(bulk_refresh.main(tickers=["AAPL"]))

    assert calls == ["AAPL"]  # fetched despite being "fresh"

    with Session(engine) as session:
        rows = session.exec(select(FundamentalsCache).where(FundamentalsCache.ticker == "AAPL")).all()
    assert len(rows) == 1
    assert "new" in rows[0].raw_json


def test_a_failing_ticker_does_not_abort_the_run(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[str] = []
    _patch_fmp_calls(monkeypatch, calls)

    summary = asyncio.run(bulk_refresh.main(tickers=["AAPL", "BADCO", "MSFT"]))

    assert calls == ["AAPL", "BADCO", "MSFT"]
    assert summary["processed"] == 3
    assert summary["failed"] == 1
    assert summary["failures"] == [("BADCO", "simulated failure fetching ratios-ttm for BADCO")]


def test_summary_reports_all_five_expected_fields(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[str] = []
    _patch_fmp_calls(monkeypatch, calls)

    summary = asyncio.run(bulk_refresh.main(tickers=["AAPL"]))

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["failures"] == []
    assert "calls_made" in summary
    assert "duration_seconds" in summary


def test_pacing_is_configured_before_the_run_starts(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[str] = []
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
    calls: list[str] = []
    _patch_fmp_calls(monkeypatch, calls)

    asyncio.run(bulk_refresh.main(tickers=None))

    assert calls == ["AAPL"]


def test_empty_ticker_list_is_handled_without_crashing(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(bulk_refresh.main(tickers=[]))

    assert summary == {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}
