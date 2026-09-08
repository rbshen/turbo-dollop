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
from sqlalchemy import event

import data.ticker_summary as ticker_summary
from clients.fmp_client import fmp_client
from core.config import settings
from core.db import engine as real_engine

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
    settings.fmp_enabled is False and cache_only is False -- which is this
    environment's own real default (.env has FMP_ENABLED=false), so any
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
    """Pins fmp_enabled/cron_health_enabled to their documented `True`
    defaults for the whole test session, regardless of what this
    developer's own local .env says. `settings` (core/config.py) is a true
    module-level singleton -- every consumer across the codebase does
    `from core.config import settings` and reads the attribute off this
    exact same object, so patching it once here, on the shared object
    itself, is visible everywhere, the same singleton-patching convention
    _default_earnings_fetch above already relies on for fmp_client.

    Root-caused 2026-09-08: this environment's real .env has had
    FMP_ENABLED=false/CRON_HEALTH_ENABLED=false since 2026-08-18 (a
    deliberate, correct operational choice -- the FMP subscription really
    is paused), but ~155 of this suite's tests never accounted for that,
    assuming the documented `True` defaults instead of monkeypatching them
    explicitly. Confirmed via `git stash`-style bisection across multiple
    sessions that this reads as "pre-existing, unrelated failures" every
    time a feature branch's tests are checked against `main` -- true in
    the narrow sense that no feature change caused it, but the real count
    (159, not the "~7" once assumed) was never actually verified plain
    until this investigation, because those still-passing local ~7-failure
    baselines were themselves generated in dev sessions with these flags
    overridden to True in the shell, not by an unmodified `uv run pytest`.

    A test that specifically wants to exercise the disabled state already
    sets its own monkeypatch.setattr(<module>.settings, "fmp_enabled"/
    "cron_health_enabled", False) afterward (e.g. test_health.py's
    test_fmp_status_reflects_the_flag_when_disabled, test_cron_health_
    endpoint.py's test_cron_health_disabled_reports_enabled_false_and_
    no_jobs) -- same object, last write wins, so this default never
    conflicts with those, exactly like _default_earnings_fetch above.
    Verified safe to flip broadly: every one of the ~155 previously-FMP-
    affected tests already monkeypatches fmp_client at the function level
    (or, for test_fmp_client.py, at the httpx transport level via
    MockTransport) rather than depending on live FMP data -- confirmed
    empirically by running the full suite with FMP_ENABLED=true and a
    deliberately invalid FMP_API_KEY: identical result (0 failures) to a
    real key, proving no test's outcome depends on a genuine FMP
    response."""
    monkeypatch.setattr(settings, "fmp_enabled", True)
    monkeypatch.setattr(settings, "cron_health_enabled", True)
