import asyncio
from datetime import date, datetime

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.momentum_data as momentum_data
from core.models import MomentumSnapshot, TickerScore


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(momentum_data, "engine", engine)
    return engine


def _series(price_at_anchor: float) -> pd.DataFrame:
    # Flat, 2 years of daily history so every ticker clears the 12mo
    # lookback window -- composite score varies only via `price_at_anchor`.
    index = pd.bdate_range(start="2024-08-01", end="2026-08-31")
    return pd.DataFrame({"Close": [100.0] * (len(index) - 1) + [price_at_anchor]}, index=index)


def _patch_universe_and_prices(monkeypatch, tickers: list[str], histories: dict[str, pd.DataFrame]):
    monkeypatch.setattr(momentum_data, "load_full_tracked_universe", lambda session: tickers)

    async def fake_get_history(requested_tickers, period, interval):
        return {t: histories[t] for t in requested_tickers if t in histories}

    monkeypatch.setattr(momentum_data.yahoo_client, "get_history", fake_get_history)


def test_tickers_without_a_moat_set_are_excluded_from_the_universe(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="WIDE", moat="wide_moat", company_name="Wide Co", overall_score=80, computed_at=datetime.now()))
        session.add(TickerScore(ticker="NOMOAT", moat=None, company_name="Unrated Co", computed_at=datetime.now()))
        session.commit()

    _patch_universe_and_prices(
        monkeypatch, ["WIDE", "NOMOAT"], {"WIDE": _series(150.0), "NOMOAT": _series(200.0)}
    )

    anchor = date(2026, 8, 31)
    summary = asyncio.run(momentum_data.compute_and_store_momentum_snapshot(anchor))

    assert summary["universe_size"] == 1
    with Session(engine) as session:
        rows = session.exec(select(MomentumSnapshot)).all()
    assert [r.ticker for r in rows] == ["WIDE"]
    assert rows[0].moat == "wide_moat"


def test_rerun_on_same_anchor_date_replaces_rather_than_duplicates(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAA", moat="narrow_moat", company_name="AAA Inc", overall_score=70, computed_at=datetime.now()))
        session.commit()

    anchor = date(2026, 8, 31)
    _patch_universe_and_prices(monkeypatch, ["AAA"], {"AAA": _series(120.0)})
    asyncio.run(momentum_data.compute_and_store_momentum_snapshot(anchor))
    asyncio.run(momentum_data.compute_and_store_momentum_snapshot(anchor))

    with Session(engine) as session:
        rows = session.exec(select(MomentumSnapshot)).all()
    assert len(rows) == 1


def test_get_momentum_snapshot_empty_before_any_run(monkeypatch):
    _fresh_engine(monkeypatch)
    result = momentum_data.get_momentum_snapshot("current")
    assert result.as_of_date is None
    assert result.computed_at is None
    assert result.rows == []


def test_get_momentum_snapshot_current_vs_previous(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAA", moat="wide_moat", company_name="AAA Inc", overall_score=70, computed_at=datetime.now()))
        session.commit()

    _patch_universe_and_prices(monkeypatch, ["AAA"], {"AAA": _series(130.0)})
    asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 7, 31)))
    asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))

    current = momentum_data.get_momentum_snapshot("current")
    previous = momentum_data.get_momentum_snapshot("previous")

    assert current.as_of_date == date(2026, 8, 31)
    assert previous.as_of_date == date(2026, 7, 31)
    assert current.rows[0].overall_score == 70
    assert current.rows[0].company_name == "AAA Inc"


def test_get_momentum_snapshot_previous_empty_when_only_one_month_exists(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAA", moat="wide_moat", company_name="AAA Inc", computed_at=datetime.now()))
        session.commit()

    _patch_universe_and_prices(monkeypatch, ["AAA"], {"AAA": _series(130.0)})
    asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))

    previous = momentum_data.get_momentum_snapshot("previous")
    assert previous.as_of_date is None
    assert previous.rows == []

