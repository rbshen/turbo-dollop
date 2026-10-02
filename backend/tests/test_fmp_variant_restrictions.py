"""Request-variant restrictions (core/data_groups.py "Request variants", 2026-10-02), against SIMULATED responses
only: a canary-confirmed 402 on period=quarter restricts that VARIANT, never the `fundamentals` group; a symbol-scoped
402, a 429 and a 5xx restrict nothing; only the variant's own replay clears it; the nightly job keeps refreshing
annual data after the first quarterly 402 and says so in its message."""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import clients.fmp_client as fmp_client_module
import core.data_groups as dg
import pipeline.nightly_fundamentals_fetch as nightly
from clients.fmp_client import FMPClient, FMPVariantUnavailableError
from core.cache import get_or_fetch_earnings_aware, safe_fetch
from core.cron_health import CronRunContext
from core.main import app
from core.models import FundamentalsCache

QUARTER = "/income-statement?limit=12&period=quarter"
ROW = [{"date": "2026-06-30", "revenue": 1.0}]
_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured once so a test can install a second handler over the first


def _install(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(**kwargs)

    monkeypatch.setattr(fmp_client_module.httpx, "AsyncClient", factory)


def _plan(refused: dict[tuple[str, str | None], int] | None = None, symbol_refused: dict[str, int] | None = None, default=200):
    """handler: `refused[(path, period)]` -> status for every symbol; `symbol_refused[symbol]` -> status for that symbol only."""
    refused, symbol_refused = refused or {}, symbol_refused or {}
    seen: list[dict] = []

    def handler(request):
        q = dict(request.url.params)
        path = "/" + request.url.path.rsplit("/", 1)[-1]  # drop the base URL's prefix
        seen.append({"path": path, **q})
        status = symbol_refused.get(q.get("symbol"), refused.get((path, q.get("period")), default))
        return httpx.Response(status, json=ROW if status < 400 else [])

    handler.seen = seen
    return handler


def _income(client, symbol, period="quarter", limit=12):
    return asyncio.run(client.get_income_statement(symbol, period, limit))


@pytest.fixture
def client():
    return FMPClient(api_key="x")


# --- the 402 canary, variant level --------------------------------------------------------------------------------


def test_a_confirmed_402_on_period_quarter_restricts_only_that_variant(monkeypatch, client):
    h = _plan({("/income-statement", "quarter"): 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "MSFT")
    # failing call, then the minimal replay for the canary symbol: same endpoint + period + limit, nothing else
    assert [(c["symbol"], c["period"], c["limit"]) for c in h.seen] == [("MSFT", "quarter", "12"), ("AAPL", "quarter", "12")]
    assert set(h.seen[1]) == {"path", "symbol", "period", "limit", "apikey"}

    assert dg.effective_state("fundamentals") == (True, "live")  # the group is untouched
    assert dg.get_snapshot().groups["fundamentals"].status == "ok"
    assert [v.variant_key for v in dg.restricted_variants("fundamentals")] == [QUARTER]
    assert dg.restricted_variants("fundamentals")[0].label == "Quarterly income statement (limit 12)"

    # the restricted variant answers immediately, with no FMP call...
    n = len(h.seen)
    with pytest.raises(FMPVariantUnavailableError, match="not available on this plan"):
        _income(client, "AAPL")
    assert len(h.seen) == n
    # ...while annual requests, other endpoints and other quarterly endpoints keep working
    assert _income(client, "MSFT", "annual", 10) == ROW
    assert asyncio.run(client.get_ratios_ttm("MSFT")) == ROW
    assert asyncio.run(client.get_key_metrics("MSFT", "annual", 10)) == ROW
    assert len(h.seen) == n + 3


def test_each_quarterly_endpoint_is_its_own_variant(monkeypatch, client):
    h = _plan({("/income-statement", "quarter"): 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "MSFT")
    assert asyncio.run(client.get_balance_sheet_statement("MSFT", "quarter", 12)) == ROW  # a different endpoint


def test_the_limit_is_part_of_the_variant(monkeypatch, client):
    def handler(request):
        refused = request.url.params.get("limit") == "10"
        return httpx.Response(402 if refused else 200, json=[] if refused else ROW)

    _install(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "MSFT", "annual", 10)
    assert [v.variant_key for v in dg.restricted_variants()] == ["/income-statement?limit=10&period=annual"]
    assert _income(client, "MSFT", "annual", 1) == ROW  # annual at another limit still works


def test_a_402_on_one_symbol_only_restricts_nothing(monkeypatch, client):
    h = _plan(symbol_refused={"BRK.B": 402})
    _install(monkeypatch, h)
    for period in ("quarter", "annual"):
        with pytest.raises(httpx.HTTPStatusError):
            _income(client, "BRK.B", period)
    assert dg.restricted_variants() == [] and dg.effective_state("fundamentals") == (True, "live")
    assert _income(client, "AAPL") == ROW  # and AAPL quarterly still works


@pytest.mark.parametrize("status", [429, 500, 503])
def test_other_failures_never_restrict_anything(monkeypatch, client, status):
    monkeypatch.setattr(fmp_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.0)
    h = _plan(default=status)
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "MSFT")
    assert dg.restricted_variants() == [] and dg.effective_state("fundamentals")[0]
    assert all(g.status in ("ok", "failing") for g in dg.get_snapshot().groups.values())


@pytest.mark.parametrize("canary_status", [429, 500, 200])
def test_a_402_whose_canary_is_not_a_402_is_inconclusive(monkeypatch, client, canary_status):
    monkeypatch.setattr(fmp_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.0)
    _install(monkeypatch, _plan(symbol_refused={"MSFT": 402, "AAPL": canary_status}))
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "MSFT")
    assert dg.restricted_variants() == []


def test_a_transport_error_on_the_canary_restricts_nothing(monkeypatch, client):
    def handler(request):
        if request.url.params.get("symbol") == "AAPL":
            raise httpx.ConnectTimeout("boom")
        return httpx.Response(402, json=[])

    _install(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "MSFT")
    assert dg.restricted_variants() == []


def test_a_402_on_the_canary_symbol_is_its_own_canary(monkeypatch, client):
    h = _plan({("/income-statement", "quarter"): 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "AAPL")
    assert len(h.seen) == 1 and len(dg.restricted_variants()) == 1


def test_groups_that_are_not_variant_groups_keep_the_group_level_net(monkeypatch, client):
    assert dg.VARIANT_GROUPS == {"fundamentals"}
    _install(monkeypatch, _plan(default=402))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.get_grades_consensus("MSFT"))
    assert dg.effective_state("analyst_ratings") == (False, "restricted") and dg.restricted_variants() == []


# --- re-probing -----------------------------------------------------------------------------------------------------


def _restrict_quarter(monkeypatch, client):
    h = _plan({("/income-statement", "quarter"): 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _income(client, "MSFT")
    return h


def test_a_reprobe_replays_the_variants_own_request_and_clears_only_when_it_succeeds(monkeypatch, client, caplog):
    _restrict_quarter(monkeypatch, client)
    h = _plan({("/income-statement", "quarter"): 402})  # annual works, quarterly still refused
    _install(monkeypatch, h)
    since = dg.restricted_variants()[0].restricted_since

    assert asyncio.run(client.reprobe_restricted_variants()) == {f"fundamentals:{QUARTER}": "restricted"}
    assert [(c["symbol"], c["period"], c["limit"]) for c in h.seen] == [("AAPL", "quarter", "12")]  # NOT the annual probe
    assert dg.restricted_variants()[0].restricted_since == since
    assert dg.restricted_variants()[0].last_probe_at is not None

    ok = _plan()  # now FMP serves quarterly
    _install(monkeypatch, ok)
    with caplog.at_level(logging.WARNING, logger="core.data_groups"):
        assert asyncio.run(client.reprobe_restricted_variants()) == {f"fundamentals:{QUARTER}": "ok"}
    assert dg.restricted_variants() == []
    assert [r.getMessage() for r in caplog.records if "CLEARED" in r.getMessage()] == [
        f"FMP request variant CLEARED (group fundamentals): {QUARTER} -- re-probe succeeded"
    ]
    assert _income(client, "MSFT") == ROW  # and the quarterly call goes out again


def test_two_weekly_probe_cycles_do_not_flap(monkeypatch, client, caplog):
    h = _restrict_quarter(monkeypatch, client)
    since = dg.restricted_variants()[0].restricted_since
    with caplog.at_level(logging.WARNING, logger="core.data_groups"):
        for _week in range(2):
            # the full weekly job: group-level re-probe (nothing restricted) + variant re-probe; the annual probe that used
            # to clear the whole group is irrelevant now
            assert asyncio.run(client.reprobe_restricted()) == {f"fundamentals:{QUARTER}": "restricted"}
            assert dg.effective_state("fundamentals") == (True, "live")
            assert _income(client, "MSFT", "annual", 10) == ROW  # annual is never interrupted between probes
            with pytest.raises(FMPVariantUnavailableError):
                _income(client, "MSFT")  # and the quarterly call is gated, so nothing re-marks anything
    assert dg.restricted_variants()[0].restricted_since == since
    changes = [r.getMessage() for r in caplog.records if "RESTRICTED" in r.getMessage() or "CLEARED" in r.getMessage()]
    assert len(changes) == 1 and "RESTRICTED" in changes[0]  # only the first restriction: no clear/re-mark across two cycles
    assert h.seen.count({"path": "/income-statement", "symbol": "AAPL", "period": "quarter", "limit": "12", "apikey": "x"}) == 3  # canary + 2 probes


def test_a_restriction_logs_one_line_when_it_happens(monkeypatch, client, caplog):
    _install(monkeypatch, _plan({("/income-statement", "quarter"): 402}))
    with caplog.at_level(logging.WARNING, logger="core.data_groups"):
        for symbol in ("MSFT", "KO"):
            if symbol == "KO":
                with pytest.raises(FMPVariantUnavailableError):
                    _income(client, symbol)
            else:
                with pytest.raises(httpx.HTTPStatusError):
                    _income(client, symbol)
    assert len([r for r in caplog.records if "RESTRICTED" in r.getMessage()]) == 1


def test_reprobe_makes_no_call_while_the_master_switch_or_the_group_is_off(monkeypatch, client):
    _restrict_quarter(monkeypatch, client)

    def handler(request):
        raise AssertionError("no live call expected")

    _install(monkeypatch, handler)
    dg.set_master(False)
    assert asyncio.run(client.reprobe_restricted_variants()) == {}
    dg.set_master(True)
    dg.set_group_enabled("fundamentals", False)
    assert asyncio.run(client.reprobe_restricted_variants()) == {}


def test_a_reprobe_that_is_inconclusive_leaves_the_restriction(monkeypatch, client):
    _restrict_quarter(monkeypatch, client)
    _install(monkeypatch, _plan(default=500))
    assert asyncio.run(client.reprobe_restricted_variants()) == {f"fundamentals:{QUARTER}": "inconclusive"}
    assert len(dg.restricted_variants()) == 1


# --- the cache layer ------------------------------------------------------------------------------------------------


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _quarterly(client, session, ticker, cached_only=False):
    return get_or_fetch_earnings_aware(
        session, ticker, "income_statement", "quarterly",
        lambda: client.get_income_statement(ticker, "quarter", 12), 7, None, cached_only,
    )


def test_a_restricted_variant_serves_the_stale_cached_row_and_writes_nothing(monkeypatch, client, engine):
    _restrict_quarter(monkeypatch, client)
    stale = [{"date": "2025-12-31", "revenue": 9.0}]
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="KO", statement_type="income_statement", period="quarterly",
                                      fetched_at=datetime.now() - timedelta(days=60), raw_json=json.dumps(stale)))
        session.commit()
        assert asyncio.run(_quarterly(client, session, "KO")) == stale
        row = session.exec(select(FundamentalsCache)).one()
    assert json.loads(row.raw_json) == stale and row.fetched_at < datetime.now() - timedelta(days=59)  # not even re-stamped


def test_with_nothing_cached_it_is_no_data_not_a_cached_empty_row(monkeypatch, client, engine):
    _restrict_quarter(monkeypatch, client)
    with Session(engine) as session:
        assert asyncio.run(safe_fetch("income_q", _quarterly(client, session, "KO"))) == {}
        assert session.exec(select(FundamentalsCache)).all() == []


# --- the nightly job --------------------------------------------------------------------------------------------------


def test_the_nightly_job_keeps_refreshing_annual_data_after_the_first_quarterly_402(monkeypatch, tmp_path, engine, client):
    h = _plan({("/income-statement", "quarter"): 402, ("/cash-flow-statement", "quarter"): 402})
    _install(monkeypatch, h)
    monkeypatch.setattr(nightly, "engine", engine)
    monkeypatch.setattr(nightly, "LOG_PATH", tmp_path / "nightly.log")
    monkeypatch.setattr(nightly, "fmp_client", client)

    async def refresh_one(ticker):
        with Session(engine) as session:
            await safe_fetch("income_q", _quarterly(client, session, ticker))
            await safe_fetch("cash_q", get_or_fetch_earnings_aware(
                session, ticker, "cash_flow_statement", "quarterly", lambda: client.get_cash_flow_statement(ticker, "quarter", 12), 7, None))
            await safe_fetch("income_a", get_or_fetch_earnings_aware(
                session, ticker, "income_statement", "annual", lambda: client.get_income_statement(ticker, "annual", 10), 7, None))

    monkeypatch.setattr(nightly, "_refresh_one_ticker", refresh_one)
    result = asyncio.run(nightly.main(["AAA", "BBB", "CCC", "DDD"]))

    assert result["failed"] == 0 and result["variant_unavailable"] == 4 and result["variants_unavailable"] == 2
    assert dg.effective_state("fundamentals") == (True, "live")  # the group never flipped
    with Session(engine) as session:
        cached = {(r.ticker, r.statement_type, r.period) for r in session.exec(select(FundamentalsCache)).all()}
    assert cached == {(t, "income_statement", "annual") for t in ("AAA", "BBB", "CCC", "DDD")}  # annual for EVERY ticker, no empty quarterly rows
    # quarterly was asked of FMP only to discover the restriction: (failing + canary) per variant, none for tickers 2-4
    quarter_calls = [c for c in h.seen if c.get("period") == "quarter"]
    assert len(quarter_calls) == 4
    assert len([c for c in h.seen if c.get("period") == "annual"]) == 4

    run = CronRunContext()
    nightly.record_outcome(result, run)
    assert run.message.endswith("4 variant-unavailable (2 request types refused by the plan)")


def test_the_variant_count_is_informational_and_never_hides_a_real_failure():
    base = {"processed": 587, "calls_made": 10, "duration_seconds": 60.0, "variant_unavailable": 587, "variants_unavailable": 3}
    run = CronRunContext()
    nightly.record_outcome({**base, "failed": 0}, run)  # every ticker had an unavailable variant: still green
    assert run.message == "587 refreshed, 0 failed, 10 FMP calls, 1.0 min, 587 variant-unavailable (3 request types refused by the plan)"
    with pytest.raises(RuntimeError, match="variant-unavailable"):  # real per-ticker failures still go red, with the counts kept in the text
        nightly.record_outcome({**base, "failed": 60}, CronRunContext())
    quiet = CronRunContext()
    nightly.record_outcome({**base, "failed": 0, "variant_unavailable": 0}, quiet)
    assert "variant" not in quiet.message


# --- Settings API ---------------------------------------------------------------------------------------------------------


def test_settings_shows_the_group_live_with_its_unavailable_variants(monkeypatch, client):
    _restrict_quarter(monkeypatch, client)
    with TestClient(app) as http:
        group = {g["key"]: g for g in http.get("/api/config/data-groups").json()["groups"]}["fundamentals"]
    assert group["state"] == "live" and group["reason"] == "live" and group["can_toggle"] is True
    assert [(v["key"], v["label"]) for v in group["unavailable_variants"]] == [(QUARTER, "Quarterly income statement (limit 12)")]


def test_the_manual_retest_and_clear_overrides(monkeypatch, client):
    _restrict_quarter(monkeypatch, client)
    with TestClient(app) as http:
        _install(monkeypatch, _plan({("/income-statement", "quarter"): 402}))
        body = http.post("/api/config/data-groups/fundamentals/retest").json()
        assert len({g["key"]: g for g in body["groups"]}["fundamentals"]["unavailable_variants"]) == 1  # still refused: stays
        _install(monkeypatch, _plan())
        body = http.post("/api/config/data-groups/fundamentals/retest").json()
        assert {g["key"]: g for g in body["groups"]}["fundamentals"]["unavailable_variants"] == []  # served: cleared

        dg.mark_variant_restricted("fundamentals", "/income-statement", {"symbol": "X", "period": "quarter", "limit": 12}, "again")
        assert http.delete("/api/config/data-groups/fundamentals/variants", params={"key": QUARTER}).status_code == 200
        assert dg.restricted_variants() == []
        assert http.delete("/api/config/data-groups/fundamentals/variants", params={"key": QUARTER}).status_code == 404
        assert http.post("/api/config/data-groups/nope/retest").status_code == 404


def test_variant_keys_and_labels():
    assert dg.variant_of("/income-statement", {"symbol": "KO", "period": "quarter", "limit": 12}) == (QUARTER, {"period": "quarter", "limit": 12})
    assert dg.variant_of("/ratios-ttm", {"symbol": "KO"}) == ("/ratios-ttm", {})
    assert dg.variant_label("/ratios-ttm", {}) == "Ratios (TTM)"
    assert dg.variant_label("/balance-sheet-statement", {"period": "annual", "limit": 10}) == "Annual balance sheet (limit 10)"


def test_variant_groups_are_real_groups_with_a_probe_and_every_variant_param_is_a_real_query_param():
    assert dg.VARIANT_GROUPS <= set(dg.GROUPS)
    assert set(dg.VARIANT_PARAMS) == {"period", "limit"}
    for group in dg.VARIANT_GROUPS:
        assert group in dg.PROBE_ENDPOINTS  # the legacy group-level re-probe still has its canary
