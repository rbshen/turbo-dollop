"""Data-layer tests for data/stuck_check_data.py and GET /api/tickers/{t}/stuck-check. Fresh in-memory engine patched onto every module
that opens its own Session (CLAUDE.md, "Ad-hoc reproduction scripts"); the bars reader is stubbed. Cache only: no fmp_client stub is
needed because nothing here may call FMP (an unstubbed call would hit the real client and the conftest guards)."""

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.stuck_check_data as stuck_data
from core.models import FundamentalsCache, TickerScore
from data.stuck_check_data import build_fiscal_years, get_stuck_check_data, trailing_returns_pct

FY = list(range(2016, 2026))


def income_rows(revenue=lambda i: 1000.0, net_income=lambda i: 100.0, shares=lambda i: 100.0):
    return [
        {
            "fiscalYear": str(y),
            "date": f"{y}-12-31",
            "revenue": revenue(i),
            "netIncome": net_income(i),
            "operatingIncome": 150.0,
            "grossProfit": 500.0,
            "weightedAverageShsOutDil": shares(i),
        }
        for i, y in enumerate(FY)
    ][::-1]


def cash_rows(cfo=lambda i: 130.0, sbc=lambda i: 20.0, buyback=lambda i: -30.0):
    return [
        {
            "fiscalYear": str(y),
            "date": f"{y}-12-31",
            "netCashProvidedByOperatingActivities": cfo(i),
            "capitalExpenditure": -10.0,
            "stockBasedCompensation": sbc(i),
            "commonStockRepurchased": buyback(i),
            "netCommonStockIssuance": buyback(i),
            "netDividendsPaid": -5.0,
        }
        for i, y in enumerate(FY)
    ][::-1]


def metrics_rows(roic=lambda i: 0.12):
    return [{"fiscalYear": str(y), "returnOnInvestedCapital": roic(i)} for i, y in enumerate(FY)][::-1]


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(stuck_data, "engine", engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(stuck_data, "read_cached_daily_bars_batch", lambda tickers, days, reference=None: {})
    stuck_data.invalidate_sector_cache()
    yield engine
    stuck_data.invalidate_sector_cache()


def seed(engine, ticker, *, profile=None, income=None, cash=None, metrics=None, score=None):
    with Session(engine) as session:
        def put(statement_type, period, rows):
            session.add(FundamentalsCache(ticker=ticker, statement_type=statement_type, period=period, fetched_at=datetime.now(), raw_json=json.dumps(rows)))

        put("profile", "latest", [{"sector": "Technology", "industry": "Software - Application", "ipoDate": "2010-01-01", **(profile or {})}])
        put("income_statement", "annual", income if income is not None else income_rows())
        put("cash_flow_statement", "annual", cash if cash is not None else cash_rows())
        put("key_metrics", "annual", metrics if metrics is not None else metrics_rows())
        if score is not False:
            values = dict(
                sector="Technology",
                market_cap=1_000.0,
                overall_verdict="Pass",
                valuation_verdict="undervalued",
                weinstein_stage="decline",
                weinstein_stage_since_date=date(2026, 1, 5),
                perf_5y_vs_spy_status="underperform",
                perf_5y_vs_spy_pct=-12.5,
                computed_at=datetime.now(),
            )
            session.add(TickerScore(ticker=ticker, **{**values, **(score or {})}))
        session.commit()


def rows_of(out):
    return {r.key: r for r in out.rows}


def test_fiscal_years_join_statements_on_fiscal_year_and_sign_the_flows(db):
    years = build_fiscal_years(income_rows(), cash_rows(), metrics_rows())
    assert [y.fiscal_year for y in years] == [str(y) for y in FY]  # chronological
    last = years[-1]
    assert last.fcf == 120.0 and last.sbc == 20.0 and last.buybacks == 30.0 and last.net_buybacks == 30.0
    assert last.dividends == 5.0 and last.roic_pct == pytest.approx(12.0) and last.diluted_shares == 100.0


def test_card_assembles_every_row_from_the_cache(db):
    seed(db, "ACME")
    out = get_stuck_check_data("acme")
    rows = rows_of(out)
    assert out.subtitle == "Context, not scored" and out.applicable and out.has_data
    assert [r.number for r in out.rows] == sorted(r.number for r in out.rows)
    assert rows["cash_conversion"].status == "ok"  # 120 / 100 = 1.2
    assert rows["sbc"].status == "ok" and rows["share_count"].status == "ok"
    assert out.footer == "Nothing flagged"
    assert out.currency == "USD" and {f.unit for r in out.rows for f in r.figures} >= {"money", "pct", "ratio"}
    price = {f.key: f for f in rows["price_context"].figures}
    assert price["overall_verdict"].text == "Pass" and price["weinstein_stage"].text == "decline"
    assert price["perf_5y_vs_spy"].value == -12.5
    assert rows["relative_strength"].status == "not_reported"  # bars stubbed empty
    assert rows["roic"].figures[0].value == pytest.approx(12.0)


def test_a_flagged_card_has_no_footer(db):
    seed(db, "ACME", cash=cash_rows(sbc=lambda i: 300.0), income=income_rows(revenue=lambda i: 1000.0))
    out = get_stuck_check_data("ACME")
    assert rows_of(out)["sbc"].status == "flagged" and out.footer is None


def test_ipo_date_from_the_profile_narrows_the_window(db):
    seed(db, "NEWCO", profile={"ipoDate": "2024-03-21"})
    rows = rows_of(get_stuck_check_data("NEWCO"))
    assert rows["sbc"].status is None and rows["share_count"].status == "not_applicable"


def test_etf_gets_no_card_and_no_data_is_a_graceful_state(db):
    seed(db, "SPY", profile={"isEtf": True})
    etf = get_stuck_check_data("SPY")
    assert not etf.applicable and etf.rows == []
    empty = get_stuck_check_data("NOPE")
    assert empty.applicable and not empty.has_data and empty.rows[0].key == "price_context"


def test_sector_peers_give_the_median_percentile_and_weight_note(db, monkeypatch):
    seed(db, "ACME", income=income_rows(revenue=lambda i: 100 * 1.2**i), score={"market_cap": 400.0})
    for n in range(6):
        seed(db, f"P{n}", income=income_rows(revenue=lambda i, n=n: 100 * (1.02 + 0.02 * n) ** i), score={"market_cap": 100.0})
    # the tracked universe is opt-in: put them on a watchlist-equivalent via TickerView.added_at
    from core.models import TickerView

    with Session(db) as session:
        for t in ["ACME"] + [f"P{n}" for n in range(6)]:
            session.add(TickerView(ticker=t, last_viewed_at=date.today(), added_at=datetime.now()))
        session.commit()
    stuck_data.invalidate_sector_cache()
    growth = rows_of(get_stuck_check_data("ACME"))["growth"]
    figs = {f.key: f for f in growth.figures}
    assert figs["sector_percentile"].text == "86th percentile"  # 6 of 7 members below ACME's 20%
    assert figs["sector_median_cagr"].value == pytest.approx(8.0)
    # market cap 400 of a 1,000 sector total: over 10%, so the relative-strength row carries the weight note
    idx = pd.bdate_range(date.today() - timedelta(days=440), periods=300)
    frame = pd.DataFrame({"close": [100.0 + i for i in range(len(idx))]}, index=idx)
    monkeypatch.setattr(stuck_data, "read_cached_daily_bars_batch", lambda tickers, days, reference=None: {"ACME": frame, "XLK": frame, "SPY": frame})
    notes = rows_of(get_stuck_check_data("ACME"))["relative_strength"].notes
    assert notes and "40%" in notes[0]


def test_trailing_returns_use_calendar_month_anchors_and_need_enough_history():
    idx = pd.bdate_range("2025-01-01", "2026-01-30")
    close = pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float)
    result = trailing_returns_pct(close, idx[-1])
    assert result[1] == pytest.approx((close.iloc[-1] / close[close.index <= idx[-1] - pd.DateOffset(months=1)].iloc[-1] - 1) * 100)
    short = trailing_returns_pct(close[close.index >= "2025-12-01"], idx[-1])
    assert short[1] is not None and short[12] is None


def test_relative_strength_reads_cached_bars(db, monkeypatch):
    idx = pd.bdate_range(date.today() - timedelta(days=440), periods=300)

    def frame(growth):
        return pd.DataFrame({"close": [100 * (1 + growth) ** i for i in range(len(idx))]}, index=idx)

    monkeypatch.setattr(
        stuck_data, "read_cached_daily_bars_batch",
        lambda tickers, days, reference=None: {"ACME": frame(0.002), "XLK": frame(0.001), "SPY": frame(0.0005)},
    )
    seed(db, "ACME")
    row = rows_of(get_stuck_check_data("ACME"))["relative_strength"]
    words = {f.key: f.text for f in row.figures}
    assert words["vs_sector_6m"] == "leads" and words["vs_spy_12m"] == "leads"


def test_unmapped_sector_is_not_applicable(db):
    seed(db, "ACME", profile={"sector": "Mystery"})
    assert rows_of(get_stuck_check_data("ACME"))["relative_strength"].status == "not_applicable"


def test_endpoint_returns_the_card_and_never_calls_fmp(db, monkeypatch):
    from clients.fmp_client import fmp_client

    def boom(*args, **kwargs):
        raise AssertionError("the stuck check must not call FMP")

    monkeypatch.setattr(fmp_client, "get", boom, raising=False)
    seed(db, "ACME")
    body = TestClient(main.app).get("/api/tickers/acme/stuck-check").json()
    assert body["ticker"] == "ACME" and body["subtitle"] == "Context, not scored"
    assert {r["key"] for r in body["rows"]} >= {"cash_conversion", "sbc", "price_context", "relative_strength", "roic"}
    assert body["footer"].startswith("Nothing flagged")


def test_the_card_writes_nothing(db):
    seed(db, "ACME")
    with Session(db) as session:
        before = (session.exec(__import__("sqlmodel").select(FundamentalsCache)).all(), session.get(TickerScore, "ACME").computed_at)
    get_stuck_check_data("ACME")
    with Session(db) as session:
        after = (session.exec(__import__("sqlmodel").select(FundamentalsCache)).all(), session.get(TickerScore, "ACME").computed_at)
    assert len(before[0]) == len(after[0]) and before[1] == after[1]


def test_money_figures_carry_the_reporting_currency(db):
    income = [{**row, "reportedCurrency": "CNY"} for row in income_rows()]
    seed(db, "ACME", income=income)
    assert get_stuck_check_data("ACME").currency == "CNY"


# --- additive dashboard fields (docs/specs/dashboard.md): the existing figures are unchanged, new detail rides beside them -------


def _bars_frame(growth):
    idx = pd.bdate_range(date.today() - timedelta(days=440), periods=300)
    return pd.DataFrame({"close": [100 * (1 + growth) ** i for i in range(len(idx))]}, index=idx)


def test_relative_strength_returns_all_four_windows_for_stock_sector_and_spy(db, monkeypatch):
    monkeypatch.setattr(
        stuck_data, "read_cached_daily_bars_batch",
        lambda tickers, days, reference=None: {"ACME": _bars_frame(0.002), "XLK": _bars_frame(0.001), "SPY": _bars_frame(0.0005)},
    )
    seed(db, "ACME")
    row = rows_of(get_stuck_check_data("ACME"))["relative_strength"]
    detail = row.returns
    assert detail.sector_etf == "XLK" and detail.benchmark == "SPY" and detail.band_pp == 2.0
    assert [w.months for w in detail.windows] == [1, 3, 6, 12]
    one_month = detail.windows[0]
    assert one_month.stock_pct > one_month.sector_pct > one_month.spy_pct > 0  # SPY 1M and 3M are present too
    assert all(w.spy_pct is not None for w in detail.windows)
    # the gap in the existing figures is the same arithmetic as the returns next to it
    gap = {f.key: f.value for f in row.figures}["vs_sector_6m"]
    six = detail.windows[2]
    assert gap == pytest.approx(six.stock_pct - six.sector_pct)


def test_relative_strength_returns_are_blank_where_the_cache_does_not_reach(db, monkeypatch):
    short = _bars_frame(0.002).iloc[-60:]  # ~3 months of bars
    monkeypatch.setattr(stuck_data, "read_cached_daily_bars_batch", lambda tickers, days, reference=None: {"ACME": short, "XLK": short, "SPY": short})
    seed(db, "ACME")
    windows = {w.months: w for w in rows_of(get_stuck_check_data("ACME"))["relative_strength"].returns.windows}
    assert windows[1].stock_pct is not None and windows[12].stock_pct is None and windows[12].spy_pct is None


def test_relative_strength_has_no_returns_when_not_applicable_or_not_reported(db):
    seed(db, "ACME", profile={"sector": "Mystery"})
    assert rows_of(get_stuck_check_data("ACME"))["relative_strength"].returns is None
    seed(db, "NOBARS")  # bars stubbed empty
    assert rows_of(get_stuck_check_data("NOBARS"))["relative_strength"].returns is None


def test_margins_and_roic_rows_carry_per_year_series_for_the_last_five_fiscal_years(db):
    seed(db, "ACME", metrics=metrics_rows(roic=lambda i: 0.0 if i == 6 else 0.05 + i / 100))
    rows = rows_of(get_stuck_check_data("ACME"))
    margin = rows["margins"].series[0]
    assert margin.key == "operating_margin" and [p.label for p in margin.points] == ["2021", "2022", "2023", "2024", "2025"]
    assert all(p.value == pytest.approx(15.0) for p in margin.points)
    roic = rows["roic"].series[0]
    assert roic.key == "roic" and [p.label for p in roic.points] == ["2021", "2022", "2023", "2024", "2025"]
    assert roic.points[0].value == pytest.approx(10.0) and roic.points[1].value is None  # 2022: an exact zero is FMP's "no figure", blank
    assert roic.points[-1].value == pytest.approx(14.0)
    assert [f.key for f in rows["margins"].figures][:3] == ["operating_margin_first3", "operating_margin_last3", "operating_margin_slope"]  # unchanged


def test_series_are_empty_for_a_not_applicable_or_not_reported_row(db):
    seed(db, "ACME", profile={"industry": "Banks - Diversified", "sector": "Financial Services"})
    assert rows_of(get_stuck_check_data("ACME"))["roic"].series == []
    short = income_rows()[:3]
    seed(db, "THIN", income=short, cash=cash_rows()[:3], metrics=metrics_rows()[:3])
    thin = rows_of(get_stuck_check_data("THIN"))
    assert thin["margins"].series == [] and thin["growth"].series == [] and thin["growth"].growth is None


def test_growth_row_carries_the_cagr_median_percentile_and_year_on_year_series(db):
    seed(db, "ACME", income=income_rows(revenue=lambda i: 100 * 1.2**i), score={"market_cap": 400.0})
    for n in range(6):
        seed(db, f"P{n}", income=income_rows(revenue=lambda i, n=n: 100 * (1.02 + 0.02 * n) ** i), score={"market_cap": 100.0})
    from core.models import TickerView

    with Session(db) as session:
        for t in ["ACME"] + [f"P{n}" for n in range(6)]:
            session.add(TickerView(ticker=t, last_viewed_at=date.today(), added_at=datetime.now()))
        session.commit()
    stuck_data.invalidate_sector_cache()
    growth = rows_of(get_stuck_check_data("ACME"))["growth"]
    assert growth.growth.cagr_5y == pytest.approx(20.0) and growth.growth.sector_median == pytest.approx(8.0)
    assert growth.growth.percentile == 86.0 and growth.growth.sector_peers == 7
    yoy = growth.series[0]
    assert yoy.key == "revenue_growth" and len(yoy.points) == 5 and all(p.value == pytest.approx(20.0) for p in yoy.points)


def test_growth_without_enough_peers_has_a_cagr_and_no_median(db):
    seed(db, "ACME")
    growth = rows_of(get_stuck_check_data("ACME"))["growth"]
    assert growth.growth.cagr_5y == pytest.approx(0.0) and growth.growth.sector_median is None and growth.growth.percentile is None


def test_rows_carry_the_meaning_line_and_gauges_through_the_endpoint(db):
    seed(db, "ACME")
    body = TestClient(main.app).get("/api/tickers/acme/stuck-check").json()
    rows = {r["key"]: r for r in body["rows"]}
    cash = rows["cash_conversion"]
    assert cash["meaning"].startswith("Free cash flow was 1.20 times net income over the last 3 fiscal years")
    assert [(g["key"], g["line"], g["direction"]) for g in cash["gauges"]] == [("last_3y", 0.7, "floor"), ("last_10y", 0.7, "floor")]
    assert rows["sbc"]["gauges"][0]["line"] == 8.0 and rows["share_count"]["gauges"][0]["direction"] == "ceiling"
    assert rows["margins"]["meaning"] and rows["roic"]["meaning"]
    assert rows["relative_strength"]["meaning"] is None and rows["relative_strength"]["gauges"] == []
