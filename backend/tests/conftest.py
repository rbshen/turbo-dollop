"""Session-scoped safety net: fails loudly, immediately, if any test writes
to the REAL `core.db.engine` instead of a properly-isolated in-memory test
engine -- the exact root cause of the PEP/ACME fixture-contamination
incidents (see CLAUDE.md's "Ad-hoc reproduction scripts must not touch the
real database"). A missing `monkeypatch.setattr(some_module, "engine",
test_engine)` now surfaces as an immediate, loud test failure with a clear
message, instead of a silent write that can sit undetected in production
for days.

Hooks the database driver itself (`before_cursor_execute`), not
`cache.get_or_fetch` specifically -- this catches every write path,
including ones this comment can't anticipate, not just the one call site
the original incidents happened to go through.

Registered once, for the pytest process's entire lifetime, via a
session-scoped autouse fixture. This never affects the real app: a normal
interactive run or a cron job never imports pytest and never constructs
this fixture, so `core.db.engine` never gets this listener attached
outside of a pytest session."""

import logging
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

import core.data_source_health as data_source_health
import data.ticker_summary as ticker_summary
from clients.fmp_client import fmp_client
from core.config import BASE_DIR, settings
from core.db import engine as real_engine
from core.models import DataSourceHealth

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "REPLACE")
# Schema changes are blocked too (2026-10-10): the guard used to let ALTER TABLE ... DROP COLUMN through, so a test that booted the
# app (lifespan -> init_db) against the real file dropped real columns. Only the real engine carries this listener; an in-memory
# or temp-file test engine can still create and alter its own tables.
_DDL_PREFIXES = ("ALTER", "DROP", "CREATE", "REINDEX", "VACUUM")


def _forbid_write(conn, cursor, statement, parameters, context, executemany):
    normalized = statement.strip().upper()
    if normalized.startswith(_DDL_PREFIXES):
        raise RuntimeError(
            "A test attempted a SCHEMA change on the REAL core.db.engine "
            f"(statement: {statement[:200]!r}). Something ran init_db() or a migration against fathom.db -- "
            "isolate its engine (see CLAUDE.md's \"Ad-hoc reproduction scripts must not touch the real database\")."
        )
    if normalized.startswith(_WRITE_PREFIXES):
        raise RuntimeError(
            "A test attempted to write to the REAL core.db.engine "
            f"(statement: {statement[:200]!r}). Some module's `engine` "
            "reference is missing its monkeypatch -- see CLAUDE.md's "
            '"Ad-hoc reproduction scripts must not touch the real '
            'database" for the incident this guards against.'
        )


_REAL_LOG_DIR = (BASE_DIR / "logs").resolve()


@pytest.fixture(autouse=True, scope="session")
def _forbid_writes_to_production_logs():
    """No test may write into backend/logs. Every job's `main()` calls `core.logging_config.configure_logging(LOG_PATH)`,
    which does `logging.basicConfig(force=True)` with a FileHandler on the real log file; a test that runs a `main()`
    without patching that module's LOG_PATH therefore wrote its own lines, and every later test's lines too (the root
    logger keeps the handler for the rest of the session), into production logs (2026-10-03: the three index-list
    refresh logs and the sector-heatmap log, lines dated 2026-10-30). Redirecting at the handler, not per module, also
    covers a job imported late and any LOG_PATH style. A FileHandler for any path outside backend/logs (tmp_path, as
    tests/test_logging_config.py uses) is untouched, so configure_logging itself stays testable. Session-scoped, so it
    patches `logging.FileHandler` once and restores it at the end."""
    original = logging.FileHandler

    class _GuardedFileHandler(original):
        def __init__(self, filename, *args, **kwargs):
            if _REAL_LOG_DIR in Path(filename).resolve().parents:
                filename = os.devnull
            super().__init__(filename, *args, **kwargs)

    logging.FileHandler = _GuardedFileHandler
    yield
    logging.FileHandler = original


@pytest.fixture(autouse=True, scope="session")
def _forbid_writes_to_real_db():
    event.listen(real_engine, "before_cursor_execute", _forbid_write)
    yield
    event.remove(real_engine, "before_cursor_execute", _forbid_write)


@pytest.fixture(autouse=True)
def _isolate_data_source_health_engine(monkeypatch):
    """core.data_source_health.record_success is reached from
    FMPClient.get, which is exercised for real (not just monkeypatched
    away) by test_fmp_client.py via MockTransport --
    so this needs the same fresh-in-memory-engine isolation every other
    per-module `engine` reference gets, applied once globally here rather
    than per test file, since so many otherwise-unrelated tests reach
    that function. record_success's own try/except swallows any
    write failure (same reasoning as cron_heartbeat's swallowed writes) --
    safe specifically because this fixture means tests never touch the
    real engine here in the first place, so the swallow can't hide a
    missing per-test monkeypatch the way it could for an unisolated write
    path.

    Function-scoped (a fresh engine per test), not session-scoped -- a
    single shared engine across the whole suite would let one test's
    incidental record_success("fmp") call (e.g. any test_fmp_client.py
    case) leak a DataSourceHealth row into a completely unrelated test
    (e.g. test_data_source_status.py's own threshold assertions),
    producing order-dependent flakiness.

    StaticPool + check_same_thread=False, not a bare `sqlite://` -- a
    plain in-memory engine hands each new connection its own separate
    database, and TestClient(app) runs the endpoint handler in a worker
    thread (see test_cron_health_endpoint.py's own `_fresh_engine` for the
    same reasoning), which would otherwise see an empty, unseeded database
    even though this fixture's own Session calls populated one."""
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(test_engine, tables=[DataSourceHealth.__table__])
    monkeypatch.setattr(data_source_health, "engine", test_engine)
    return test_engine


@pytest.fixture(autouse=True)
def _isolate_data_groups_engine(monkeypatch):
    """core.data_groups reads/lazy-seeds its DB-backed group toggles on the
    first FMPClient.get / cache gate check, so every test needs its own
    fresh in-memory engine for it (same reasoning as
    _isolate_data_source_health_engine). The lazy seed gives the documented
    defaults: master on, plan Ultimate, every group live except `news` and
    `institutional_ownership` (both shelved, default off) -- a test
    exercising one of those features, or using one as a generic example
    group, turns it on via data_groups.set_group_enabled("news", True) /
    data_groups.set_group_enabled("institutional_ownership", True)."""
    import core.data_groups as data_groups

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(data_groups, "engine", test_engine)
    data_groups.invalidate_cache()
    data_groups._last_success_write.clear()
    yield test_engine
    data_groups.invalidate_cache()


@pytest.fixture(autouse=True)
def _isolate_score_weights_cache():
    """data.score_weights keeps a 5 s snapshot keyed on id(engine); a test's engine can reuse a freed engine's id, so every
    test starts and ends with it dropped (an unseeded database serves the defaults)."""
    import data.score_weights as score_weights

    score_weights.invalidate_cache()
    yield
    score_weights.invalidate_cache()


@pytest.fixture(autouse=True)
def recompute_launches(monkeypatch):
    """No test ever starts the real recompute worker (a subprocess): data.score_recompute.launcher records what WOULD have been
    launched instead. A test of the worker itself runs pipeline.score_recompute_job.run_job in-process."""
    import data.score_recompute as score_recompute

    launches: list[tuple[int, list[str] | None]] = []
    monkeypatch.setattr(score_recompute, "launcher", lambda run_id, tickers: launches.append((run_id, tickers)))
    return launches


@pytest.fixture(autouse=True)
def _block_live_fmp_daily_bars(monkeypatch):
    """The shared-bars-cache daily path now tries FMP first (FMPDailySource ->
    fmp_client.get_historical_price_eod). No test may reach the real network
    through it: by default that call fails as a transport error, so every
    ticker is simply unserved. A test exercising FMP builds FMPDailySource(client=<fake>) or patches the method itself."""
    import httpx

    from clients.fmp_client import fmp_client

    async def _blocked(*_args, **_kwargs):
        raise httpx.ConnectError("live FMP daily-bar fetch blocked in tests")

    monkeypatch.setattr(fmp_client, "get_historical_price_eod", _blocked)


@pytest.fixture(autouse=True)
def _isolate_tracked_universe_engine(monkeypatch):
    """GET /summary records a page view (data.tracked_universe.record_ticker_view, which swallows its own
    errors), so every test reaching that route needs its own in-memory TickerView table: otherwise the
    write would hit the real engine, trip the write guard above and be swallowed, hiding a real bug."""
    import data.tracked_universe as tracked_universe
    import data.universe_membership as universe_membership

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(tracked_universe, "engine", engine)
    # The opt-in universe API (data/universe_membership.py): its status read, and the best-effort ETF row write that
    # a watchlist add triggers, must never see the real database from an unrelated watchlist/ETF test.
    monkeypatch.setattr(universe_membership, "engine", engine)
    return engine


@pytest.fixture(autouse=True)
def _isolate_long_history_engine(monkeypatch):
    """clients/long_history_bars.py reads/writes its own table (LongHistoryBars) on its own
    `engine` reference: every test gets a fresh in-memory one, so none can touch (or depend on
    the existence of that table in) the real database. Tests of modules that call it
    (chart_data, analyst_ratings_data) reach FMP only through the blocked singleton above."""
    import clients.daily_bar_sources as daily_bar_sources
    import clients.long_history_bars as long_history_bars

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(long_history_bars, "engine", engine)
    monkeypatch.setattr(daily_bar_sources, "engine", engine)  # the exchange lookup route_by_source/group_for read


@pytest.fixture(autouse=True)
def _forbid_real_http(monkeypatch, request):
    """No test may make a real outbound HTTP call. fmp_client (and sec_edgar) build a fresh `httpx.AsyncClient` per request,
    and a real one sends through `httpx.AsyncHTTPTransport.handle_async_request`: that method is blocked here, so the call
    raises at once with the test id and URL. `httpx.MockTransport` (test_fmp_client.py and the other FMP client tests) is a
    different class and is untouched. The error is also recorded and re-raised as a failure at teardown, so a caller that
    swallows it (safe_fetch, `except Exception`) cannot hide a leaking test: a test that reaches FMP must mock the client method."""
    import httpx

    leaks: list[str] = []

    async def _blocked(self, req):
        url = req.url.copy_remove_param("apikey")  # never print the key
        message = f"{request.node.nodeid} made a real HTTP call to {req.method} {url}: mock the FMP client method it reaches"
        leaks.append(message)
        raise RuntimeError(message)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked)
    yield
    if leaks:
        pytest.fail("; ".join(leaks), pytrace=False)


@pytest.fixture(autouse=True)
def _default_earnings_fetch(monkeypatch):
    """Every statement-grain data module (step1-5_data.py, ratios_data.py,
    segmentation_data.py, financials_data.py, ticker_summary.py) now resolves
    each ticker's most recent reported earnings date
    (helpers.earnings.resolve_most_recent_earnings_date) before deciding cache
    freshness -- see core/cache.py::get_or_fetch_earnings_aware. fmp_client is
    a true singleton (`clients/fmp_client.py::fmp_client = FMPClient()`), so
    patching it once here applies across every module that imported it by
    reference. Defaults get_earnings to an empty response so a test exercising
    a live (non-cache_only) fetch path doesn't silently make a real network
    call just because it doesn't itself care about earnings-date-aware
    staleness -- an empty list makes most_recent_reported_earnings_date return
    None, which falls back to the same flat-window behavior these tests'
    existing call-count assertions were already written against. A test that
    DOES care sets its own monkeypatch.setattr(fmp_client, "get_earnings", ...)
    afterward, which simply overrides this default (same object, last write
    wins) -- no conflict."""

    async def _default_get_earnings(ticker):
        return []

    monkeypatch.setattr(fmp_client, "get_earnings", _default_get_earnings)


@pytest.fixture(autouse=True)
def _default_last_close_cache(monkeypatch):
    """get_summary's price fallback (data/ticker_summary.py) reads the nightly last-close
    cache (data.last_close_data.get_cached_last_close) whenever the live FMP quote is
    unavailable and cache_only is False. That read goes to the real core.db.engine, so any
    test calling get_summary() with a failing/absent quote would otherwise see whatever the
    real DB holds. Defaults to "nothing cached"; a test that cares patches
    ticker_summary.get_cached_last_close itself."""
    import data.ticker_score as ticker_score

    monkeypatch.setattr(ticker_summary, "get_cached_last_close", lambda ticker: None)
    monkeypatch.setattr(ticker_score, "get_cached_last_close", lambda ticker: None)  # the Screener row's price (same default)


@pytest.fixture(autouse=True)
def _isolate_corporate_events_engine(monkeypatch):
    """data/chart_events_data.py reads the FMP-backed CorporateEvent cache first
    (data.corporate_events_data.read_cached_chart_events), which would otherwise see the
    REAL core.db.engine's populated cache from any test reaching fetch_chart_events. Every
    test gets an empty in-memory cache; the cache's own tests seed theirs on top."""
    from sqlmodel import SQLModel, create_engine

    import data.corporate_events_data as corporate_events_data

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(corporate_events_data, "engine", engine)


@pytest.fixture(autouse=True)
def _default_flags_enabled(monkeypatch):
    """Pins cron_health_enabled to its documented `True` default for the
    whole test session, regardless of what this developer's own local .env
    says. `settings` (core/config.py) is a true module-level singleton, so
    patching it once here is visible everywhere. FMP on/off is no longer an
    env flag -- see _isolate_data_groups_engine above, which gives every test
    a fresh DB-backed group config (master on, all groups live except the
    shelved `news`). A test wanting a disabled state calls
    core.data_groups.set_master/set_group_enabled itself."""
    monkeypatch.setattr(settings, "cron_health_enabled", True)
