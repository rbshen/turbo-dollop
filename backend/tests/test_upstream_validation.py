"""Upstream data validation: FMPClient.get's shape check, null-safe ticker_summary parsing and the corrupt
saved-view guard. Malformed fixtures only, no network (MockTransport), in-memory engines."""

import asyncio
import json
from datetime import date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.fmp_client as fmp_client_module
import core.cache as cache_module
import core.data_groups as dg
import core.main as main
from clients.fmp_client import FMPClient, FMPInvalidResponseError
from core.cache import get_or_fetch, safe_fetch
from core.models import FundamentalsCache, SavedScreenerFilter
from data import ticker_summary as ts


def _install(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(**kwargs)

    monkeypatch.setattr(fmp_client_module.httpx, "AsyncClient", factory)


def _get(client, endpoint="/profile"):
    return asyncio.run(client.get(endpoint, {"symbol": "AAPL"}))


# ---- FMPClient.get ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>maintenance</html>", headers={"content-type": "text/html"}),
        httpx.Response(200, content=b""),
        httpx.Response(200, content=b"\xff\xfe not utf-8"),
        httpx.Response(200, content=b'{"truncated": '),
        httpx.Response(200, json={"Error Message": "Limit Reach"}),
        httpx.Response(200, json={"error": "bad"}),
        httpx.Response(200, json={"ERROR MESSAGE": "x", "other": 1}),
        httpx.Response(200, json=None),
        httpx.Response(200, json="a string"),
        httpx.Response(200, json=42),
    ],
)
def test_a_200_that_is_not_data_is_a_handled_upstream_error(monkeypatch, response):
    _install(monkeypatch, lambda request: response)
    client = FMPClient(api_key="secret-key")
    with pytest.raises(FMPInvalidResponseError) as exc:
        _get(client)
    assert isinstance(exc.value, httpx.HTTPError)  # safe_fetch / every `except httpx.HTTPError` already handles it
    assert "secret-key" not in str(exc.value) and "apikey" not in str(exc.value)
    assert asyncio.run(safe_fetch("profile", client.get("/profile", {"symbol": "AAPL"}))) == {}


def test_valid_bodies_pass_unchanged(monkeypatch):
    current = {}
    _install(monkeypatch, lambda request: httpx.Response(200, json=current["body"]))
    for body in ([], [{"symbol": "AAPL"}], {}, {"symbol": "AAPL", "errorCount": 0}):
        current["body"] = body
        assert _get(FMPClient(api_key="x")) == body


def test_an_invalid_200_counts_as_a_group_failure_not_a_success(monkeypatch):
    _install(monkeypatch, lambda request: httpx.Response(200, json={"Error Message": "x"}))
    with pytest.raises(FMPInvalidResponseError):
        _get(FMPClient(api_key="x"))
    group = dg.group_for_endpoint("/profile")
    assert dg.get_snapshot().groups[group].consecutive_failures == 1


def test_an_invalid_200_never_clears_a_restriction_in_a_probe(monkeypatch):
    group = "profile_quote"
    dg.mark_restricted(group, "test")
    _install(monkeypatch, lambda request: httpx.Response(200, content=b"<html>"))
    assert asyncio.run(FMPClient(api_key="x").probe_group(group)) == "inconclusive"
    assert dg.get_snapshot().groups[group].status == "plan_restricted"


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.mark.parametrize(
    "statement_type,period",
    [
        ("profile", "latest"),  # a snapshot key: the plain overwrite path
        ("quote", "latest"),
        ("income_statement", "annual"),  # a history key: the merge path
        ("price_target_consensus", "latest"),
        ("some_future_key", "latest"),  # any key
    ],
)
def test_an_error_answer_is_never_cached_for_any_key(monkeypatch, statement_type, period):
    _install(monkeypatch, lambda request: httpx.Response(200, json={"Error Message": "Limit Reach"}))
    client = FMPClient(api_key="x")
    engine = _engine()
    good = [{"date": "2025-12-31", "revenue": 1}]
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker="AAPL", statement_type=statement_type, period=period, fetched_at=datetime(2020, 1, 1), raw_json=json.dumps(good)
            )
        )
        session.commit()

        async def run():
            return await get_or_fetch(
                session, "AAPL", statement_type, period, lambda: client.get("/profile", {"symbol": "AAPL"}), staleness_days=7
            )

        with pytest.raises(FMPInvalidResponseError):
            asyncio.run(run())  # reaches safe_fetch's caller as the failed fetch it is
        row = session.exec(select(FundamentalsCache)).one()
        assert json.loads(row.raw_json) == good and row.fetched_at == datetime(2020, 1, 1)  # untouched, still stale -> retried next time


def test_an_error_answer_with_nothing_cached_writes_nothing(monkeypatch):
    _install(monkeypatch, lambda request: httpx.Response(200, content=b"not json"))
    client = FMPClient(api_key="x")
    engine = _engine()
    with Session(engine) as session:
        result = asyncio.run(
            safe_fetch("profile", get_or_fetch(session, "AAPL", "profile", "latest", lambda: client.get("/profile", {"symbol": "AAPL"}), 7))
        )
        assert result == {}
        assert session.exec(select(FundamentalsCache)).all() == []


# ---- ticker_summary --------------------------------------------------------------------------------------------------


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


def test_avg_volume_30d_skips_malformed_rows():
    rows = [
        {"date": _day(0), "volume": 100},
        {"date": _day(1), "volume": None},  # null volume
        {"date": _day(2), "volume": "oops"},
        {"date": None, "volume": 5},
        {"volume": 5},  # no date
        {"date": "not-a-date", "volume": 5},
        "garbage",
        {"date": _day(3), "volume": 300},
    ]
    assert ts._avg_volume_30d(rows) == 200
    assert ts._avg_volume_30d([{"date": _day(0), "volume": None}]) is None
    assert ts._avg_volume_30d([{"volume": 1}]) is None
    assert ts._avg_volume_30d([]) is None


def test_avg_volume_30d_unchanged_for_clean_rows():
    rows = [{"date": _day(i), "volume": 10 * (i + 1)} for i in range(5)] + [{"date": _day(60), "volume": 9999}]
    assert ts._avg_volume_30d(rows) == 30


def test_avg_dollar_volume_20d_skips_malformed_rows():
    rows = [{"close": 10, "volume": 5}, {"close": None, "volume": 5}, {"close": 10, "volume": None}, "x", {"close": "a", "volume": 1}, {"close": 20, "volume": 5}]
    assert ts._avg_dollar_volume_20d(rows) == 75
    assert ts._avg_dollar_volume_20d([{"close": None, "volume": None}]) is None
    assert ts._avg_dollar_volume_20d([]) is None


def test_next_earnings_date_skips_malformed_dates():
    future = date.today() + timedelta(days=10)
    rows = [
        {"date": "garbage", "epsActual": None},
        {"date": None, "epsActual": None},
        {"date": 20261231, "epsActual": None},
        {"date": "", "epsActual": None},
        "junk",
        {"epsActual": None},
        {"date": future.isoformat(), "epsActual": None},
        {"date": (future + timedelta(days=5)).isoformat() + "T00:00:00", "epsActual": None},
    ]
    assert ts._next_earnings_date(rows) == future
    assert ts._next_earnings_date([{"date": "garbage", "epsActual": None}]) is None


def test_pct_and_number_helpers():
    assert ts._pct(0.5) == 50
    assert ts._pct(None) is None and ts._pct("0.5") is None and ts._pct(True) is None and ts._pct(float("nan")) is None


# ---- saved views -----------------------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    now = datetime(2026, 1, 1)
    with Session(engine) as session:
        for name, raw in [("good", '{"a": 1}'), ("truncated", '{"a": '), ("empty", ""), ("not an object", "[1, 2]"), ("null", "null")]:
            session.add(
                SavedScreenerFilter(
                    name=name, kind="stock", universe="all", sort_field="overall_score", sort_direction="desc",
                    filters_json=raw, created_at=now, updated_at=now,
                )
            )
        session.commit()
    with TestClient(main.app) as c:
        yield c


def test_one_corrupt_saved_view_does_not_break_the_list(client):
    response = client.get("/api/screener/filters")
    assert response.status_code == 200
    by_name = {v["name"]: v["filters"] for v in response.json()}
    assert by_name == {"good": {"a": 1}, "truncated": {}, "empty": {}, "not an object": {}, "null": {}}


def test_a_corrupt_saved_view_can_be_replaced(client):
    body = {"universe": "all", "sort_field": "overall_score", "sort_direction": "desc", "filters": {"b": 2}}
    assert client.put("/api/screener/filters/truncated", json=body).json()["filters"] == {"b": 2}
