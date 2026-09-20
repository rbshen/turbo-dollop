import asyncio
import json
from datetime import date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.fmp_client as fmp_client_module
import core.main as main
import data.insider_activity_data as insider_data
from clients.fmp_client import FMPClient
from core.config import settings
from core.models import FundamentalsCache
from data.insider_activity_data import (
    build_quarterly_activity,
    build_summary,
    classify_sentiment,
    find_cluster_buy,
    get_insider_activity_data,
    normalize_quarterly_stats,
    normalize_transactions,
)


@pytest.fixture(autouse=True)
def _insider_activity_enabled(monkeypatch):
    """The feature is shelved behind Settings.insider_activity_enabled
    (default False, pinned by conftest's _default_flags_enabled). Every test
    in this module exercises the feature itself, so it turns the flag on
    explicitly; the disabled-state tests at the bottom set it back to
    False -- same object, last write wins."""
    monkeypatch.setattr(insider_data.settings, "insider_activity_enabled", True)


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

    async def fake_search(ticker, limit=100, page=0):
        calls["search"] += 1
        rows = search if search is not None else []
        return rows[page * limit : (page + 1) * limit] if isinstance(rows, list) else rows

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


# --- one name / role per CIK ------------------------------------------------


def test_every_row_for_a_cik_takes_the_most_recent_rows_role():
    txs = normalize_transactions(
        [
            _row(cik="1", tx_date="2026-01-05", typeOfOwner="officer: Chief Financial Officer"),
            _row(cik="1", tx_date="2026-09-05", typeOfOwner="director, officer: Chief Executive Officer"),
            _row(cik="1", tx_date="2026-05-05", typeOfOwner="officer: VP Finance"),
        ]
    )
    assert {t.insider_role for t in txs} == {"director, officer: Chief Executive Officer"}


def test_a_blank_latest_role_falls_back_to_the_most_recent_non_blank_one():
    txs = normalize_transactions(
        [
            _row(cik="1", tx_date="2026-09-05", typeOfOwner=""),
            _row(cik="1", tx_date="2026-06-05", typeOfOwner="   "),
            _row(cik="1", tx_date="2026-03-05", typeOfOwner="officer: Chief Legal Officer"),
            _row(cik="1", tx_date="2026-01-05", typeOfOwner="officer: General Counsel"),
        ]
    )
    assert {t.insider_role for t in txs} == {"officer: Chief Legal Officer"}


def test_a_cik_whose_every_role_is_blank_keeps_none():
    txs = normalize_transactions([_row(cik="1", typeOfOwner=""), _row(cik="1", typeOfOwner=None)])
    assert {t.insider_role for t in txs} == {None}


def test_roles_are_unified_per_cik_not_across_ciks():
    txs = normalize_transactions(
        [
            _row(cik="1", typeOfOwner="director"),
            _row(cik="2", typeOfOwner="officer: CFO"),
        ]
    )
    assert {t.insider_cik: t.insider_role for t in txs} == {"1": "director", "2": "officer: CFO"}


def test_name_variants_of_one_cik_collapse_to_the_most_recent_spelling():
    txs = normalize_transactions(
        [
            _row(cik="1198046", tx_date="2026-08-01", name="Hennessy John L."),
            _row(cik="1198046", tx_date="2026-03-01", name="HENNESSY JOHN L"),
            _row(cik="1198046", tx_date="2025-11-01", name="HENNESSY JOHN L"),
        ]
    )
    assert {t.insider_name for t in txs} == {"Hennessy John L."}


def test_name_uses_the_latest_spelling_even_when_it_is_the_all_caps_one():
    txs = normalize_transactions(
        [
            _row(cik="1", tx_date="2026-08-01", name="HENNESSY JOHN L"),
            _row(cik="1", tx_date="2026-03-01", name="Hennessy John L."),
        ]
    )
    assert {t.insider_name for t in txs} == {"HENNESSY JOHN L"}


def test_a_missing_latest_name_does_not_replace_a_real_one_with_unknown():
    txs = normalize_transactions(
        [
            _row(cik="1", tx_date="2026-08-01", name=""),
            _row(cik="1", tx_date="2026-03-01", name="Jane Doe"),
        ]
    )
    assert {t.insider_name for t in txs} == {"Jane Doe"}


def test_rows_without_a_cik_are_left_untouched():
    txs = normalize_transactions(
        [
            _row(cik=None, tx_date="2026-08-01", name="A. Person", typeOfOwner="director"),
            _row(cik=None, tx_date="2026-03-01", name="a person", typeOfOwner="officer: CFO"),
        ]
    )
    assert sorted((t.insider_name, t.insider_role) for t in txs) == [("A. Person", "director"), ("a person", "officer: CFO")]


# --- notable trades ---------------------------------------------------------


def test_notable_trades_are_the_largest_open_market_buy_and_sale_by_dollar_value():
    transactions = normalize_transactions(
        [
            _row(tx_type="P-Purchase", price=10, shares=100, name="small buy", cik="1"),
            _row(tx_type="P-Purchase", price=10, shares=900, name="big buy", cik="2"),
            _row(tx_type="S-Sale", price=50, shares=10, name="small sale", cik="3"),
            _row(tx_type="S-Sale", price=50, shares=5000, name="big sale", cik="4"),
            _row(tx_type="M-Exempt", price=1000, shares=1_000_000, name="huge exercise", cik="5"),  # never notable
        ]
    )
    summary = build_summary(transactions, [])
    assert summary.notable_buy.insider_name == "big buy"
    assert summary.notable_sale.insider_name == "big sale"


def test_same_day_lines_by_one_insider_are_merged_into_one_notable_trade():
    # One real sale split across price bands: the biggest single LINE ($6,000)
    # is smaller than a different insider's one-line $9,000 sale, but the
    # merged total ($14,000 across 3 fills) is the largest trade.
    transactions = normalize_transactions(
        [
            _row(tx_type="S-Sale", cik="1", name="splitter", price=10, shares=400),
            _row(tx_type="S-Sale", cik="1", name="splitter", price=15, shares=400),
            _row(tx_type="S-Sale", cik="1", name="splitter", price=20, shares=200),
            _row(tx_type="S-Sale", cik="2", name="one liner", price=90, shares=100),
        ]
    )
    sale = build_summary(transactions, []).notable_sale
    assert sale.insider_name == "splitter"
    assert sale.fill_count == 3
    assert sale.shares == 1000
    assert sale.dollar_value == 400 * 10 + 400 * 15 + 200 * 20
    assert sale.price == pytest.approx(14.0)  # share-weighted average
    assert sale.has_cash_value is True


def test_a_single_line_notable_trade_has_a_fill_count_of_one_and_is_unchanged():
    transactions = normalize_transactions([_row(tx_type="P-Purchase", cik="1", price=10, shares=100)])
    buy = build_summary(transactions, []).notable_buy
    assert buy.fill_count == 1
    assert buy.shares == 100 and buy.dollar_value == 1000 and buy.price == 10


def test_lines_on_different_days_are_never_merged():
    # Weekly 10b5-1 style sales stay distinct events: no multi-day windowing.
    transactions = normalize_transactions(
        [_row(tx_type="S-Sale", cik="1", tx_date=f"2026-09-0{d}", price=10, shares=100) for d in (1, 2, 3)]
    )
    sale = build_summary(transactions, []).notable_sale
    assert sale.fill_count == 1
    assert sale.dollar_value == 1000


def test_same_day_lines_by_different_insiders_are_not_merged():
    transactions = normalize_transactions(
        [
            _row(tx_type="S-Sale", cik="1", name="a", price=10, shares=100),
            _row(tx_type="S-Sale", cik="2", name="b", price=10, shares=100),
        ]
    )
    assert build_summary(transactions, []).notable_sale.fill_count == 1


def test_buys_and_sales_by_one_insider_on_one_day_are_grouped_separately():
    transactions = normalize_transactions(
        [
            _row(tx_type="S-Sale", cik="1", price=10, shares=100),
            _row(tx_type="P-Purchase", cik="1", price=10, shares=300),
        ]
    )
    summary = build_summary(transactions, [])
    assert (summary.notable_sale.shares, summary.notable_sale.fill_count) == (100, 1)
    assert (summary.notable_buy.shares, summary.notable_buy.fill_count) == (300, 1)


def test_merged_notable_trade_takes_identity_fields_from_its_largest_line():
    transactions = normalize_transactions(
        [
            _row(tx_type="S-Sale", cik="1", price=10, shares=10, secFilingUrl="https://sec/small"),
            _row(tx_type="S-Sale", cik="1", price=10, shares=900, secFilingUrl="https://sec/big"),
        ]
    )
    sale = build_summary(transactions, []).notable_sale
    assert sale.sec_filing_url == "https://sec/big"
    assert sale.fill_count == 2


def test_merged_notable_trade_with_mixed_ownership_reports_none():
    transactions = normalize_transactions(
        [
            _row(tx_type="S-Sale", cik="1", directOrIndirect="D"),
            _row(tx_type="S-Sale", cik="1", directOrIndirect="I"),
        ]
    )
    assert build_summary(transactions, []).notable_sale.ownership is None


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


# --- quarterly chart series -------------------------------------------------


def _q(txs, frontier=None):
    series, truncated = build_quarterly_activity(normalize_transactions(txs), frontier)
    return {(q.year, q.quarter): q for q in series}, truncated


def test_open_market_and_all_types_totals_are_bucketed_by_transaction_date():
    quarters, _ = _q(
        [
            _row(tx_type="S-Sale", tx_date="2026-08-01", shares=100, acquisitionOrDisposition="D"),
            _row(tx_type="S-Sale", tx_date="2026-09-30", shares=50, acquisitionOrDisposition="D"),
            _row(tx_type="P-Purchase", tx_date="2026-07-01", shares=30, acquisitionOrDisposition="A"),
            # Same transactionDate quarter even though filed in the next one.
            _row(tx_type="S-Sale", tx_date="2026-06-30", shares=7, filingDate="2026-07-02", acquisitionOrDisposition="D"),
        ]
    )
    q3, q2 = quarters[(2026, 3)], quarters[(2026, 2)]
    assert (q3.open_market_disposed, q3.open_market_acquired) == (150, 30)
    assert (q3.all_disposed, q3.all_acquired) == (150, 30)
    assert q2.open_market_disposed == 7


def test_non_open_market_rows_only_count_toward_the_all_types_totals():
    quarters, _ = _q(
        [
            _row(tx_type="S-Sale", shares=100, acquisitionOrDisposition="D"),
            _row(tx_type="M-Exempt", shares=1000, price=0, acquisitionOrDisposition="A"),  # exercise: acquired
            _row(tx_type="M-Exempt", shares=900, price=0, acquisitionOrDisposition="D"),  # ...and the option leg
            _row(tx_type="F-InKind", shares=400, price=0, acquisitionOrDisposition="D"),  # tax withholding
            _row(tx_type="G-Gift", shares=60, price=0, acquisitionOrDisposition="D"),
            _row(tx_type="A-Award", shares=2000, price=0, acquisitionOrDisposition="A"),
        ]
    )
    q = quarters[(2026, 3)]
    assert (q.open_market_acquired, q.open_market_disposed) == (0, 100)
    assert q.all_acquired == 3000
    assert q.all_disposed == 100 + 900 + 400 + 60


def test_open_market_direction_is_pinned_by_kind_not_the_flag():
    quarters, _ = _q([_row(tx_type="S-Sale", shares=10), _row(tx_type="P-Purchase", shares=4)])  # no A/D flag at all
    q = quarters[(2026, 3)]
    assert (q.all_acquired, q.all_disposed) == (4, 10)


def test_a_row_with_no_direction_flag_is_left_out_of_the_all_types_totals():
    quarters, _ = _q([_row(tx_type="M-Exempt", shares=500, price=0)])
    q = quarters[(2026, 3)]
    assert (q.all_acquired, q.all_disposed) == (0, 0)


def test_the_window_is_twelve_quarters_ending_at_the_newest_transaction_with_gaps_zero_filled():
    quarters, truncated = _q(
        [
            _row(tx_date="2026-09-01", shares=1),
            _row(tx_date="2026-01-15", shares=1),
            _row(tx_date="2023-10-05", shares=1),  # first day of the window's first quarter
            _row(tx_date="2023-09-29", shares=99),  # one quarter too old
        ]
    )
    keys = sorted(quarters)
    assert keys[0] == (2023, 4) and keys[-1] == (2026, 3) and len(keys) == 12
    assert quarters[(2026, 2)].all_acquired == 0 and quarters[(2026, 2)].open_market_acquired == 0
    assert (2023, 3) not in quarters
    assert truncated is False


def test_an_exhausted_young_history_is_not_padded_with_leading_zeros():
    quarters, truncated = _q([_row(tx_date="2026-09-01"), _row(tx_date="2026-02-01")])
    assert sorted(quarters) == [(2026, 1), (2026, 2), (2026, 3)]
    assert truncated is False


def test_a_frontier_drops_quarters_that_could_be_incomplete_and_flags_truncation():
    txs = [_row(tx_date="2026-09-01"), _row(tx_date="2025-01-15"), _row(tx_date="2024-11-20")]
    # Filings on/before 2025-02-10 may be missing -> 2025 Q1 (starts 2025-01-01) is unsafe,
    # 2025 Q2 is the first quarter that begins after the frontier.
    quarters, truncated = _q(txs, frontier=date(2025, 2, 10))
    assert sorted(quarters)[0] == (2025, 2)
    assert (2025, 1) not in quarters and (2024, 4) not in quarters
    assert truncated is True


def test_a_frontier_that_starts_before_the_window_truncates_nothing():
    quarters, truncated = _q([_row(tx_date="2026-09-01"), _row(tx_date="2024-06-01")], frontier=date(2020, 1, 1))
    assert len(quarters) == 12 and truncated is False
    # ...and its leading empty quarters are real zeros, not trimmed.
    assert quarters[(2023, 4)].all_acquired == 0


def test_a_frontier_newer_than_every_quarter_leaves_an_empty_truncated_series():
    quarters, truncated = _q([_row(tx_date="2026-09-01")], frontier=date(2026, 12, 31))
    assert quarters == {} and truncated is True


def test_no_transactions_means_no_series():
    assert build_quarterly_activity([], None) == ([], False)


def test_the_endpoint_payload_carries_the_series_and_the_truncation_flag(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, search=[_filed_row("2026-09-03", tx_type="S-Sale", shares=10)], statistics=[])
    out = asyncio.run(get_insider_activity_data("TEST"))
    assert [(q.year, q.quarter, q.open_market_disposed) for q in out.quarterly_activity] == [(2026, 3, 10)]
    assert out.history_truncated is False


def test_a_capped_cached_blob_reads_as_truncated_through_the_endpoint(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    rows = [_filed_row("2026-09-03"), _filed_row("2025-03-03")]
    _seed_cache(engine, "insider_trading_search", {"rows": rows, "exhausted": False}, datetime.now())
    _seed_cache(engine, "insider_trading_statistics", [], datetime.now())
    _patch_fmp(monkeypatch)
    out = asyncio.run(get_insider_activity_data("TEST"))
    # Frontier 2025-03-03: 2025 Q1 is unsafe, 2025 Q2 is the first shown.
    assert (out.quarterly_activity[0].year, out.quarterly_activity[0].quarter) == (2025, 2)
    assert out.history_truncated is True


# --- search paging ----------------------------------------------------------


def _filed_row(filed: str, tx_date: str | None = None, **kw) -> dict:
    """A row in FMP's order: `filed` drives paging, the transaction is filed 2 days after it."""
    if tx_date is None:
        tx_date = (date.fromisoformat(filed) - timedelta(days=2)).isoformat()
    return _row(tx_date=tx_date, filingDate=filed, **kw)


def _stream(n, start="2026-09-15", step_days=1):
    """n rows filed newest-first, one per `step_days`."""
    first = date.fromisoformat(start)
    return [_filed_row((first - timedelta(days=i * step_days)).isoformat()) for i in range(n)]


def _run(coro):
    return asyncio.run(coro)


def _record_pages(monkeypatch, rows, fail_on_page=None, page_size=10, max_pages=6):
    monkeypatch.setattr(insider_data, "SEARCH_PAGE_SIZE", page_size)
    monkeypatch.setattr(insider_data, "SEARCH_MAX_PAGES", max_pages)
    pages = []

    async def fake_search(ticker, limit, page):
        pages.append(page)
        if page == fail_on_page:
            raise httpx.ConnectError("boom")
        return rows[page * limit : (page + 1) * limit]

    monkeypatch.setattr(insider_data.fmp_client, "get_insider_trading_search", fake_search)
    return pages


def test_a_quiet_ticker_costs_one_request_and_is_exhausted(monkeypatch):
    pages = _record_pages(monkeypatch, _stream(4))
    blob = _run(insider_data._fetch_search_history("TEST"))
    assert pages == [0]
    assert len(blob["rows"]) == 4 and blob["exhausted"] is True


def test_paging_stops_as_soon_as_the_chart_window_is_covered(monkeypatch):
    # One row a week: 12 quarters back from 2026-09 starts 2023-10-01, i.e. ~155
    # weekly rows. 10-row pages must stop the page after the frontier crosses it,
    # not run to the 6-page cap or drain the (much longer) stream.
    rows = _stream(400, step_days=7)
    pages = _record_pages(monkeypatch, rows, max_pages=100)
    blob = _run(insider_data._fetch_search_history("TEST"))
    frontier = insider_data._filing_frontier(blob["rows"])
    assert frontier < date(2023, 10, 1)
    assert pages == list(range(len(pages))) and len(pages) < 20
    # ...and it stopped on the FIRST page that crossed the window start, not one later.
    assert insider_data._filing_frontier(blob["rows"][: -10]) >= date(2023, 10, 1)
    assert blob["exhausted"] is False


def test_a_stray_old_transaction_date_does_not_end_paging_early(monkeypatch):
    # A Form 5 filed today can carry a 2020 transactionDate deep in a recent page.
    # Coverage is judged on FILING date, so this must not fool the stop check.
    rows = _stream(400, step_days=7)
    rows[3] = _filed_row(rows[3]["filingDate"], tx_date="2020-12-31")
    pages = _record_pages(monkeypatch, rows, max_pages=100)
    _run(insider_data._fetch_search_history("TEST"))
    assert len(pages) > 5


def test_paging_is_capped_and_the_blob_reports_not_exhausted(monkeypatch):
    pages = _record_pages(monkeypatch, _stream(500), max_pages=3)
    blob = _run(insider_data._fetch_search_history("TEST"))
    assert pages == [0, 1, 2]
    assert len(blob["rows"]) == 30 and blob["exhausted"] is False


def test_a_later_page_failure_keeps_the_rows_already_fetched(monkeypatch):
    _record_pages(monkeypatch, _stream(500), fail_on_page=2)
    blob = _run(insider_data._fetch_search_history("TEST"))
    assert len(blob["rows"]) == 20 and blob["exhausted"] is False


def test_a_first_page_failure_propagates_so_nothing_is_cached(monkeypatch):
    _record_pages(monkeypatch, _stream(50), fail_on_page=0)
    with pytest.raises(httpx.HTTPError):
        _run(insider_data._fetch_search_history("TEST"))


def test_unpack_reads_the_new_blob_and_the_legacy_bare_list():
    frontier = date(2026, 1, 5)
    rows = [_filed_row("2026-09-01"), _filed_row("2026-01-05")]
    assert insider_data._unpack_search_blob({"rows": rows, "exhausted": True}) == (rows, None)
    assert insider_data._unpack_search_blob({"rows": rows, "exhausted": False}) == (rows, frontier)
    # Legacy: a bare list shorter than the old 100-row limit was exhausted; a full one was capped.
    assert insider_data._unpack_search_blob(rows) == (rows, None)
    full = _stream(100)
    assert insider_data._unpack_search_blob(full) == (full, insider_data._filing_frontier(full))
    assert insider_data._unpack_search_blob({}) == ([], None)
    assert insider_data._unpack_search_blob(None) == ([], None)


def test_a_full_fetch_lands_in_the_cache_as_the_new_blob_shape(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, search=[_filed_row("2026-09-03")], statistics=[])
    asyncio.run(get_insider_activity_data("TEST"))
    with Session(engine) as session:
        row = session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "insider_trading_search")).one()
    assert set(json.loads(row.raw_json)) == {"rows", "exhausted"}


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
        await client.get_insider_trading_search("AAPL", limit=25, page=3)
        await client.get_insider_trading_statistics("AAPL")

    asyncio.run(run())

    assert seen[0][0] == "/stable/insider-trading/search"
    assert seen[0][1]["symbol"] == "AAPL" and seen[0][1]["limit"] == "100" and seen[0][1]["page"] == "0"
    assert seen[1][1]["limit"] == "25" and seen[1][1]["page"] == "3"
    assert seen[2][0] == "/stable/insider-trading/statistics"
    assert seen[2][1]["symbol"] == "AAPL"


# --- shelved-feature flag ---------------------------------------------------


def _fmp_must_not_be_called(monkeypatch):
    calls = []

    async def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("FMP must not be called while Insider Activity is disabled")

    monkeypatch.setattr(insider_data.fmp_client, "get_insider_trading_search", boom)
    monkeypatch.setattr(insider_data.fmp_client, "get_insider_trading_statistics", boom)
    return calls


def _cache_rows(engine):
    with Session(engine) as session:
        return session.exec(select(FundamentalsCache)).all()


def test_the_documented_default_is_disabled():
    from core.config import Settings

    assert Settings.model_fields["insider_activity_enabled"].default is False


def test_disabled_returns_a_distinct_payload_with_no_fmp_call_and_no_cache_write(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    calls = _fmp_must_not_be_called(monkeypatch)
    monkeypatch.setattr(insider_data.settings, "insider_activity_enabled", False)

    out = asyncio.run(get_insider_activity_data("test"))

    assert calls == []
    assert _cache_rows(engine) == []
    assert out.enabled is False
    assert out.ticker == "TEST"  # still normalized
    assert (out.transactions, out.quarterly_stats, out.quarterly_activity) == ([], [], [])
    assert out.has_data is False and out.as_of is None and out.history_truncated is False
    assert out.summary.sentiment == "no_activity"


def test_disabled_ignores_an_already_cached_row_entirely(monkeypatch):
    # Not even a cache READ happens: a populated row must not surface as data.
    engine = _fresh_engine(monkeypatch)
    _seed_cache(engine, "insider_trading_search", [_row()], datetime.now())
    _seed_cache(engine, "insider_trading_statistics", [_stat(2026, 3, purchases=5)], datetime.now())
    _fmp_must_not_be_called(monkeypatch)
    monkeypatch.setattr(insider_data.settings, "insider_activity_enabled", False)

    out = asyncio.run(get_insider_activity_data("TEST", cache_only=True))

    assert out.enabled is False and out.has_data is False and out.transactions == []
    assert len(_cache_rows(engine)) == 2  # ...and nothing was deleted or rewritten either


def test_disabled_is_distinguishable_from_genuinely_empty_and_not_cached(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, search=[], statistics=[])
    empty = asyncio.run(get_insider_activity_data("TEST"))  # enabled, cached and genuinely empty
    assert empty.enabled is True and empty.has_data is False and empty.as_of is not None

    monkeypatch.setattr(insider_data.settings, "insider_activity_enabled", False)
    disabled = asyncio.run(get_insider_activity_data("TEST"))
    assert disabled.enabled is False and disabled.as_of is None
    assert len(_cache_rows(engine)) == 2  # only the enabled call wrote anything


def test_disabled_endpoint_returns_the_disabled_shape_not_a_404(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _fmp_must_not_be_called(monkeypatch)
    monkeypatch.setattr(insider_data.settings, "insider_activity_enabled", False)

    response = TestClient(main.app).get("/api/tickers/AAPL/insider-activity")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["ticker"] == "AAPL"
    assert body["transactions"] == [] and body["quarterly_stats"] == [] and body["quarterly_activity"] == []
    assert body["has_data"] is False and body["as_of"] is None
    assert _cache_rows(engine) == []


def test_enabled_endpoint_reports_enabled_true(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, search=[_filed_row("2026-09-03")], statistics=[])
    body = TestClient(main.app).get("/api/tickers/TEST/insider-activity").json()
    assert body["enabled"] is True and body["has_data"] is True
