"""ETF Momentum (docs/specs/momentum.md): the compute/store function, the "previous month" rule shared with the
stock endpoint, GET /api/momentum/etf, and the ETF pass of pipeline/monthly_momentum_snapshot.py."""

import asyncio
from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.data_groups as dg
import data.last_close_data as last_close_data
import data.momentum_data as momentum_data
import pipeline.monthly_momentum_snapshot as monthly_momentum
from core.main import app
from core.models import (
    EtfMomentumSnapshot,
    EtfScreenerRow,
    FundamentalsCache,
    MomentumSnapshot,
    TickerLastClose,
    TickerScore,
    TickerView,
)

ANCHOR = date(2026, 8, 31)


def _engine(monkeypatch, tmp_path=None):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(momentum_data, "engine", engine)
    monkeypatch.setattr(last_close_data, "engine", engine)
    if tmp_path is not None:
        monkeypatch.setattr(monthly_momentum, "LOG_PATH", tmp_path / "x.log")
    monkeypatch.setattr(monthly_momentum, "init_db", lambda: None)
    return engine


def _series(price_at_anchor: float, start: str = "2024-08-01") -> pd.DataFrame:
    index = pd.bdate_range(start=start, end="2026-08-31")
    return pd.DataFrame({"close": [100.0] * (len(index) - 1) + [price_at_anchor]}, index=index)


def _patch_universe_and_bars(monkeypatch, tickers, histories):
    monkeypatch.setattr(momentum_data, "load_etf_universe", lambda session: tickers)

    async def fake_bars(requested, interval, lookback_days, auto_adjust=True, unserved_tickers=None, **kwargs):
        return {t: histories[t] for t in requested if t in histories}

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", fake_bars)
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))


def _etf_snapshot(ticker, as_of, rank, composite=0.1, **kwargs):
    return EtfMomentumSnapshot(
        ticker=ticker, as_of_date=as_of, computed_at=datetime(2026, 10, 1), return_3mo=composite, return_6mo=composite,
        return_12mo=composite, composite_score=composite, rank=rank, **kwargs,
    )


# --- compute / store -------------------------------------------------------------------------------------------


def test_compute_ranks_by_composite_drops_short_history_and_has_no_moat(monkeypatch):
    engine = _engine(monkeypatch)
    _patch_universe_and_bars(
        monkeypatch,
        ["AAA", "BBB", "YOUNG"],
        {"AAA": _series(150.0), "BBB": _series(120.0), "YOUNG": _series(300.0, start="2026-03-02")},
    )

    summary = asyncio.run(momentum_data.compute_and_store_etf_momentum_snapshot(ANCHOR))

    assert (summary["universe_size"], summary["processed"], summary["dropped"]) == (3, 2, 1)
    assert summary["top5"] == ["AAA", "BBB"]
    with Session(engine) as session:
        rows = session.exec(select(EtfMomentumSnapshot).order_by(EtfMomentumSnapshot.rank)).all()
    assert [(r.ticker, r.rank, r.as_of_date) for r in rows] == [("AAA", 1, ANCHOR), ("BBB", 2, ANCHOR)]
    assert rows[0].composite_score == pytest.approx((0.5 + 0.5 + 0.5) / 3)
    assert "moat" not in EtfMomentumSnapshot.model_fields


def test_tie_break_is_by_ticker(monkeypatch):
    engine = _engine(monkeypatch)
    _patch_universe_and_bars(monkeypatch, ["ZZZ", "AAA"], {"ZZZ": _series(130.0), "AAA": _series(130.0)})
    asyncio.run(momentum_data.compute_and_store_etf_momentum_snapshot(ANCHOR))
    with Session(engine) as session:
        rows = session.exec(select(EtfMomentumSnapshot).order_by(EtfMomentumSnapshot.rank)).all()
    assert [r.ticker for r in rows] == ["AAA", "ZZZ"]


def test_rerun_replaces_only_that_dates_etf_rows(monkeypatch):
    engine = _engine(monkeypatch)
    with Session(engine) as session:
        session.add(_etf_snapshot("OLD", date(2026, 7, 31), 1))
        session.add(
            MomentumSnapshot(
                ticker="STK", as_of_date=ANCHOR, computed_at=datetime(2026, 9, 1), moat="wide_moat", return_3mo=0.1,
                return_6mo=0.1, return_12mo=0.1, composite_score=0.1, rank=1,
            )
        )
        session.commit()
    _patch_universe_and_bars(monkeypatch, ["AAA", "BBB"], {"AAA": _series(150.0), "BBB": _series(120.0)})

    asyncio.run(momentum_data.compute_and_store_etf_momentum_snapshot(ANCHOR))
    _patch_universe_and_bars(monkeypatch, ["AAA"], {"AAA": _series(150.0)})
    asyncio.run(momentum_data.compute_and_store_etf_momentum_snapshot(ANCHOR))

    with Session(engine) as session:
        etf = session.exec(select(EtfMomentumSnapshot).order_by(EtfMomentumSnapshot.as_of_date, EtfMomentumSnapshot.rank)).all()
        stock = session.exec(select(MomentumSnapshot)).all()
    assert [(r.ticker, r.as_of_date) for r in etf] == [("OLD", date(2026, 7, 31)), ("AAA", ANCHOR)]
    assert [(r.ticker, r.as_of_date) for r in stock] == [("STK", ANCHOR)]  # the stock table is untouched


def test_universe_is_the_etf_universe_not_the_stock_one(monkeypatch):
    engine = _engine(monkeypatch)
    now = datetime.now()
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="ADDEDETF", statement_type="profile", period="latest", fetched_at=now, raw_json='{"isEtf": true}'))
        session.add(TickerView(ticker="ADDEDETF", last_viewed_at=now, added_at=now, added_source="user"))
        session.add(FundamentalsCache(ticker="BROWSED", statement_type="profile", period="latest", fetched_at=now, raw_json='{"isEtf": true}'))
        session.add(TickerView(ticker="BROWSED", last_viewed_at=now))
        session.add(TickerScore(ticker="XLB", computed_at=now, is_etf=True, delisted_at=now))
        session.add(TickerScore(ticker="STK", computed_at=now, moat="wide_moat", is_etf=False))
        session.commit()
    requested: list[str] = []

    async def fake_bars(tickers, interval, lookback_days, **kwargs):
        requested.extend(tickers)
        return {}

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", fake_bars)
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))

    summary = asyncio.run(momentum_data.compute_and_store_etf_momentum_snapshot(ANCHOR))

    assert "ADDEDETF" in requested and "SPY" in requested and "XLK" in requested  # added ETF + seeds
    assert not {"BROWSED", "XLB", "STK"} & set(requested)  # browsed, delisted and stocks are out
    assert summary["universe_size"] == len(requested)


def test_cached_only_mode_reads_the_cache_and_never_fetches(monkeypatch):
    engine = _engine(monkeypatch)
    monkeypatch.setattr(momentum_data, "load_etf_universe", lambda session: ["AAA"])

    async def boom(*a, **k):
        raise AssertionError("cached_only must not fetch")

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", boom)
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no stale check")))
    seen = {}

    def fake_cached(tickers, lookback_days, reference=None):
        seen["tickers"] = tickers
        return {"AAA": _series(150.0)}

    monkeypatch.setattr(momentum_data, "read_cached_daily_bars_batch", fake_cached)

    summary = asyncio.run(momentum_data.compute_and_store_etf_momentum_snapshot(ANCHOR, cached_only=True))

    assert seen["tickers"] == ["AAA"] and summary["processed"] == 1 and summary["cached_only"] is True
    with Session(engine) as session:
        assert len(session.exec(select(EtfMomentumSnapshot)).all()) == 1


# --- previous-month rule -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dates, expected",
    [
        ([], None),
        ([date(2026, 9, 30)], None),
        ([date(2026, 9, 30), date(2026, 9, 23)], None),  # same month: not "previous"
        ([date(2026, 9, 30), date(2026, 9, 23), date(2026, 8, 31)], date(2026, 8, 31)),
        ([date(2026, 9, 30), date(2026, 8, 31), date(2026, 8, 20), date(2026, 7, 31)], date(2026, 8, 31)),  # latest in Aug
        ([date(2027, 1, 29), date(2026, 12, 31)], date(2026, 12, 31)),  # across a year boundary
    ],
)
def test_previous_snapshot_date(dates, expected):
    assert momentum_data.previous_snapshot_date(dates) == expected


def test_stock_endpoint_previous_skips_a_same_month_snapshot(monkeypatch):
    engine = _engine(monkeypatch)
    with Session(engine) as session:
        for as_of in (date(2026, 8, 31), date(2026, 9, 23), date(2026, 9, 30)):
            session.add(
                MomentumSnapshot(
                    ticker="AAA", as_of_date=as_of, computed_at=datetime(2026, 10, 1), moat="wide_moat", return_3mo=0.1,
                    return_6mo=0.1, return_12mo=0.1, composite_score=0.1, rank=1,
                )
            )
        session.commit()
    with TestClient(app) as client:
        current = client.get("/api/momentum?period=current").json()
        previous = client.get("/api/momentum?period=previous").json()
    assert current["as_of_date"] == "2026-09-30"
    assert previous["as_of_date"] == "2026-08-31"


def test_etf_endpoint_previous_skips_a_same_month_snapshot(monkeypatch):
    engine = _engine(monkeypatch)
    with Session(engine) as session:
        for as_of in (date(2026, 8, 31), date(2026, 9, 23), date(2026, 9, 30)):
            session.add(_etf_snapshot("AAA", as_of, 1))
        session.commit()
    with TestClient(app) as client:
        assert client.get("/api/momentum/etf?period=current").json()["as_of_date"] == "2026-09-30"
        assert client.get("/api/momentum/etf?period=previous").json()["as_of_date"] == "2026-08-31"


# --- endpoint ----------------------------------------------------------------------------------------------------


def test_etf_endpoint_empty_before_any_snapshot(monkeypatch):
    _engine(monkeypatch)
    with TestClient(app) as client:
        body = client.get("/api/momentum/etf").json()
    assert body == {"as_of_date": None, "computed_at": None, "total_ranked": 0, "rows": []}


def test_etf_endpoint_returns_top_five_with_joined_fields_and_no_stock_only_fields(monkeypatch):
    engine = _engine(monkeypatch)
    with Session(engine) as session:
        for rank in range(1, 9):
            session.add(_etf_snapshot(f"E{rank}", ANCHOR, rank, composite=1 - rank / 10, return_1w=0.01, return_1mo=0.02))
        session.add(EtfScreenerRow(ticker="E1", name="First Fund"))
        session.add(TickerLastClose(ticker="E1", close=55.5, as_of_date=date(2026, 9, 25), fetched_at=datetime.now()))
        session.commit()

    with TestClient(app) as client:
        body = client.get("/api/momentum/etf").json()

    assert body["as_of_date"] == "2026-08-31" and body["total_ranked"] == 8
    assert [r["ticker"] for r in body["rows"]] == ["E1", "E2", "E3", "E4", "E5"]
    first, second = body["rows"][0], body["rows"][1]
    assert first["company_name"] == "First Fund" and first["last_price"] == 55.5
    assert second["company_name"] is None and second["last_price"] is None
    assert first["return_1w"] == 0.01 and first["return_1mo"] == 0.02
    assert not {"moat", "overall_score", "quote_currency"} & set(first)


# --- the job -----------------------------------------------------------------------------------------------------


def _stock_summary(**over):
    return {"as_of_date": "2026-08-31", "universe_size": 412, "processed": 410, "dropped": 2, "stale_count": 1,
            "unserved_count": 0, "skipped_delisted_count": 1, **over}


def _etf_summary(**over):
    return {"as_of_date": "2026-08-31", "universe_size": 30, "processed": 28, "dropped": 2, "stale_count": 2,
            "unserved_count": 0, "cached_only": False, "top5": [], **over}


def _patch_passes(monkeypatch, stock=None, etf=None):
    calls = []

    async def fake_stock(anchor):
        calls.append(("stock", anchor))
        if isinstance(stock, Exception):
            raise stock
        return stock or _stock_summary()

    async def fake_etf(anchor, cached_only=False):
        calls.append(("etf", anchor, cached_only))
        if isinstance(etf, Exception):
            raise etf
        return etf or _etf_summary()

    monkeypatch.setattr(monthly_momentum, "compute_and_store_momentum_snapshot", fake_stock)
    monkeypatch.setattr(monthly_momentum, "compute_and_store_etf_momentum_snapshot", fake_etf)
    return calls


def test_job_runs_stock_then_etf_pass_and_reports_both_counts(monkeypatch, tmp_path):
    _engine(monkeypatch, tmp_path)
    calls = _patch_passes(monkeypatch)

    summary = asyncio.run(monthly_momentum.main(force_anchor=ANCHOR))

    assert [c[0] for c in calls] == ["stock", "etf"] and calls[1] == ("etf", ANCHOR, False)
    assert summary["skipped"] is False and summary["processed"] == 410 and summary["etf"]["processed"] == 28
    assert monthly_momentum.build_run_message(summary) == (
        "stocks 410/412, ETFs 28/30, 3 still stale after fetch, 0 not served by FMP (cached bars kept), 1 skipped as delisted"
    )


def test_job_etf_pass_failure_surfaces_as_a_failure(monkeypatch, tmp_path):
    _engine(monkeypatch, tmp_path)
    _patch_passes(monkeypatch, etf=RuntimeError("etf boom"))
    with pytest.raises(RuntimeError, match="etf boom"):
        asyncio.run(monthly_momentum.main(force_anchor=ANCHOR))


def test_job_stock_failure_still_runs_the_etf_pass_then_raises(monkeypatch, tmp_path):
    _engine(monkeypatch, tmp_path)
    calls = _patch_passes(monkeypatch, stock=RuntimeError("stock boom"))
    with pytest.raises(RuntimeError, match="stock boom"):
        asyncio.run(monthly_momentum.main(force_anchor=ANCHOR))
    assert [c[0] for c in calls] == ["stock", "etf"]


def test_job_group_off_skips_both_passes(monkeypatch, tmp_path):
    _engine(monkeypatch, tmp_path)
    calls = _patch_passes(monkeypatch)
    dg.set_group_enabled("daily_prices", False)

    summary = asyncio.run(monthly_momentum.main(force_anchor=ANCHOR))

    assert summary["group_skipped"] is True and calls == []


def test_etf_only_cached_mode_skips_the_stock_pass_and_the_group_gate(monkeypatch, tmp_path):
    _engine(monkeypatch, tmp_path)
    calls = _patch_passes(monkeypatch)
    dg.set_group_enabled("daily_prices", False)  # a cached read makes no FMP call, so the gate does not apply

    summary = asyncio.run(monthly_momentum.main(force_anchor=ANCHOR, etf_only=True, cached_bars_only=True))

    assert calls == [("etf", ANCHOR, True)] and summary["etf_only"] is True
    assert monthly_momentum.build_run_message(summary) == "ETFs 28/30, 2 still stale after fetch, 0 not served by FMP (cached bars kept)"


def test_cached_bars_only_requires_etf_only(monkeypatch, tmp_path):
    _engine(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(monthly_momentum.main(force_anchor=ANCHOR, cached_bars_only=True))
