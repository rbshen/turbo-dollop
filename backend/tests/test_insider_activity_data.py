import asyncio
import json
from datetime import date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import clients.fmp_client as fmp_client_module
import core.main as main
import data.insider_activity_data as insider_data
from clients.fmp_client import FMPClient
from core.config import settings
from core.models import FundamentalsCache
from data.insider_activity_data import (
    build_summary,
    classify_sentiment,
    find_cluster_buy,
    get_insider_activity_data,
    normalize_quarterly_stats,
    normalize_transactions,
)


def _fresh_engine(monkeypatch):
    # StaticPool so the endpoint test's TestClient thread shares the same
    # in-memory database (see test_liquidity_zone_endpoint.py).
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(insider_data, "engine", test_engine)
    return test_engine


def _row(
    tx_type="P-Purchase",
    tx_date="2026-09-01",
    cik="0001",
    name="Jane Doe",
    price=10.0,
    shares=100,
    **extra,
) -> dict:
    return {
        "symbol": "TEST",
        "filingDate": "2026-09-03",
        "transactionDate": tx_date,
        "reportingCik": cik,
        "reportingName": name,
        "typeOfOwner": "officer: CFO",
        "transactionType": tx_type,
        "directOrIndirect": "D",
        "securitiesTransacted": shares,
        "price": price,
        "secFilingUrl": "https://www.sec.gov/x",
        **extra,
    }


def _stat(year, quarter, purchases=0, sales=0, acquired=0, disposed=0) -> dict:
    return {
        "symbol": "TEST",
        "year": year,
        "quarter": quarter,
        "totalPurchases": purchases,
        "totalSales": sales,
        "totalAcquired": acquired,
        "totalDisposed": disposed,
    }


def _patch_fmp(monkeypatch, search=None, statistics=None):
    calls = {"search": 0, "statistics": 0}

    async def fake_search(ticker, limit=100):
        calls["search"] += 1
        return search if search is not None else []

    async def fake_statistics(ticker):
        calls["statistics"] += 1
        return statistics if statistics is not None else []

    monkeypatch.setattr(insider_data.fmp_client, "get_insider_trading_search", fake_search)
    monkeypatch.setattr(insider_data.fmp_client, "get_insider_trading_statistics", fake_statistics)
    return calls


def _seed_cache(engine, statement_type, payload, fetched_at):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker="TEST", statement_type=statement_type, period="latest", fetched_at=fetched_at, raw_json=json.dumps(payload)
            )
        )
        session.commit()


# --- normalization ---------------------------------------------------------


def test_empty_transaction_type_rows_are_dropped():
    rows = [_row(tx_type=""), _row(tx_type="   "), {**_row(), "transactionType": None}, _row(tx_type="P-Purchase")]
    result = normalize_transactions(rows)
    assert [t.kind for t in result] == ["open_market_buy"]


@pytest.mark.parametrize(
    "tx_type,kind,label",
    [
        ("P-Purchase", "open_market_buy", "Open-market buy"),
        ("S-Sale", "open_market_sale", "Open-market sale"),
        ("M-Exempt", "option_exercise", "Option exercise"),
        ("A-Award", "award", "Grant / award"),
        ("G-Gift", "gift", "Gift"),
        ("F-InKind", "other", "Tax withholding"),
        ("Z-Weird", "other", "Trust deposit / withdrawal"),
        ("Q-SomethingNew", "other", "SomethingNew"),
    ],
)
def test_transaction_types_are_classified_and_labelled(tx_type, kind, label):
    (result,) = normalize_transactions([_row(tx_type=tx_type)])
    assert (result.kind, result.type_label) == (kind, label)


def test_classification_keys_on_the_code_not_the_label_text():
    # "S-Sale+OE" style variants and lowercase must still land on the code.
    kinds = [normalize_transactions([_row(tx_type=t)])[0].kind for t in ("S-Sale+OE", "p-purchase", "P")]
    assert kinds == ["open_market_sale", "open_market_buy", "open_market_buy"]


def test_zero_price_non_open_market_has_no_cash_value():
    award, gift, exercise = normalize_transactions(
        [_row(tx_type="A-Award", price=0), _row(tx_type="G-Gift", price=0), _row(tx_type="M-Exempt", price=0)]
    )
    for t in (award, gift, exercise):
        assert t.has_cash_value is False
        assert t.dollar_value is None
        assert t.price is None


def test_priced_non_open_market_row_has_cash_value():
    (exercise,) = normalize_transactions([_row(tx_type="M-Exempt", price=12.5, shares=200)])
    assert exercise.has_cash_value is True
    assert exercise.dollar_value == 2500.0


def test_open_market_row_always_has_cash_value_even_at_zero_price():
    (buy,) = normalize_transactions([_row(tx_type="P-Purchase", price=0, shares=50)])
    assert buy.has_cash_value is True
    assert buy.dollar_value == 0.0


def test_dollar_value_is_price_times_shares():
    (sale,) = normalize_transactions([_row(tx_type="S-Sale", price=150.25, shares=1000)])
    assert sale.dollar_value == pytest.approx(150250.0)


def test_null_price_and_shares_do_not_crash():
    (t,) = normalize_transactions([_row(tx_type="A-Award", price=None, shares=None)])
    assert t.shares == 0.0
    assert t.has_cash_value is False


def test_ownership_role_and_link_fields():
    direct, indirect, unknown = normalize_transactions(
        [
            _row(tx_date="2026-09-03", directOrIndirect="D"),
            _row(tx_date="2026-09-02", directOrIndirect="I"),
            _row(tx_date="2026-09-01", directOrIndirect=None),
        ]
    )
    assert (direct.ownership, indirect.ownership, unknown.ownership) == ("direct", "indirect", None)
    assert direct.insider_role == "officer: CFO"
    assert direct.sec_filing_url == "https://www.sec.gov/x"


def test_falls_back_to_url_field_when_secfilingurl_absent():
    row = _row()
    del row["secFilingUrl"]
    row["url"] = "https://www.sec.gov/fallback"
    assert normalize_transactions([row])[0].sec_filing_url == "https://www.sec.gov/fallback"


def test_rows_without_a_parseable_transaction_date_are_dropped_and_rest_sorted_newest_first():
    result = normalize_transactions(
        [_row(tx_date="2026-08-01"), _row(tx_date=None), _row(tx_date="garbage"), _row(tx_date="2026-09-01")]
    )
    assert [t.transaction_date for t in result] == [date(2026, 9, 1), date(2026, 8, 1)]


def test_non_dict_rows_are_ignored():
    assert normalize_transactions(["oops", None, 3]) == []


# --- quarterly stats & summary ---------------------------------------------


def test_quarterly_stats_are_sorted_oldest_first_and_bad_rows_dropped():
    result = normalize_quarterly_stats(
        [_stat(2026, 2, purchases=1), _stat(2025, 4), {"year": 2026, "quarter": 9}, {"year": None, "quarter": 1}, _stat(2026, 1)]
    )
    assert [(s.year, s.quarter) for s in result] == [(2025, 4), (2026, 1), (2026, 2)]


def test_window_sums_only_the_two_most_recent_quarters_regardless_of_input_order():
    stats = normalize_quarterly_stats(
        [
            _stat(2026, 2, purchases=5, sales=1, acquired=500, disposed=100),
            _stat(2025, 3, purchases=1000, sales=1000, acquired=1000, disposed=1000),  # outside the window
            _stat(2026, 1, purchases=3, sales=2, acquired=300, disposed=200),
        ]
    )
    summary = build_summary([], stats)
    assert summary.quarters_in_window == 2
    assert (summary.total_purchases, summary.total_sales) == (8, 3)
    assert (summary.total_acquired, summary.total_disposed) == (800, 300)


def test_window_with_a_single_quarter_still_sums_it():
    summary = build_summary([], normalize_quarterly_stats([_stat(2026, 2, purchases=4, sales=1)]))
    assert summary.quarters_in_window == 1
    assert summary.total_purchases == 4


@pytest.mark.parametrize(
    "purchases,sales,expected",
    [(5, 1, "net_buying"), (1, 5, "net_selling"), (0, 0, "no_activity"), (3, 3, "mixed")],
)
def test_sentiment_states(purchases, sales, expected):
    assert classify_sentiment(purchases, sales) == expected


def test_summary_with_no_data_reads_no_activity():
    summary = build_summary([], [])
    assert summary.sentiment == "no_activity"
    assert summary.quarters_in_window == 0
    assert summary.cluster_buy is None and summary.notable_buy is None and summary.notable_sale is None


def test_open_market_counts_cover_only_the_stats_window():
    stats = normalize_quarterly_stats([_stat(2026, 1), _stat(2026, 2)])  # window starts 2026-01-01
    transactions = normalize_transactions(
        [
            _row(tx_date="2026-08-01", tx_type="P-Purchase"),
            _row(tx_date="2026-02-01", tx_type="S-Sale"),
            _row(tx_date="2026-02-02", tx_type="S-Sale"),
            _row(tx_date="2025-12-31", tx_type="S-Sale"),  # before the window
            _row(tx_date="2026-03-01", tx_type="A-Award"),  # not open market
        ]
    )
    summary = build_summary(transactions, stats)
    assert (summary.open_market_buy_count, summary.open_market_sale_count) == (1, 2)


def test_open_market_counts_fall_back_to_every_transaction_without_stats():
    transactions = normalize_transactions([_row(tx_date="2020-01-01", tx_type="S-Sale"), _row(tx_type="P-Purchase")])
    summary = build_summary(transactions, [])
    assert (summary.open_market_buy_count, summary.open_market_sale_count) == (1, 1)


# --- notable trades ---------------------------------------------------------


def test_notable_trades_are_the_largest_open_market_buy_and_sale_by_dollar_value():
    transactions = normalize_transactions(
        [
            _row(tx_type="P-Purchase", price=10, shares=100, name="small buy"),
            _row(tx_type="P-Purchase", price=10, shares=900, name="big buy"),
            _row(tx_type="S-Sale", price=50, shares=10, name="small sale"),
            _row(tx_type="S-Sale", price=50, shares=5000, name="big sale"),
            _row(tx_type="M-Exempt", price=1000, shares=1_000_000, name="huge exercise"),  # never notable
        ]
    )
    summary = build_summary(transactions, [])
    assert summary.notable_buy.insider_name == "big buy"
    assert summary.notable_sale.insider_name == "big sale"


def test_notable_trade_is_none_when_there_is_no_positive_value_open_market_trade():
    transactions = normalize_transactions([_row(tx_type="P-Purchase", price=0), _row(tx_type="A-Award", price=0)])
    summary = build_summary(transactions, [])
    assert summary.notable_buy is None
    assert summary.notable_sale is None


# --- cluster buy ------------------------------------------------------------


def _buys(*specs):
    """specs: (date, cik) tuples."""
    return normalize_transactions([_row(tx_date=d, cik=c, name=f"insider {c}") for d, c in specs])


def test_three_distinct_insiders_within_90_days_is_a_cluster():
    cluster = find_cluster_buy(_buys(("2026-07-01", "1"), ("2026-08-01", "2"), ("2026-09-01", "3")))
    assert cluster is not None
    assert cluster.insider_count == 3
    assert cluster.window_start == date(2026, 7, 1)
    assert cluster.window_end == date(2026, 9, 1)


def test_two_insiders_is_not_a_cluster():
    assert find_cluster_buy(_buys(("2026-08-01", "1"), ("2026-08-02", "2"))) is None


def test_repeat_buys_by_one_insider_count_once():
    assert find_cluster_buy(_buys(("2026-08-01", "1"), ("2026-08-02", "1"), ("2026-08-03", "1"), ("2026-08-04", "2"))) is None


def test_buys_spread_beyond_90_days_are_not_a_cluster():
    assert find_cluster_buy(_buys(("2026-01-01", "1"), ("2026-06-01", "2"), ("2026-09-01", "3"))) is None


def test_90_day_window_edge_is_inclusive():
    start = date(2026, 6, 1)
    inside = _buys((start.isoformat(), "1"), ((start + timedelta(days=45)).isoformat(), "2"), ((start + timedelta(days=90)).isoformat(), "3"))
    outside = _buys((start.isoformat(), "1"), ((start + timedelta(days=45)).isoformat(), "2"), ((start + timedelta(days=91)).isoformat(), "3"))
    assert find_cluster_buy(inside) is not None
    assert find_cluster_buy(outside) is None


def test_sales_and_other_types_do_not_count_toward_a_cluster():
    transactions = normalize_transactions(
        [
            _row(tx_date="2026-08-01", cik="1", tx_type="P-Purchase"),
            _row(tx_date="2026-08-02", cik="2", tx_type="S-Sale"),
            _row(tx_date="2026-08-03", cik="3", tx_type="A-Award"),
        ]
    )
    assert find_cluster_buy(transactions) is None


def test_cluster_reports_the_most_recent_qualifying_window():
    old = [("2024-01-01", "1"), ("2024-01-10", "2"), ("2024-01-20", "3")]
    recent = [("2026-08-01", "4"), ("2026-08-05", "5"), ("2026-08-09", "6"), ("2026-08-12", "7")]
    cluster = find_cluster_buy(_buys(*old, *recent))
    assert cluster.window_end == date(2026, 8, 12)
    assert cluster.insider_count == 4


def test_cluster_falls_back_to_name_when_cik_missing():
    transactions = normalize_transactions(
        [_row(tx_date=f"2026-08-0{i}", cik=None, name=f"person {i}") for i in (1, 2, 3)]
    )
    assert find_cluster_buy(transactions) is not None


# --- get_insider_activity_data: caching / as_of / FMP-disabled ---------------


def test_fresh_fetch_populates_everything_and_as_of(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_fmp(
        monkeypatch,
        search=[_row(), _row(tx_type="", tx_date="2026-09-02")],
        statistics=[_stat(2026, 2, purchases=2, sales=1)],
    )

    result = asyncio.run(get_insider_activity_data("test"))

    assert result.ticker == "TEST"
    assert result.has_data is True
    assert len(result.transactions) == 1
    assert result.summary.sentiment == "net_buying"
    assert result.as_of is not None
    assert calls == {"search": 1, "statistics": 1}


def test_cached_and_genuinely_empty_has_as_of_but_no_data(monkeypatch):
    # HK/France/quiet tickers: FMP answers 200 with [] -- a real, cached "no data".
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, search=[], statistics=[])

    result = asyncio.run(get_insider_activity_data("TEST"))

    assert result.has_data is False
    assert result.as_of is not None


def test_cold_miss_with_fmp_disabled_has_no_as_of(monkeypatch):
    _fresh_engine(monkeypatch)
    monkeypatch.setattr(settings, "fmp_enabled", False)
    calls = _patch_fmp(monkeypatch, search=[_row()])

    result = asyncio.run(get_insider_activity_data("TEST"))

    assert result.has_data is False
    assert result.as_of is None
    assert result.transactions == [] and result.quarterly_stats == []
    assert calls == {"search": 0, "statistics": 0}  # never attempted a live call


def test_cache_only_cold_miss_has_no_as_of_and_never_calls_fmp(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_fmp(monkeypatch, search=[_row()])

    result = asyncio.run(get_insider_activity_data("TEST", cache_only=True))

    assert result.as_of is None
    assert result.has_data is False
    assert calls == {"search": 0, "statistics": 0}


def test_fetch_failure_leaves_no_as_of_so_it_reads_as_not_cached(monkeypatch):
    # e.g. the plan doesn't cover the endpoint (HTTP 402/403) -- safe_fetch
    # swallows it, nothing is cached, and it must NOT read as "genuinely empty".
    _fresh_engine(monkeypatch)

    async def failing(*args, **kwargs):
        raise httpx.HTTPStatusError("402", request=httpx.Request("GET", "http://x"), response=httpx.Response(402))

    monkeypatch.setattr(insider_data.fmp_client, "get_insider_trading_search", failing)
    monkeypatch.setattr(insider_data.fmp_client, "get_insider_trading_statistics", failing)

    result = asyncio.run(get_insider_activity_data("TEST"))

    assert result.has_data is False
    assert result.as_of is None


def test_fmp_disabled_serves_a_stale_cached_row_with_its_original_as_of(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(settings, "fmp_enabled", False)
    long_ago = datetime.now() - timedelta(days=30)
    _seed_cache(engine, "insider_trading_search", [_row()], long_ago)
    _seed_cache(engine, "insider_trading_statistics", [_stat(2026, 2, purchases=1)], long_ago)

    result = asyncio.run(get_insider_activity_data("TEST"))

    assert result.has_data is True
    assert result.as_of == long_ago


def test_uses_the_dedicated_one_day_window_not_the_shared_seven_day_one(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    assert settings.insider_staleness_days == 1
    _seed_cache(engine, "insider_trading_search", [_row()], datetime.now() - timedelta(days=2))
    _seed_cache(engine, "insider_trading_statistics", [], datetime.now() - timedelta(days=2))
    calls = _patch_fmp(monkeypatch, search=[_row(), _row(tx_date="2026-09-02")], statistics=[])

    result = asyncio.run(get_insider_activity_data("TEST"))

    assert calls["search"] == 1  # 2-day-old row is stale under 1 day, though fresh under the shared 7
    assert len(result.transactions) == 2


def test_a_fresh_cached_row_is_not_refetched(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime.now()
    _seed_cache(engine, "insider_trading_search", [_row()], now)
    _seed_cache(engine, "insider_trading_statistics", [], now)
    calls = _patch_fmp(monkeypatch)

    result = asyncio.run(get_insider_activity_data("TEST"))

    assert calls == {"search": 0, "statistics": 0}
    assert len(result.transactions) == 1


def test_non_list_payload_is_treated_as_empty(monkeypatch):
    # FMP sometimes answers 200 with an error dict instead of a list.
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, search={"Error Message": "nope"}, statistics={"Error Message": "nope"})

    result = asyncio.run(get_insider_activity_data("TEST"))

    assert result.has_data is False
    assert result.as_of is not None  # the (bad) response was still cached


# --- endpoint ---------------------------------------------------------------


def test_endpoint_returns_the_normalized_shape(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, search=[_row(tx_type="S-Sale", price=20, shares=10)], statistics=[_stat(2026, 2, sales=1)])

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/TEST/insider-activity")

    assert response.status_code == 200
    body = response.json()
    assert body["has_data"] is True
    assert body["transactions"][0]["kind"] == "open_market_sale"
    assert body["transactions"][0]["dollar_value"] == 200.0
    assert body["summary"]["sentiment"] == "net_selling"
    assert body["as_of"] is not None


def test_endpoint_reports_not_cached_yet_when_fmp_is_paused(monkeypatch):
    _fresh_engine(monkeypatch)
    monkeypatch.setattr(settings, "fmp_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/TEST/insider-activity")

    assert response.status_code == 200
    body = response.json()
    assert body["has_data"] is False
    assert body["as_of"] is None


# --- FMPClient wrappers -----------------------------------------------------


def test_fmp_client_wrappers_hit_the_stable_insider_endpoints(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(fmp_client_module.httpx, "AsyncClient", factory)
    client = FMPClient(api_key="k")

    async def run():
        await client.get_insider_trading_search("AAPL")
        await client.get_insider_trading_search("AAPL", limit=25)
        await client.get_insider_trading_statistics("AAPL")

    asyncio.run(run())

    assert seen[0][0] == "/stable/insider-trading/search"
    assert seen[0][1]["symbol"] == "AAPL" and seen[0][1]["limit"] == "100"
    assert seen[1][1]["limit"] == "25"
    assert seen[2][0] == "/stable/insider-trading/statistics"
    assert seen[2][1]["symbol"] == "AAPL"
