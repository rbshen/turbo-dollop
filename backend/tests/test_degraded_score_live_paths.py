"""M5: a transient FMP failure on the two live score paths other than Refresh -- the /score frozen-row recompute and the
universe Add -- must not persist an all-None score. Same shape as test_refresh_fallback.py: the chain is real (endpoint ->
compute_ticker_score -> the real step functions), only the FMP client is faked (it answers the profile and times out on
everything else), and every module's own `engine` points at one in-memory DB."""

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.speculative_growth_data as speculative_growth_data
import data.step1_data as step1_data
import data.step2_data as step2_data
import data.step3_data as step3_data
import data.step4_data as step4_data
import data.step5_data as step5_data
import data.ticker_score as ticker_score
import data.ticker_summary as ticker_summary
import data.tracked_universe as tracked_universe
import data.universe_membership as universe_membership
import pipeline.refresh as refresh
from clients.fmp_client import fmp_client
from core.models import TickerScore, TickerView
from scoring.overall import SCORE_FORMULA_VERSION

MODULES = (
    main, refresh, ticker_score, step1_data, step2_data, step3_data, step4_data, step5_data, ticker_summary, speculative_growth_data,
    tracked_universe, universe_membership,
)
PROFILE = [{"symbol": "AAPL", "companyName": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "marketCap": 3e12, "exchange": "NASDAQ"}]


@pytest.fixture()
def engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(test_engine)
    for module in MODULES:
        monkeypatch.setattr(module, "engine", test_engine)
    return test_engine


@pytest.fixture()
def failing_fmp(monkeypatch):
    """The profile answers; every other endpoint times out like an outage. Prices answer empty so they are not the failure."""

    async def get(endpoint, params=None, group=None):
        if endpoint == "/profile":
            return PROFILE
        raise httpx.ReadTimeout("FMP timed out")

    async def empty(*_args, **_kwargs):
        return []

    monkeypatch.setattr(fmp_client, "get", get)
    monkeypatch.setattr(fmp_client, "get_historical_price_eod", empty)


def _score(engine) -> TickerScore | None:
    with Session(engine) as session:
        return session.get(TickerScore, "AAPL")


def test_score_endpoint_serves_the_stored_row_when_the_frozen_recompute_hits_a_transient_fmp_failure(engine, failing_fmp):
    long_ago = datetime.now() - timedelta(days=60)
    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="AAPL", company_name="Apple Inc.", overall_score=88, overall_verdict="Strong Pass", step1_score=90,
                computed_at=long_ago, formula_version=SCORE_FORMULA_VERSION,
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/score")

    assert response.status_code == 200
    body = response.json()
    assert (body["overall_score"], body["step1_score"]) == (88, 90)  # the last good row, not one built from missing inputs
    stored = _score(engine)
    assert (stored.overall_score, stored.step1_score, stored.computed_at) == (88, 90, long_ago)  # and nothing was upserted


def test_add_reports_score_not_computed_and_stores_no_degraded_row_after_a_transient_fmp_failure(engine, failing_fmp):
    with Session(engine) as session:
        session.add(TickerView(ticker="AAPL", last_viewed_at=datetime.now() - timedelta(days=2)))
        session.commit()

    with TestClient(main.app) as client:
        response = client.post("/api/tickers/AAPL/universe")

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True  # the add itself stands
    assert body["score_computed"] is False
    assert body["reason"] == "fetch_failed"
    assert "no score was stored" in body["message"] and "computed its score" not in body["message"]
    assert _score(engine) is None  # no all-None row was written
    with Session(engine) as session:
        assert session.exec(select(TickerView).where(TickerView.ticker == "AAPL", TickerView.added_at.is_not(None))).first() is not None
