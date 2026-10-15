"""Item 4 of the auth work: what a VIEWER may see and cause. A viewer is restricted server-side (not by the UI) to tickers already in the
tracked universe, every data function runs cache-only, nothing they request writes a row or touches a ticker view, and operational detail
is withheld. Every test counts the calls that reach the FMP client and every non-SELECT statement the app database receives."""

import asyncio
import sys
from datetime import date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, select

import conftest as suite_conftest
import core.main as main
from clients.fmp_client import fmp_client
from core.config import settings
from core.models import (
    FundamentalsCache,
    IndexConstituent,
    ScoreRecomputeRun,
    TickerScore,
    TickerView,
    Watchlist,
    WatchlistTicker,
)
from core.route_roles import ROUTE_ROLES
from core.schemas import ChartOut, RecomputeRunOut, RecomputeSummary, UniverseAddOut
from data.viewer_chart_cache import ViewerChartCache, viewer_chart_cache
from wipe_seed import make_engine

pytestmark = pytest.mark.auth("viewer")  # the default TestClient signs in as a viewer; admin comparisons use client_for("admin")

_APP_PACKAGES = {"core", "data", "helpers", "pipeline", "clients", "scoring", "analysis"}
_WRITE_WORDS = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP")
VIEWED = datetime.now() - timedelta(days=5)


class World:
    def __init__(self, engine, calls, writes):
        self.engine, self.calls, self.writes = engine, calls, writes

    def reset(self):
        self.calls.clear()
        self.writes.clear()


def _profile(ticker, *, etf=False):
    return FundamentalsCache(
        ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(),
        raw_json='[{"symbol": "%s", "companyName": "%s Inc", "exchange": "NASDAQ", "isEtf": %s, "isFund": false, "sector": "Technology"}]'
        % (ticker, ticker, "true" if etf else "false"),
    )


@pytest.fixture()
def world(monkeypatch):
    engine = make_engine()
    for name, module in list(sys.modules.items()):
        if module is not None and name.split(".")[0] in _APP_PACKAGES and getattr(module, "engine", None) is suite_conftest.real_engine:
            monkeypatch.setattr(module, "engine", engine)
    with Session(engine) as s:
        # TRK: tracked (S&P 500 member) with a stored score row. UNT: known and viewed 5 days ago, but not added: out of the universe.
        s.add_all([_profile("TRK"), _profile("UNT"), _profile("EEE", etf=True)])
        s.add(IndexConstituent(index_name="sp500", ticker="TRK", company_name="TRK Inc", sector="Technology", sub_industry="Software", last_synced_at=datetime.now()))
        s.add(
            TickerScore(
                ticker="TRK", company_name="TRK Inc", computed_at=datetime.now(), overall_score=77, overall_verdict="Pass", is_etf=False,
                formula_version=None, weights_version=None,
            )
        )
        s.add(TickerView(ticker="TRK", last_viewed_at=VIEWED))
        s.add(TickerView(ticker="UNT", last_viewed_at=VIEWED))
        s.add(TickerView(ticker="EEE", last_viewed_at=VIEWED, added_at=VIEWED, added_source="user"))  # an added ETF: tracked
        s.commit()
        # The live database already holds every settings singleton (a first read of a pristine database seeds its default row, an
        # idempotent pre-existing behaviour); seed them here so "no write" below means no write beyond that.
        from data.score_weights import get_score_weights_row
        from helpers.discount_rate_config import get_discount_rate_config
        from helpers.liquidity_zone_config import get_liquidity_zone_settings
        from helpers.reit_dividend_yield_config import get_reit_dividend_yield_config
        from helpers.weinstein_config import get_weinstein_settings
        from data.moat import get_moat_score_config

        for getter in (get_discount_rate_config, get_reit_dividend_yield_config, get_liquidity_zone_settings, get_weinstein_settings,
                       get_moat_score_config, get_score_weights_row):
            getter(s)
    calls, writes = [], []

    async def no_network(endpoint, params=None, group=None):
        calls.append(endpoint)
        raise httpx.ReadTimeout("the tests have no network")

    monkeypatch.setattr(fmp_client, "get", no_network)

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(_WRITE_WORDS):
            writes.append(statement.strip()[:120])

    event.listen(engine, "before_cursor_execute", record)
    return World(engine, calls, writes)


def concrete(path: str, ticker: str) -> str:
    return path.replace("{ticker}", ticker).replace("{watchlist_id}", "1").replace("{as_of_date}", "2026-01-02").replace("{name}", "view")


TICKER_GETS = sorted(p for (m, p), role in ROUTE_ROLES.items() if m == "GET" and "{ticker}" in p and role == "viewer")
OTHER_VIEWER_GETS = sorted(
    p for (m, p), role in ROUTE_ROLES.items()
    if m == "GET" and "{ticker}" not in p and role == "viewer" and not p.startswith("/api/auth") and p != "/api/tickers/search"
)


# ---- untracked tickers: 404, no fetch, no write ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", TICKER_GETS)
@pytest.mark.parametrize("ticker", ["UNT", "ZZZ"])
def test_a_viewer_gets_a_generic_404_for_a_ticker_outside_the_universe_and_nothing_is_fetched_or_written(world, path, ticker):
    response = TestClient(main.app).get(concrete(path, ticker))
    assert response.status_code == 404 and response.json() == {"detail": "Not found"}
    assert world.calls == [] and world.writes == []


def test_the_same_request_by_an_admin_does_reach_fmp_and_write(world, client_for):
    """The control: without it 'no calls, no writes' could just mean the fake FMP breaks everything."""
    response = client_for("admin").get("/api/tickers/UNT/summary")
    assert response.status_code != 404
    assert world.calls, "an admin's summary of an unseen-today ticker fetches live"
    assert world.writes, "and records the view"


def test_a_viewer_cannot_add_remove_or_rate_a_ticker(world):
    viewer = TestClient(main.app)
    for method, path in (("POST", "/api/tickers/UNT/universe"), ("DELETE", "/api/tickers/TRK/universe"), ("PUT", "/api/tickers/TRK/moat"),
                         ("POST", "/api/tickers/TRK/refresh")):
        assert viewer.request(method, path, json={}).status_code == 403
    assert world.calls == [] and world.writes == []


# ---- tracked tickers: served from cache, no call, no write -----------------------------------------------------------------


@pytest.mark.parametrize("path", TICKER_GETS)
def test_a_viewer_reads_a_tracked_ticker_with_zero_fmp_calls_and_zero_writes(world, path):
    response = TestClient(main.app).get(concrete(path, "TRK"))
    assert response.status_code < 500, (path, response.text[:200])
    assert world.calls == [], f"{path} reached FMP: {world.calls}"
    assert world.writes == [], f"{path} wrote: {world.writes}"


@pytest.mark.parametrize("path", [p for p in TICKER_GETS if p != "/api/tickers/{ticker}/chart"])
def test_a_tracked_etf_is_open_to_a_viewer_too(world, path):
    response = TestClient(main.app).get(concrete(path, "EEE"))
    assert response.status_code < 500 and response.status_code != 404, (path, response.text[:200])
    assert world.calls == [] and world.writes == []


@pytest.mark.parametrize("path", OTHER_VIEWER_GETS)
def test_every_other_viewer_read_makes_no_fmp_call_and_no_write(world, path):
    with Session(world.engine) as s:
        s.add(Watchlist(name="E1", created_at=datetime.now(), updated_at=datetime.now()))
        s.commit()
        s.add(WatchlistTicker(watchlist_id=1, ticker="TRK", added_at=datetime.now()))
        s.commit()
    world.reset()
    path = path.replace("{watchlist_id}", "1").replace("{as_of_date}", "2026-01-02").replace("{name}", "view")
    if path.endswith("/export-data"):
        path += "?ids=1"
    response = TestClient(main.app).get(path)
    assert response.status_code < 500, (path, response.text[:200])
    assert world.calls == [], f"{path} reached FMP: {world.calls}"
    assert world.writes == [], f"{path} wrote: {world.writes}"


def test_a_viewers_summary_does_not_touch_or_create_a_ticker_view(world):
    TestClient(main.app).get("/api/tickers/TRK/summary")
    with Session(world.engine) as s:
        assert s.get(TickerView, "TRK").last_viewed_at == VIEWED
    assert world.writes == []


def test_score_serves_the_stored_row_and_never_recomputes_a_current_one(world):
    body = TestClient(main.app).get("/api/tickers/TRK/score").json()
    assert body["overall_score"] == 77
    assert world.calls == [] and world.writes == []


def test_score_rederives_an_older_weights_row_in_memory_without_storing_it(world):
    from scoring.overall import SCORE_FORMULA_VERSION

    with Session(world.engine) as s:
        row = s.get(TickerScore, "TRK")
        row.weights_version, row.formula_version = 0, SCORE_FORMULA_VERSION - 1  # scored under older weights / another formula
        s.add(row)
        s.commit()
    world.reset()
    response = TestClient(main.app).get("/api/tickers/TRK/score")
    assert response.status_code == 200
    assert world.calls == [] and world.writes == []
    with Session(world.engine) as s:
        assert (s.get(TickerScore, "TRK").weights_version, s.get(TickerScore, "TRK").overall_score) == (0, 77)  # the stored row is untouched


def test_score_for_a_tracked_ticker_with_no_row_is_derived_without_a_write(world):
    with Session(world.engine) as s:
        s.delete(s.get(TickerScore, "TRK"))
        s.commit()
    world.reset()
    response = TestClient(main.app).get("/api/tickers/TRK/score")
    assert response.status_code == 200
    assert world.calls == [] and world.writes == []
    with Session(world.engine) as s:
        assert s.get(TickerScore, "TRK") is None


def test_watchlist_rows_for_a_viewer_are_cache_only_and_write_free_while_an_admin_gets_the_live_consensus(world, client_for):
    with Session(world.engine) as s:
        s.add(Watchlist(name="W9", created_at=datetime.now(), updated_at=datetime.now()))
        s.commit()
        s.add(WatchlistTicker(watchlist_id=1, ticker="TRK", added_at=datetime.now()))
        s.commit()
    world.reset()
    assert TestClient(main.app).get("/api/watchlists/1/rows").status_code == 200
    assert world.calls == [] and world.writes == []
    client_for("admin").get("/api/watchlists/1/rows")
    assert "/grades-consensus" in world.calls  # the admin path is unchanged: it still fetches the consensus rating live


# ---- search --------------------------------------------------------------------------------------------------------------


def test_viewer_search_uses_only_the_tracked_universe_and_makes_no_fmp_call(world, client_for):
    viewer = TestClient(main.app)
    symbols = [r["symbol"] for r in viewer.get("/api/tickers/search?q=T").json()]
    assert symbols == ["TRK"]  # UNT (browsed) matches 'T' but a viewer could not open it; EEE has no T
    # the seed ETFs (XLE, XLRE: "system" tickers) are in the universe by design, so they are offered too
    assert [r["symbol"] for r in viewer.get("/api/tickers/search?q=E").json()] == ["EEE", "XLE", "XLRE"]
    assert viewer.get("/api/tickers/search?q=ZZ").json() == []
    assert world.calls == [] and world.writes == []
    client_for("admin").get("/api/tickers/search?q=T")
    assert "/search-symbol" in world.calls  # an admin's search is still the live one


# ---- chart: in-memory TTL cache for viewers ----------------------------------------------------------------------------------


def _chart(range_key="D_1Y") -> ChartOut:
    return ChartOut(
        range=range_key, timeframe="daily", bars=[], ema21=[], sma50=[], sma200=[], bollinger=[], stochastic=[], rsi=[],
        entry_signal_available=False, warren_signal_available=False, zones_available=False, source="fmp", chart_available=False,
    )


@pytest.fixture()
def chart_loads(monkeypatch, world):
    loads = []

    async def fake_chart(ticker, range_key):
        loads.append((ticker, range_key))
        return _chart(range_key)

    monkeypatch.setattr(main, "get_chart_data", fake_chart)
    return loads


def test_viewer_chart_requests_share_one_load_per_ticker_and_view(chart_loads):
    viewer = TestClient(main.app)
    for _ in range(5):
        assert viewer.get("/api/tickers/TRK/chart?range=D_1Y").status_code == 200
    assert chart_loads == [("TRK", "D_1Y")]
    viewer.get("/api/tickers/TRK/chart?range=W_4Y")
    viewer.get("/api/tickers/TRK/chart")  # the default view is D_1Y: a hit
    assert chart_loads == [("TRK", "D_1Y"), ("TRK", "W_4Y")]


def test_viewer_chart_cache_serves_the_d_6m_fvgs_and_keeps_other_views_empty(world, monkeypatch):
    from core.schemas import ChartFvgOut

    loads = []

    async def fake_chart(ticker, range_key):
        loads.append(range_key)
        out = _chart(range_key)
        if range_key == "D_6M":
            out.fvgs = [ChartFvgOut(side="bullish", top=12.0, bottom=10.0, start_time="2026-03-02")]
        return out

    monkeypatch.setattr(main, "get_chart_data", fake_chart)
    viewer = TestClient(main.app)
    for _ in range(2):
        body = viewer.get("/api/tickers/TRK/chart?range=D_6M").json()
        assert body["fvgs"] == [{"side": "bullish", "top": 12.0, "bottom": 10.0, "start_time": "2026-03-02", "end_time": None}]
    assert viewer.get("/api/tickers/TRK/chart?range=D_1Y").json()["fvgs"] == []
    assert loads == ["D_6M", "D_1Y"]


def test_viewer_chart_cache_expires_after_the_configured_ttl(chart_loads, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("data.viewer_chart_cache._monotonic", lambda: clock["t"])
    monkeypatch.setattr(settings, "viewer_chart_cache_seconds", 60)
    viewer = TestClient(main.app)
    viewer.get("/api/tickers/TRK/chart")
    clock["t"] += 59
    viewer.get("/api/tickers/TRK/chart")
    assert len(chart_loads) == 1
    clock["t"] += 2
    viewer.get("/api/tickers/TRK/chart")
    assert len(chart_loads) == 2


def test_the_ttl_is_env_configurable_and_zero_turns_the_cache_off(chart_loads, monkeypatch):
    monkeypatch.setattr(settings, "viewer_chart_cache_seconds", 0)
    viewer = TestClient(main.app)
    viewer.get("/api/tickers/TRK/chart")
    viewer.get("/api/tickers/TRK/chart")
    assert len(chart_loads) == 2


def test_an_admin_chart_is_always_live_and_does_not_fill_the_viewer_cache(chart_loads, client_for):
    admin = client_for("admin")
    admin.get("/api/tickers/TRK/chart")
    admin.get("/api/tickers/TRK/chart")
    assert len(chart_loads) == 2
    TestClient(main.app).get("/api/tickers/TRK/chart")
    assert len(chart_loads) == 3  # the viewer still had a miss


def test_a_failed_chart_load_is_not_cached(monkeypatch, world):
    attempts = []

    async def flaky(ticker, range_key):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("slow")
        return _chart(range_key)

    monkeypatch.setattr(main, "get_chart_data", flaky)
    viewer = TestClient(main.app)
    assert viewer.get("/api/tickers/TRK/chart").status_code == 502
    assert viewer.get("/api/tickers/TRK/chart").status_code == 200
    assert len(attempts) == 2


def test_concurrent_misses_for_the_same_view_share_one_fetch():
    cache, loads = ViewerChartCache(), []

    async def slow():
        loads.append(1)
        await asyncio.sleep(0.05)
        return _chart()

    async def run():
        return await asyncio.gather(*[cache.get("TRK", "D_1Y", slow) for _ in range(8)])

    results = asyncio.run(run())
    assert len(loads) == 1 and all(r.range == "D_1Y" for r in results)


def test_the_cache_is_bounded():
    import data.viewer_chart_cache as module

    cache = ViewerChartCache()

    async def load():
        return _chart()

    async def run():
        for i in range(module.MAX_ENTRIES + 20):
            await cache.get(f"T{i}", "D_1Y", load)

    asyncio.run(run())
    assert len(cache._entries) <= module.MAX_ENTRIES


def test_chart_cache_starts_empty_for_each_test():
    assert viewer_chart_cache._entries == {}


# ---- redaction -----------------------------------------------------------------------------------------------------------------


def test_score_weights_hides_the_raw_recompute_error_from_a_viewer_but_not_an_admin(world, client_for):
    secret = "The recompute worker could not be started: [Errno 2] No such file or directory: '/home/shen/fathom/backend/worker.py'"
    with Session(world.engine) as s:
        s.add(ScoreRecomputeRun(state="failed", trigger="weights", started_at=datetime.now(), finished_at=datetime.now(), heartbeat_at=datetime.now(), processed=0,
                                total=10, failed=0, error=secret))
        s.commit()
    viewer = TestClient(main.app).get("/api/config/score-weights").json()["recompute"]
    assert viewer["state"] == "failed" and viewer["error"] is None and viewer["total"] == 10
    assert secret not in str(viewer)
    assert client_for("admin").get("/api/config/score-weights").json()["recompute"]["error"] == secret


def test_etf_overview_reason_is_operational_detail_for_admins_only(world, client_for):
    viewer = TestClient(main.app).get("/api/tickers/EEE/etf-overview").json()
    assert viewer["status"] == "unavailable" and viewer["reason"] is None
    assert world.calls == []
    assert client_for("admin").get("/api/tickers/EEE/etf-overview").json()["reason"] == "fetch_failed"


def test_response_models_can_drop_their_raw_error_text():
    run = RecomputeRunOut(id=1, state="failed", trigger="x", started_at=datetime.now(), processed=0, total=1, failed=1, error="boom /srv/x.py")
    assert run.for_viewer().error is None and run.for_viewer().state == "failed" and run.error == "boom /srv/x.py"
    summary = RecomputeSummary(processed=1, failed=1, duration_seconds=1.0, failures=[("AAPL", "KeyError: 'secret'")])
    assert summary.for_viewer().failures == [("AAPL", "")]
    add = UniverseAddOut.model_construct(status=None, changed=True, error="ReadTimeout: https://x?apikey=K", message="m")
    assert add.for_viewer().error is None and add.for_viewer().message == "m"


def test_viewer_cannot_read_settings_only_endpoints_but_an_admin_can(world, client_for):
    paths = [f"/api/config/{n}" for n in ("discount-rate", "discount-rates", "liquidity-zones", "reit-dividend-yield", "weinstein")]
    viewer = client_for("viewer")
    for path in paths:
        assert viewer.get(path).status_code == 403, path
    assert world.calls == [] and world.writes == []
    admin = client_for("admin")
    for path in paths:
        assert admin.get(path).status_code == 200, path
    # The shared config reads (ticker pages and the Screener use them) stay open to a viewer.
    for path in ("/api/config/moat", "/api/config/score-weights"):
        assert viewer.get(path).status_code == 200, path


def test_viewer_cannot_read_operational_endpoints(world):
    viewer = TestClient(main.app)
    for path in ("/api/config/cron-health", "/api/config/data-source-health", "/api/config/data-groups",
                 "/api/tickers/TRK/financials/cash-flow-cell-check?field=interestPaid&period_end=2025-12-31"):
        response = viewer.get(path)
        assert response.status_code == 403, path
    assert world.calls == [] and world.writes == []
