"""Cutover step 7 (docs/specs/etf-screener.md, "Cutover"): once the stock-side jobs stop touching ETFs, nothing else may
delete an ETF's rows. Every prune/cleanup in the code base was audited (Gate 0): none keys on the stock universe (they
prune by age, by a confirmed-empty profile, by a non-US listing, or by the ETF universe itself). This pins that: an ETF
with a recent TrendAnalysis, TickerLastClose, TickerScore, bars and profile survives each of them."""

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.shared_bars_cache as shared_bars_cache
import data.etf_screener_refresh as refresh
import data.tracked_universe as tu
import pipeline.prune_cache as prune_cache_job
import pipeline.purge_invalid_tickers as purge_job
from clients.shared_bars_cache import DAILY_INTERVAL, _write_rows
from core.models import EtfScreenerRow, FundamentalsCache, SharedBarsCache, TickerLastClose, TickerScore, TickerView, TrendAnalysis


@pytest.fixture
def engine(monkeypatch):
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(e)
    for module in (prune_cache_job, purge_job, shared_bars_cache, refresh, tu):
        monkeypatch.setattr(module, "engine", e)
    return e


def _seed_etf(engine, ticker):
    now = datetime.now()
    index = pd.DatetimeIndex([pd.Timestamp(date.today() - timedelta(days=d)) for d in range(10, 0, -1)])
    bars = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 100.0, "volume": 1}, index=index)
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=now,
                                      raw_json=json.dumps([{"companyName": f"{ticker} fund", "isEtf": True}])))
        session.add(TickerView(ticker=ticker, last_viewed_at=now))
        session.add(TrendAnalysis(ticker=ticker, computed_at=now, weinstein_stage="advance"))
        session.add(TickerLastClose(ticker=ticker, close=100.0, as_of_date=date.today(), fetched_at=now))
        session.add(TickerScore(ticker=ticker, company_name=f"{ticker} fund", is_etf=True, computed_at=now - timedelta(days=3)))
        session.add(EtfScreenerRow(ticker=ticker, name=f"{ticker} fund"))
        _write_rows(session, ticker, DAILY_INTERVAL, bars, fetched_at=now)
        session.commit()


def _counts(engine, ticker):
    with Session(engine) as session:
        return {
            model.__name__: len(session.exec(select(model).where(model.ticker == ticker)).all())
            for model in (FundamentalsCache, TrendAnalysis, TickerLastClose, TickerScore, EtfScreenerRow, SharedBarsCache)
        }


def test_an_etfs_rows_survive_every_prune_and_cleanup_job(engine):
    _seed_etf(engine, "QQQ")
    before = _counts(engine, "QQQ")
    assert all(count >= 1 for count in before.values())

    prune_cache_job.prune_cache(retention_days=180)
    shared_bars_cache.prune_old_bars()
    assert purge_job.purge_invalid_tickers() == []
    with Session(engine) as session:
        universe = tu.load_etf_universe(session)
    assert "QQQ" in universe
    assert refresh.prune_etf_screener_rows(universe) == 0

    assert _counts(engine, "QQQ") == before
