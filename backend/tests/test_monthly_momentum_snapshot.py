import asyncio
from datetime import date, datetime

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.momentum_data as momentum_data
import pipeline.monthly_momentum_snapshot as monthly_momentum
from core.models import MomentumSnapshot, TickerScore


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(momentum_data, "engine", engine)
    monkeypatch.setattr(monthly_momentum, "LOG_PATH", tmp_path / "test_monthly_momentum_snapshot.log")
    return engine


def _series(price_at_anchor: float) -> pd.DataFrame:
    index = pd.bdate_range(start="2024-08-01", end="2026-08-31")
    return pd.DataFrame({"close": [100.0] * (len(index) - 1) + [price_at_anchor]}, index=index)


def test_non_anchor_day_is_a_no_op_but_still_a_successful_run(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(monthly_momentum, "resolve_month_end_anchor", lambda today: None)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("must not compute a snapshot on a non-anchor day")

    monkeypatch.setattr(monthly_momentum, "compute_and_store_momentum_snapshot", fail_if_called)

    summary = asyncio.run(monthly_momentum.main())

    assert summary == {"processed": 0, "skipped": True, "reason": "not the first trading day of the month"}


def _stub_stale_count(monkeypatch):
    # stale_ticker_count reads clients.shared_bars_cache's OWN engine
    # directly (not momentum_data's) -- stubbed here so it never falls
    # through to a real (potentially on-disk) engine.
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))


def test_anchor_day_computes_and_persists_a_snapshot(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAA", moat="wide_moat", company_name="AAA Inc", overall_score=70, computed_at=datetime.now()))
        session.commit()

    monkeypatch.setattr(momentum_data, "load_full_tracked_universe", lambda session: ["AAA"])
    _stub_stale_count(monkeypatch)

    async def fake_get_bars_batch(tickers, interval, lookback_days, auto_adjust=True, **kwargs):
        return {"AAA": _series(130.0)}

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", fake_get_bars_batch)

    summary = asyncio.run(monthly_momentum.main(force_anchor=date(2026, 8, 31)))

    assert summary["skipped"] is False
    assert summary["processed"] == 1
    with Session(engine) as session:
        rows = session.exec(select(MomentumSnapshot)).all()
    assert rows[0].ticker == "AAA"
    assert rows[0].as_of_date == date(2026, 8, 31)
