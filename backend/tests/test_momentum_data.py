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
    # Lowercase column, matching what clients/shared_bars_cache.py::
    # get_or_fetch_bars_batch returns.
    index = pd.bdate_range(start="2024-08-01", end="2026-08-31")
    return pd.DataFrame({"close": [100.0] * (len(index) - 1) + [price_at_anchor]}, index=index)


def _patch_universe_and_prices(
    monkeypatch, tickers: list[str], histories: dict[str, pd.DataFrame], unserved_tickers: list[str] | None = None
):
    monkeypatch.setattr(momentum_data, "load_tracked_universe", lambda session: tickers)
    fallback = unserved_tickers or []

    async def fake_get_bars_batch(requested_tickers, interval, lookback_days, auto_adjust=True, unserved_tickers=None, **kwargs):
        if unserved_tickers is not None:
            unserved_tickers.extend(fallback)
        return {t: histories[t] for t in requested_tickers if t in histories}

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", fake_get_bars_batch)
    # stale_ticker_count reads clients.shared_bars_cache's OWN engine
    # directly -- stubbed here too, same reasoning as
    # tests/test_nightly_trend_calculation.py's own _patch_batch_fetch.
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))


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


def test_delisted_tickers_are_excluded_from_the_universe(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="WIDE", moat="wide_moat", company_name="Wide Co", overall_score=80, computed_at=datetime.now()))
        session.add(
            TickerScore(
                ticker="TWTR", moat="narrow_moat", company_name="Twitter Inc", overall_score=60, computed_at=datetime.now(),
                delisted_at=datetime.now(),
            )
        )
        session.commit()

    _patch_universe_and_prices(monkeypatch, ["WIDE", "TWTR"], {"WIDE": _series(150.0), "TWTR": _series(50.0)})

    summary = asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))

    assert summary["universe_size"] == 1
    assert summary["skipped_delisted_count"] == 1
    with Session(engine) as session:
        rows = session.exec(select(MomentumSnapshot)).all()
    assert [r.ticker for r in rows] == ["WIDE"]


def test_summary_reports_the_unserved_count_from_the_batch_fetch(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="WIDE", moat="wide_moat", company_name="Wide Co", overall_score=80, computed_at=datetime.now()))
        session.commit()

    _patch_universe_and_prices(monkeypatch, ["WIDE"], {"WIDE": _series(150.0)}, unserved_tickers=["WIDE"])

    summary = asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))

    assert summary["unserved_count"] == 1


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



def test_get_momentum_snapshot_joins_the_review_status_from_the_same_score_row(monkeypatch):
    import json

    engine = _fresh_engine(monkeypatch)
    reason = {
        "step": "step5", "score": 43, "verdict": "Fail", "hint": "unclear", "raw_hint": "unclear",
        "guarded": False, "rule": "not_covered", "evidence": "Current Ratio 0.78 (borderline_fail)",
    }
    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="REV", moat="wide_moat", company_name="Rev Inc", overall_score=71, overall_verdict="Pass",
                review_status="review_unclear", review_reasons=json.dumps([reason]), conviction="high",
                computed_at=datetime.now(),
            )
        )
        session.add(TickerScore(ticker="PLAIN", moat="wide_moat", company_name="Plain Inc", overall_score=80, overall_verdict="Pass", computed_at=datetime.now()))
        session.commit()

    _patch_universe_and_prices(monkeypatch, ["REV", "PLAIN"], {"REV": _series(130.0), "PLAIN": _series(125.0)})
    asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))
    rows = {r.ticker: r for r in momentum_data.get_momentum_snapshot("current").rows}

    assert rows["REV"].review_status == "review_unclear"
    assert [r.model_dump() for r in rows["REV"].review_reasons] == [reason]
    assert rows["REV"].conviction == "high"
    assert (rows["REV"].overall_score, rows["REV"].overall_verdict) == (71, "Pass")
    # No status: every new field is null, and the existing ones are as before.
    plain = rows["PLAIN"]
    assert (plain.review_status, plain.review_reasons, plain.conviction) == (None, None, None)
    assert (plain.overall_score, plain.overall_verdict) == (80, "Pass")


def test_ranking_order_does_not_depend_on_the_review_status(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        for ticker, status in (("AAA", None), ("BBB", "review_unclear")):
            session.add(TickerScore(ticker=ticker, moat="wide_moat", company_name=ticker, overall_score=70, overall_verdict="Pass", review_status=status, review_reasons="[]" if status else None, computed_at=datetime.now()))
        session.commit()

    _patch_universe_and_prices(monkeypatch, ["AAA", "BBB"], {"AAA": _series(130.0), "BBB": _series(160.0)})
    asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))
    rows = momentum_data.get_momentum_snapshot("current").rows

    assert [r.ticker for r in rows] == ["BBB", "AAA"]
    assert [r.rank for r in rows] == [1, 2]
