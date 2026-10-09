"""P/E history chart (docs/specs/sector-industry-pe.md, "Phase 2"): TTM EPS maths and timing, the EPS <= 0 / gap /
duplicate-quarter handling, ADR, exchange selection, sector / industry gaps and fallback, ETF / OTC statuses, the
1-year window, the route shape and the no-FMP-call guarantee."""

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.pe_history_data as ph
import data.sector_industry_pe_data as sip
from core.models import FundamentalsCache, SectorIndustryPe

TODAY = date.today()


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(ph, "engine", eng)
    monkeypatch.setattr(sip, "engine", eng)

    class NoFmp:
        def __getattr__(self, name):
            raise AssertionError(f"FMP must not be called ({name})")

    monkeypatch.setattr(sip, "fmp_client", NoFmp())
    return eng


def _quarter(end: date, eps: float, filed: date | None = None, period="Q1", fy="2026", currency="USD") -> dict:
    return {
        "date": end.isoformat(),
        "filingDate": (filed or end + timedelta(days=30)).isoformat(),
        "epsDiluted": eps,
        "period": period,
        "fiscalYear": fy,
        "reportedCurrency": currency,
    }


def _quarters(eps: list[float], last_end: date = TODAY - timedelta(days=60), **kw) -> list[dict]:
    """Newest first, quarter ends 91 days apart, the newest ending at `last_end`."""
    return [_quarter(last_end - timedelta(days=91 * i), v, **kw) for i, v in enumerate(eps)]


def _cache(engine, ticker, statement_type, period, rows):
    with Session(engine) as s:
        s.add(FundamentalsCache(ticker=ticker, statement_type=statement_type, period=period, fetched_at=datetime.now(), raw_json=json.dumps(rows)))
        s.commit()


def _profile(engine, ticker="ABC", **kw):
    row = {"exchange": "NASDAQ", "sector": "Technology", "industry": "Software - Application", "currency": "USD", **kw}
    _cache(engine, ticker, "profile", "latest", [row])


def _pe_rows(engine, kind, name, exchange, values: dict[date, float]):
    with Session(engine) as s:
        for d, pe in values.items():
            s.add(SectorIndustryPe(kind=kind, name=name, exchange=exchange, date=d, pe=pe))
        s.commit()


def _bars(monkeypatch, closes: dict[date, float]):
    frame = pd.DataFrame({"close": list(closes.values())}, index=pd.DatetimeIndex([pd.Timestamp(d) for d in closes]))
    monkeypatch.setattr(ph, "read_cached_completed_daily_bars", lambda ticker, days: frame)


def _days(n: int) -> list[date]:
    return [TODAY - timedelta(days=n - 1 - i) for i in range(n)]


# --- the maths ---------------------------------------------------------------------------------------------------

def test_ttm_is_sum_of_four_and_applies_from_the_fourth_quarters_filing_date():
    q = _quarters([2.0, 1.0, 1.0, 1.0, 0.5])
    steps = ph.ttm_eps_steps(q, [])
    assert [v for _, v in steps] == [3.5, 5.0]  # oldest window first: 0.5+1+1+1, then 1+1+1+2
    newest_filed = date.fromisoformat(q[0]["filingDate"])
    assert steps[-1][0] == newest_filed


def test_pe_is_close_over_ttm_eps_with_no_lookahead():
    q = _quarters([2.0, 1.0, 1.0, 1.0])
    filed = date.fromisoformat(q[0]["filingDate"])
    closes = pd.Series([100.0, 100.0], index=pd.DatetimeIndex([filed - timedelta(days=1), filed]))
    pe = ph.ticker_pe_series(closes, ph.ttm_eps_steps(q, []))
    assert list(pe.index) == [pd.Timestamp(filed)]  # the day before the filing has no EPS in force
    assert pe.iloc[0] == pytest.approx(100 / 5.0)


def test_non_positive_ttm_eps_days_are_dropped():
    q = _quarters([-1.0, -1.0, -1.0, 0.5, 0.5, 0.5, 0.5, 0.5])
    steps = ph.ttm_eps_steps(q, [])
    closes = pd.Series(50.0, index=pd.DatetimeIndex([pd.Timestamp(s[0]) for s in steps]))
    pe = ph.ticker_pe_series(closes, steps)
    assert len(pe) == sum(1 for _, v in steps if v and v > 0)
    assert (pe > 0).all()
    assert len(pe) < len(closes)


def test_fewer_than_four_quarters_gives_no_steps():
    assert ph.ttm_eps_steps(_quarters([1.0, 1.0, 1.0]), []) == []


def test_missing_quarter_gap_breaks_the_window():
    q = _quarters([1.0] * 6)
    del q[2]  # a quarter missing: a 182-day gap
    steps = ph.ttm_eps_steps(q, [])
    assert steps and all(v is None for _, v in steps)


def test_q4_row_duplicating_the_annual_eps_breaks_its_windows_and_is_not_carried_over():
    q = _quarters([1.0] * 5)
    q[1]["period"], q[1]["fiscalYear"], q[1]["epsDiluted"] = "Q4", "2025", 4.0
    annual = [{"fiscalYear": "2025", "epsDiluted": 4.0}]
    steps = ph.ttm_eps_steps(q, annual)
    assert steps[-1][1] is None
    closes = pd.Series(10.0, index=pd.DatetimeIndex([pd.Timestamp(steps[-1][0])]))
    assert ph.ticker_pe_series(closes, steps).empty  # the older valid EPS is not held across the broken window


# --- get_pe_history ----------------------------------------------------------------------------------------------

def test_full_series_with_overlays_and_latest(engine, monkeypatch):
    _profile(engine)
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([1.0, 1.0, 1.0, 1.0, 1.0]))
    days = _days(30)
    _bars(monkeypatch, {d: 40.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in days})
    _pe_rows(engine, "industry", "Software - Application", "NASDAQ", {d: 30.0 for d in days})
    out = ph.get_pe_history("ABC")
    assert out.status == "ok" and out.stock_status == "ok" and not out.industry_fallback
    assert out.latest_stock.value == 10.0 and out.latest_sector.value == 25.0 and out.latest_industry.value == 30.0
    assert len(out.points) == 30 and out.points[-1].stock == 10.0
    assert out.stock_starts == out.points[0].date  # EPS was already in force: no late-start marker


def test_stock_starts_later_than_the_first_point(engine, monkeypatch):
    _profile(engine)
    q = _quarters([1.0, 1.0, 1.0, 1.0], last_end=TODAY - timedelta(days=50))  # filed 20 days ago
    _cache(engine, "ABC", "income_statement", "quarterly", q)
    days = _days(60)
    _bars(monkeypatch, {d: 40.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in days})
    out = ph.get_pe_history("ABC")
    assert out.stock_starts == q[0]["filingDate"] and out.stock_starts > out.points[0].date
    assert out.points[0].stock is None and out.points[-1].stock == 10.0


def test_sector_and_industry_use_the_tickers_own_exchange(engine, monkeypatch):
    _profile(engine, exchange="NYSE")
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([1.0] * 5))
    days = _days(10)
    _bars(monkeypatch, {d: 40.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 99.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NYSE", {d: 21.0 for d in days})
    out = ph.get_pe_history("ABC")
    assert out.exchange == "NYSE" and out.latest_sector.value == 21.0


def test_zero_pe_is_a_gap_and_never_plotted(engine, monkeypatch):
    _profile(engine)
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([1.0] * 5))
    days = _days(20)
    _bars(monkeypatch, {d: 40.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: (0.0 if i in (3, 4) else 22.0) for i, d in enumerate(days)})
    out = ph.get_pe_history("ABC")
    assert out.points[3].sector is None and out.points[4].sector is None
    assert out.points[5].sector == 22.0 and all(p.sector != 0 for p in out.points)


def test_industry_missing_falls_back_to_the_sector_line(engine, monkeypatch):
    _profile(engine, industry="Asset Management")
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([1.0] * 5))
    days = _days(10)
    _bars(monkeypatch, {d: 40.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in days})
    out = ph.get_pe_history("ABC")
    assert out.industry_fallback and out.sector_available and not out.industry_available
    assert out.latest_industry is None and out.latest_sector.value == 25.0


@pytest.mark.parametrize("extra,status", [({"isEtf": True}, "etf"), ({"isFund": True}, "etf"), ({"exchange": "OTC"}, "unsupported_exchange"), ({"exchange": "CBOE"}, "unsupported_exchange")])
def test_etf_and_unsupported_exchange_have_no_series(engine, monkeypatch, extra, status):
    _profile(engine, **extra)
    _bars(monkeypatch, {d: 40.0 for d in _days(5)})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in _days(5)})
    out = ph.get_pe_history("ABC")
    assert out.status == status and out.points == [] and out.note


def test_no_profile(engine):
    assert ph.get_pe_history("ZZZ").status == "no_profile"


def test_all_eps_non_positive_is_an_empty_stock_state_overlays_remain(engine, monkeypatch):
    _profile(engine)
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([-1.0] * 6))
    days = _days(10)
    _bars(monkeypatch, {d: 40.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in days})
    out = ph.get_pe_history("ABC")
    assert out.stock_status == "no_eps" and out.latest_stock is None and out.latest_sector.value == 25.0


def test_adr_has_no_stock_line_but_keeps_overlays(engine, monkeypatch):
    _profile(engine)
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([1.0] * 5, currency="TWD"))
    days = _days(10)
    _bars(monkeypatch, {d: 40.0 for d in days})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in days})
    out = ph.get_pe_history("ABC")
    assert out.stock_status == "adr" and out.latest_stock is None and out.sector_available


def test_no_bars_uses_the_overlay_dates(engine, monkeypatch):
    _profile(engine)
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([1.0] * 5))
    monkeypatch.setattr(ph, "read_cached_completed_daily_bars", lambda t, d: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in _days(10)})
    out = ph.get_pe_history("ABC")
    assert out.stock_status == "no_prices" and len(out.points) == 10 and out.latest_sector.value == 25.0


def test_window_is_one_year_even_though_five_years_are_stored(engine, monkeypatch):
    _profile(engine)
    _cache(engine, "ABC", "income_statement", "quarterly", _quarters([1.0] * 5))
    old = TODAY - timedelta(days=800)
    _bars(monkeypatch, {old: 40.0, TODAY - timedelta(days=5): 40.0})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {old: 20.0, TODAY - timedelta(days=5): 25.0})
    out = ph.get_pe_history("ABC")
    assert [p.date for p in out.points] == [(TODAY - timedelta(days=5)).isoformat()]
    assert out.window_start == sip.window_start(years=1).isoformat()


# --- route -------------------------------------------------------------------------------------------------------

def test_route_shape_and_ticker_normalisation(engine, monkeypatch):
    _profile(engine, ticker="BRK-B")
    _bars(monkeypatch, {d: 40.0 for d in _days(3)})
    _pe_rows(engine, "sector", "Technology", "NASDAQ", {d: 25.0 for d in _days(3)})
    body = TestClient(main.app).get("/api/tickers/brk-b/pe-history").json()
    assert body["ticker"] == "BRK-B" and body["status"] == "ok"
    assert body["label"] == "average PE of listed companies (FMP)"
    assert set(body["points"][0]) == {"date", "stock", "sector", "industry"}
