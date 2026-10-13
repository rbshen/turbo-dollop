"""Wrongly typed upstream (FMP) fields degrade that one field to None instead of failing the response (cleanup batch 2026-10-13,
helpers/coerce.py). One malformed fixture per group: ticker summary (profile, quote, price change, ratios TTM, growth, enterprise
values), Valuation inputs, Ratios tab, Analyst ratings tab, ETF overview, Chart. A clean field next to a bad one stays intact.

Every FMP client method is replaced with a fake and every module's own `engine` reference is patched to one in-memory engine."""

import asyncio
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.db as core_db
import core.main as main
import data.chart_data as chart_data
from clients.fmp_client import FMPClient, fmp_client
from conftest import real_engine as _real_core_engine
from core.models import FundamentalsCache
from data.analyst_ratings_data import get_analyst_ratings_data
from data.chart_events_data import ChartEvents
from data.etf_data import get_etf_overview
from data.ratios_data import get_ratios_data
from data.ticker_summary import get_summary
from helpers.coerce import clean_row, count_or_zero, finite_number, first_row, text_or_none
from helpers.first import _first

NAN, INF = float("nan"), float("inf")

STOCK_PROFILE_CLEAN = {"companyName": "Apple Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Consumer Electronics", "beta": 1.2}


@pytest.fixture
def install(monkeypatch):
    """install({"get_profile": ..., ...}) -> the in-memory engine; every other FMPClient get_* answers []."""

    def _install(answers: dict):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(engine)
        for module in list(sys.modules.values()):
            if module is not core_db and getattr(module, "engine", None) is _real_core_engine:
                monkeypatch.setattr(module, "engine", engine)

        def fake(name):
            async def _call(*_args, **_kwargs):
                return answers.get(name, [])

            return _call

        for name in dir(FMPClient):
            if name.startswith("get_") and callable(getattr(FMPClient, name)):
                monkeypatch.setattr(fmp_client, name, fake(name))
        return engine

    return _install


def _cache(engine, ticker, statement_type, period, payload):
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker=ticker, statement_type=statement_type, period=period, fetched_at=datetime.now(), raw_json=json.dumps(payload)))
        session.commit()


# ---- the helpers ----------------------------------------------------------------------------------------------------


def test_finite_number_accepts_only_finite_numbers():
    assert finite_number(1) == 1.0 and finite_number(-2.5) == -2.5 and finite_number(0) == 0.0
    for bad in (None, "1.2", "abc", True, False, [1], {}, NAN, INF, -INF):
        assert finite_number(bad) is None


def test_text_and_count_helpers():
    assert text_or_none("x") == "x" and text_or_none("") == ""
    assert text_or_none(5) is None and text_or_none(None) is None and text_or_none(["x"]) is None
    assert count_or_zero(3) == 3 and count_or_zero(3.0) == 3
    assert [count_or_zero(v) for v in ("3", None, -1, NAN, True, [2])] == [0, 0, 0, 0, 0, 0]


def test_clean_row_touches_only_listed_present_keys():
    row = {"a": "x", "b": 2, "c": "keep", "t": 5}
    out = clean_row(row, numbers=("a", "b", "missing"), texts=("t",))
    assert out == {"a": None, "b": 2.0, "c": "keep", "t": None}  # an absent key stays absent
    assert row == {"a": "x", "b": 2, "c": "keep", "t": 5}  # the input is not mutated


def test_first_row_ignores_a_non_dict_first_element():
    assert first_row(["a string"]) == {} and first_row([5]) == {} and first_row([None]) == {} and first_row([{"x": 1}]) == {"x": 1}
    assert first_row([]) == {} and first_row({"a": 1}) == {"a": 1} and first_row("junk") == {} and first_row(None) == {}


def test_the_delete_path_keeps_the_old_first():
    # purge_invalid_tickers reads "no companyName" as "confirmed-empty profile" and deletes: junk in the list must not look like that.
    # `_first` is unchanged (it hands the stray value back, so that caller's `.get` raises instead of purging).
    assert _first(["a string"]) == "a string" and _first([]) == {} and _first({"a": 1}) == {"a": 1}
    from pipeline.purge_invalid_tickers import find_invalid_tickers  # noqa: F401 -- imported to pin which helper it uses

    import inspect

    import pipeline.purge_invalid_tickers as purge

    assert "from helpers.first import _first" in inspect.getsource(purge)


# ---- ticker summary (profile, quote, price change, ratios TTM, growth, enterprise values) ------------------------------


def _bad_stock_answers():
    return {
        "get_profile": [
            {
                "companyName": 123,
                "exchange": ["NASDAQ"],
                "sector": {"x": 1},
                "industry": 5,
                "description": 9.5,
                "currency": 7,
                "beta": "1.2x",
                "mktCap": "N/A",
                "isEtf": False,
            }
        ],
        "get_quote": [
            {"price": "N/A", "change": "up", "changePercentage": [1], "marketCap": INF, "yearHigh": NAN, "yearLow": {"a": 1}}
        ],
        "get_price_change": [{"1M": "3.2", "6M": 12.5, "ytd": None, "1Y": [20], "5Y": "x", "10Y": True}],
        "get_ratios_ttm": [
            {"priceToEarningsGrowthRatioTTM": "n/a", "forwardPriceToEarningsGrowthRatioTTM": [3], "dividendYieldTTM": {"v": 1}, "netIncomePerShareTTM": "5", "priceToEarningsRatioTTM": INF}
        ],
        "get_financial_growth": [{"revenueGrowth": "8%", "netIncomeGrowth": NAN}],
        "get_enterprise_values": [{"enterpriseValue": "3.9T", "numberOfShares": [1]}],
        "get_income_statement": [{"reportedCurrency": 840}],
        "get_historical_price_eod": [{"date": "2026-10-01", "close": "x", "volume": "y"}, {"date": 5, "close": "1", "volume": 2}, "junk"],
    }


def test_summary_with_every_field_wrong_typed_degrades_each_to_none(install):
    install(_bad_stock_answers())
    out = asyncio.run(get_summary("AAPL"))
    for field in (
        "company_name", "exchange", "sector", "industry", "description", "price", "change", "change_percent", "market_cap", "enterprise_value",
        "beta", "peg_ratio", "forward_peg_ratio", "dividend_yield", "shares_outstanding", "avg_volume_30d", "avg_dollar_volume_20d",
        "perf_1m", "perf_1y", "perf_5y", "perf_10y", "perf_5y_vs_spy_pct", "week52_high", "week52_low", "revenue_growth_yoy",
        "net_income_growth_yoy", "pe_ratio", "reported_currency",
    ):
        assert getattr(out, field) is None, field
    assert out.quote_currency == "USD"  # a non-string currency reads as missing, so the documented default applies
    assert out.perf_5y_vs_spy_status == "no_data"
    assert out.perf_6m == 12.5  # the one clean figure next to the bad ones survives


def test_summary_endpoint_answers_200_not_500_for_a_wrong_typed_profile(install):
    install(_bad_stock_answers())
    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["beta"] is None and body["company_name"] is None and body["perf_6m"] == 12.5


@pytest.mark.parametrize("bad", ["abc", "N/A", "", [1], {"a": 1}, NAN, INF, True])
def test_summary_beta_wrong_type_is_none_and_the_valuation_still_runs(install, bad):
    install({"get_profile": [{**STOCK_PROFILE_CLEAN, "beta": bad}], "get_quote": [{"price": 190.5, "marketCap": 3e12}]})
    out = asyncio.run(get_summary("AAPL"))
    assert out.beta is None
    assert out.company_name == "Apple Inc." and out.price == 190.5 and out.market_cap == 3e12


def test_summary_clean_profile_is_unchanged(install):
    install({"get_profile": [STOCK_PROFILE_CLEAN], "get_quote": [{"price": 190.5, "marketCap": 3e12, "yearHigh": 200.0, "yearLow": 150.0}]})
    out = asyncio.run(get_summary("AAPL"))
    assert (out.beta, out.sector, out.exchange, out.week52_high, out.shares_outstanding) == (1.2, "Technology", "NASDAQ", 200.0, 3e12 / 190.5)


def test_summary_etf_profile_with_a_string_beta(install):
    install({"get_profile": [{"companyName": "SPDR Gold", "exchange": "AMEX", "isEtf": True, "beta": "0.45"}], "get_quote": [{"price": "382"}]})
    out = asyncio.run(get_summary("GLD"))
    assert out.is_etf and out.beta is None and out.price is None and out.company_name == "SPDR Gold"


def test_shares_outstanding_helper_falls_back_when_the_quote_is_wrong_typed():
    from helpers.shares import compute_shares_outstanding

    assert compute_shares_outstanding({"marketCap": "big", "price": 10}, [{"weightedAverageShsOutDil": 5}])[0] == 5
    assert compute_shares_outstanding({"marketCap": 100, "price": "x"}, [{"weightedAverageShsOutDil": "many"}]) == (None, None)
    assert compute_shares_outstanding({}, ["junk"]) == (None, None)


# ---- Ratios tab ----------------------------------------------------------------------------------------------------------


def test_ratios_tab_with_wrong_typed_cells(install):
    install(
        {
            "get_key_metrics": [{"fiscalYear": 2024, "evToSales": "n/a", "returnOnEquity": "0.3", "grahamNumber": [1]}, {"fiscalYear": ["x"], "date": 20240101, "evToSales": 2.5}, "junk"],
            "get_key_metrics_ttm": [{"evToSalesTTM": {"a": 1}, "returnOnEquityTTM": NAN, "earningsYieldTTM": 0.05}],
            "get_ratios": [{"fiscalYear": "2024", "priceToEarningsRatio": "x", "grossProfitMargin": "0.4", "reportedCurrency": 840}, {"date": "2023-12-31", "priceToEarningsRatio": 20.0, "grossProfitMargin": 0.5}],
            "get_ratios_ttm": [{"priceToEarningsRatioTTM": INF, "grossProfitMarginTTM": "high", "netProfitMarginTTM": 0.2}],
            "get_balance_sheet_statement": [{"date": 20250101}],
        }
    )
    out = asyncio.run(get_ratios_data("AAPL"))
    assert out.periods[-1] == "TTM"  # the quarter date was not text, so the undated label
    assert out.reported_currency is None
    cells = {item.label: item.values for group in out.groups for item in group.items}
    # Oldest first: 2023 (clean), 2024 ("x" / "0.4" are text -> None), then the TTM column (INF / "high" -> None).
    assert cells["P/E"][-3:] == [20.0, None, None]
    assert cells["Gross Margin"][-3:] == [50.0, None, None]
    assert cells["Net Margin"][-1] == pytest.approx(20.0)
    assert cells["Earnings Yield"][-1] == pytest.approx(5.0)
    assert all(v is None or isinstance(v, float) for values in cells.values() for v in values)
    assert out.periods[-3:] == ["—", "2024", "TTM"]  # a list-typed fiscalYear with a numeric date has no label


def test_ratios_endpoint_does_not_500(install):
    install({"get_key_metrics": [{"fiscalYear": 2024, "evToSales": "x"}], "get_ratios": [{"priceToEarningsRatio": [1]}], "get_ratios_ttm": [["junk"]]})
    with TestClient(main.app) as client:
        assert client.get("/api/tickers/AAPL/ratios").status_code == 200


# ---- Analyst ratings tab -------------------------------------------------------------------------------------------------


def test_analyst_ratings_with_wrong_typed_fields(install):
    recent = (date.today() - timedelta(days=30)).isoformat()
    install(
        {
            "get_grades_consensus": [{"consensus": 5, "strongBuy": "10", "buy": 7, "hold": None, "sell": [1], "strongSell": NAN}],
            "get_price_target_consensus": [{"targetConsensus": "250", "targetHigh": INF, "targetLow": 150, "targetMedian": {"a": 1}}],
            "get_price_target_summary": [{"lastMonthCount": "2", "lastMonthAvgPriceTarget": 200, "lastQuarterCount": 3, "lastQuarterAvgPriceTarget": "x", "lastYearCount": [1], "allTimeCount": 4, "allTimeAvgPriceTarget": NAN}],
            "get_grades_historical": [
                {"date": recent, "analystRatingsStrongBuy": 5, "analystRatingsBuy": "3", "analystRatingsHold": 2},
                {"date": 20240101, "analystRatingsBuy": 4},
                {"date": "not a date", "analystRatingsBuy": 4},
                "junk",
            ],
            "get_quote": [{"price": "190"}],
        }
    )
    out = asyncio.run(get_analyst_ratings_data("AAPL"))
    assert out.banner.rating == "N/A"  # a non-string consensus label
    assert (out.banner.analyst_count, out.banner.buy_count) == (7, 7)  # only the clean `buy` count (7) counts
    assert out.price_target.current_price is None and out.price_target.target_consensus is None and out.price_target.upside_pct is None
    assert out.price_target.target_high is None and out.price_target.target_low == 150 and out.price_target.target_median is None
    buckets = {b.label: b for b in out.price_target_by_recency}
    assert buckets["Last Month"].analyst_count == 0 and buckets["Last Month"].avg_price_target is None
    assert buckets["Last Quarter"].analyst_count == 3 and buckets["Last Quarter"].avg_price_target is None
    assert buckets["All Time"].analyst_count == 4 and buckets["All Time"].avg_price_target is None
    assert [p.date for p in out.history] == [recent]  # the dated, parseable row only
    assert out.history[0].buy_pct == pytest.approx(5 / 7 * 100)  # 5 of (5 + 0 + 2): the text "3" counts as 0


def test_analyst_ratings_endpoint_does_not_500(install):
    install({"get_grades_consensus": [{"strongBuy": "x"}], "get_price_target_consensus": [{"targetConsensus": "x"}], "get_quote": [{"price": "x"}]})
    with TestClient(main.app) as client:
        assert client.get("/api/tickers/AAPL/analyst-ratings").status_code == 200


# ---- ETF overview ---------------------------------------------------------------------------------------------------------


def test_etf_overview_with_wrong_typed_and_non_finite_fields(install):
    engine = install(
        {
            "get_etf_info": [
                {
                    "name": 5, "etfCompany": ["SPDR"], "assetClass": "Equity", "expenseRatio": INF, "assetsUnderManagement": NAN,
                    "holdingsCount": INF, "nav": "n/a", "navCurrency": 840, "avgVolume": [1], "inceptionDate": 20200101, "domicile": None,
                    "description": {"a": 1}, "website": True,
                    "sectorsList": [{"industry": "Technology", "exposure": NAN}, {"industry": "Energy", "exposure": INF}, {"industry": 7, "exposure": 5}, {"industry": "Health", "exposure": "12.5"}, "junk"],
                }
            ],
        }
    )
    _cache(engine, "XLK", "profile", "latest", [{"beta": "high", "lastDividend": INF}])
    _cache(engine, "XLK", "quote", "latest", [{"price": "x", "yearLow": NAN, "yearHigh": {"a": 1}}])
    out = asyncio.run(get_etf_overview("XLK"))
    assert out.status == "ok"
    for field in ("name", "issuer", "expense_ratio", "assets_under_management", "holdings_count", "nav", "nav_currency", "avg_volume", "inception_date", "domicile", "description", "website"):
        assert getattr(out, field) is None, field
    assert [(w.sector, w.weight) for w in out.sector_weights] == [("Health", 12.5)]
    assert out.asset_class == "Equity"
    json.dumps(out.model_dump(mode="json"), allow_nan=False)  # the answer itself can be serialised


def test_etf_overview_endpoint_does_not_500(install):
    install({"get_etf_info": [{"name": "X", "expenseRatio": INF, "sectorsList": "junk"}], "get_profile": [{"isEtf": True}]})
    with TestClient(main.app) as client:
        assert client.get("/api/tickers/XLK/etf-overview").status_code == 200


# ---- Chart ------------------------------------------------------------------------------------------------------------------


def _rows(n=30):
    day = date.today()
    out = []
    while len(out) < n:
        if day.weekday() < 5:
            out.append({"date": day.isoformat(), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0 + len(out) * 0.1, "volume": 1000})
        day -= timedelta(days=1)
    return out


def _chart(monkeypatch, rows):
    async def fake(ticker, from_date, to_date, group="daily_prices"):
        return rows

    async def none(*_a, **_k):
        return None

    async def no_events(ticker):
        return ChartEvents()

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", fake)
    monkeypatch.setattr(chart_data, "fetch_chart_events", no_events)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", none)
    monkeypatch.setattr(chart_data, "get_warren_signal_data", none)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: None)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(chart_data, "engine", eng)
    return asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))


def test_chart_with_wrong_typed_bar_cells_drops_or_fills_them(monkeypatch):
    rows = _rows()
    rows[3]["close"] = "N/A"  # no usable close: the bar is dropped
    rows[5]["open"] = "x"  # a missing open takes the close
    rows[6]["high"] = NAN
    rows[7]["low"] = {"a": 1}
    rows[8]["volume"] = [1]
    rows[9]["close"] = INF
    out = _chart(monkeypatch, rows)
    assert out.chart_available
    assert len(out.bars) == len(rows) - 2  # the two rows with an unusable close are gone
    for bar in out.bars:
        assert all(math.isfinite(v) for v in (bar.open, bar.high, bar.low, bar.close))
    json.dumps(out.model_dump(mode="json"), allow_nan=False)


def test_chart_with_a_malformed_date_degrades_to_an_empty_chart(monkeypatch):
    rows = _rows()
    rows[2]["date"] = {"not": "a date"}
    out = _chart(monkeypatch, rows)
    assert out.chart_available is False and out.bars == []


def test_chart_clean_rows_are_unchanged(monkeypatch):
    out = _chart(monkeypatch, _rows())
    assert out.chart_available and len(out.bars) == 30
