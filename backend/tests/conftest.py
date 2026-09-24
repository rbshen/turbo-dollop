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

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

import core.data_source_health as data_source_health
import data.ticker_summary as ticker_summary
from clients.fmp_client import fmp_client
from core.config import settings
from core.db import engine as real_engine
from core.models import DataSourceHealth

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "REPLACE")


def _forbid_write(conn, cursor, statement, parameters, context, executemany):
    normalized = statement.strip().upper()
    if normalized.startswith(_WRITE_PREFIXES):
        raise RuntimeError(
            "A test attempted to write to the REAL core.db.engine "
            f"(statement: {statement[:200]!r}). Some module's `engine` "
            "reference is missing its monkeypatch -- see CLAUDE.md's "
            '"Ad-hoc reproduction scripts must not touch the real '
            'database" for the incident this guards against.'
        )


@pytest.fixture(autouse=True, scope="session")
def _forbid_writes_to_real_db():
    event.listen(real_engine, "before_cursor_execute", _forbid_write)
    yield
    event.remove(real_engine, "before_cursor_execute", _forbid_write)


@pytest.fixture(autouse=True)
def _isolate_data_source_health_engine(monkeypatch):
    """core.data_source_health.record_success is reached from
    FMPClient.get/YahooClient.get_history, both of which are exercised for
    real (not just monkeypatched away) by test_fmp_client.py/
    test_yahoo_client.py via MockTransport/a monkeypatched yf.download --
    so this needs the same fresh-in-memory-engine isolation every other
    per-module `engine` reference gets, applied once globally here rather
    than per test file, since so many otherwise-unrelated tests reach one
    of those two functions. record_success's own try/except swallows any
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
    defaults: master on, plan Ultimate, every group live except `insider`
    (shelved, default off) -- a test exercising the insider feature turns it
    on via data_groups.set_group_enabled("insider", True)."""
    import core.data_groups as data_groups

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(data_groups, "engine", test_engine)
    data_groups.invalidate_cache()
    data_groups._last_success_write.clear()
    yield test_engine
    data_groups.invalidate_cache()


@pytest.fixture(autouse=True)
def _block_live_fmp_daily_bars(monkeypatch):
    """The shared-bars-cache daily path now tries FMP first (FMPDailySource ->
    fmp_client.get_historical_price_eod). Legacy tests written against the
    Massive/Yahoo chain must never reach the real network through it: by
    default that call fails as a transport error, so every ticker falls
    through to the fallback chain exactly as before. A test exercising FMP
    builds FMPDailySource(client=<fake>) or patches the method itself."""
    import httpx

    from clients.fmp_client import fmp_client

    async def _blocked(*_args, **_kwargs):
        raise httpx.ConnectError("live FMP daily-bar fetch blocked in tests")

    monkeypatch.setattr(fmp_client, "get_historical_price_eod", _blocked)


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
def _default_yahoo_price_history(monkeypatch):
    """get_summary's FMP-disabled price fallback (data/ticker_summary.py)
    calls clients.yahoo_cache.get_or_fetch_price_history whenever
    the profile_quote group is not live and cache_only is False, so any
    test calling get_summary() non-cache_only would otherwise silently
    reach the real Yahoo fetch / real core.db.engine (caught by
    _forbid_writes_to_real_db above) purely because it doesn't itself care
    about this feature. Defaults to an empty list (same "no Yahoo data,
    fall back to whatever's already resolved" degradation
    compute_and_store_trend_analysis's own callers already handle) so
    existing tests are unaffected; a test that DOES care sets its own
    monkeypatch.setattr(ticker_summary, "get_or_fetch_price_history", ...)
    afterward, which simply overrides this default."""

    async def _default_get_or_fetch_price_history(ticker, period="2y", cache_only=False):
        return []

    monkeypatch.setattr(ticker_summary, "get_or_fetch_price_history", _default_get_or_fetch_price_history)


@pytest.fixture(autouse=True)
def _default_flags_enabled(monkeypatch):
    """Pins cron_health_enabled to its documented `True` default for the
    whole test session, regardless of what this developer's own local .env
    says. `settings` (core/config.py) is a true module-level singleton, so
    patching it once here is visible everywhere. FMP on/off is no longer an
    env flag -- see _isolate_data_groups_engine above, which gives every test
    a fresh DB-backed group config (master on, all groups live except the
    shelved `insider`). A test wanting a disabled state calls
    core.data_groups.set_master/set_group_enabled itself."""
    monkeypatch.setattr(settings, "cron_health_enabled", True)
    # massive_enabled's documented default is True (unlike
    # insider_activity_enabled above), but pinned False here anyway: the
    # ~50+ pre-existing tests exercising clients/shared_bars_cache.py's
    # interval="1d" fetch path (test_shared_bars_cache.py,
    # test_market_breadth_data.py, test_liquidity_zone_data.py,
    # test_nightly_trend_calculation.py, etc.) were all written entirely
    # around Yahoo behavior and mock only yahoo_client -- with
    # massive_enabled left at its True default, get_or_fetch_bars_batch
    # would route through clients/daily_bar_sources.py::MassiveWithYahooFallback,
    # which tries a REAL live Massive/Polygon API call (using the real
    # MASSIVE_API_KEY in backend/.env) before ever falling back to the
    # mocked Yahoo path. In this sandbox that call simply fails fast (no
    # outbound network), so those tests still pass -- but that's an
    # accident of this environment, not a guarantee, and a CI/dev machine
    # WITH network access would make real, non-hermetic API calls on every
    # test run. Pinned False here so the whole suite stays hermetic by
    # default; clients/test_massive_client.py and
    # clients/test_daily_bar_sources.py (which test Massive's own behavior
    # directly, against fully-fake clients/sources) are unaffected, and any
    # test that specifically wants the enabled routing sets it True itself,
    # same last-write-wins convention as every flag above.
    monkeypatch.setattr(settings, "massive_enabled", False)
