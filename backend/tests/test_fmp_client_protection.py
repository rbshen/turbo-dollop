"""Outbound FMP protection in FMPClient (clients/fmp_client.py): the API process's token bucket and the 401/403 circuit
breaker. MockTransport only, no network."""

import asyncio
import time

import httpx
import pytest

import clients.fmp_client as fmp_client_module
import core.data_groups as dg
from clients.fmp_client import FMPCircuitOpenError, FMPClient, FMPLocalRateLimitError
from core.cache import safe_fetch


def _install(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(**kwargs)

    monkeypatch.setattr(fmp_client_module.httpx, "AsyncClient", factory)


class _Script:
    """Answers with the next status from `statuses` (the last one repeats) and counts the requests."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.calls = 0

    def __call__(self, request):
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return httpx.Response(status, json={"symbol": "AAPL"} if status < 400 else {"Error Message": "nope"})


def _get(client):
    return asyncio.run(client.get("/profile", {"symbol": "AAPL"}))


# ---- token bucket ----------------------------------------------------------------------------------------------------


def test_bucket_is_off_by_default_and_for_cron(monkeypatch):
    script = _Script(200)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x")
    assert client._bucket is None  # nothing but the API lifespan turns it on
    start = time.monotonic()
    for _ in range(60):
        _get(client)
    assert script.calls == 60 and time.monotonic() - start < 5


def test_bucket_passes_a_burst_then_paces(monkeypatch):
    script = _Script(200)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x")
    client.enable_api_rate_limit(rate_per_minute=600, burst=3, max_wait=5)  # 10 per second, burst 3

    async def run():
        t0 = time.monotonic()
        for _ in range(3):
            await client.get("/profile", {"symbol": "AAPL"})
        burst_elapsed = time.monotonic() - t0
        await client.get("/profile", {"symbol": "AAPL"})  # the 4th must wait ~0.1s for a token
        return burst_elapsed, time.monotonic() - t0

    burst_elapsed, total = asyncio.run(run())
    assert burst_elapsed < 0.09
    assert total >= 0.08


def test_bucket_fails_fast_instead_of_queueing_past_max_wait(monkeypatch):
    script = _Script(200)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x")
    client.enable_api_rate_limit(rate_per_minute=6, burst=1, max_wait=2)  # one token per 10s
    _get(client)
    with pytest.raises(FMPLocalRateLimitError):
        _get(client)
    assert script.calls == 1  # the refused call never reached the network
    # a handled fetch failure like any other: safe_fetch swallows httpx.HTTPError
    assert asyncio.run(safe_fetch("profile", client.get("/profile", {"symbol": "AAPL"}))) == {}


def test_rate_of_zero_leaves_the_bucket_off():
    client = FMPClient(api_key="x")
    client.enable_api_rate_limit(rate_per_minute=0)
    assert client._bucket is None


def test_api_lifespan_enables_and_then_disables_the_bucket(monkeypatch):
    from fastapi.testclient import TestClient

    import core.main as main

    monkeypatch.setattr(main.settings, "fmp_api_rate_per_minute", 90, raising=False)
    monkeypatch.setattr(fmp_client_module.settings, "fmp_api_rate_per_minute", 90)
    with TestClient(main.app):
        assert main.fmp_client._bucket is not None
    assert main.fmp_client._bucket is None


def test_cron_entry_points_never_enable_the_bucket():
    # Only core/main.py's lifespan may call enable_api_rate_limit: a cron job is its own process and keeps its own pacing.
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    callers = {
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if ".venv" not in p.parts and "tests" not in p.parts and "enable_api_rate_limit(" in p.read_text()
    }
    assert callers == {"clients/fmp_client.py", "core/main.py"}


# ---- circuit breaker -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("code", [401, 403])
def test_breaker_opens_after_n_consecutive_auth_failures_and_stops_sending(monkeypatch, code):
    script = _Script(code)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x", auth_breaker_threshold=3, auth_breaker_cooldown_seconds=60)
    for _ in range(3):
        with pytest.raises(httpx.HTTPStatusError):
            _get(client)
    assert client.auth_breaker_open and script.calls == 3
    with pytest.raises(FMPCircuitOpenError) as exc:
        _get(client)
    assert script.calls == 3  # nothing was sent
    assert "apikey" not in str(exc.value)
    # a handled error: safe_fetch treats it as a failed fetch, no exception reaches the caller
    assert asyncio.run(safe_fetch("profile", client.get("/profile", {"symbol": "AAPL"}))) == {}


def test_breaker_surfaces_through_the_key_problem_banner(monkeypatch):
    _install(monkeypatch, _Script(401))
    client = FMPClient(api_key="x", auth_breaker_threshold=2, auth_breaker_cooldown_seconds=60)
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            _get(client)
    snap = dg.get_snapshot()
    assert snap.key_problem_at is not None
    assert "paused" in snap.key_problem_detail and "2 in a row" in snap.key_problem_detail
    assert all(g.status == "ok" for g in snap.groups.values())  # no group blamed


def test_a_success_resets_the_run(monkeypatch):
    script = _Script(401, 401, 200, 401, 401, 200)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x", auth_breaker_threshold=3, auth_breaker_cooldown_seconds=60)
    for expected in (401, 401, 200, 401, 401, 200):
        if expected == 200:
            _get(client)
        else:
            with pytest.raises(httpx.HTTPStatusError):
                _get(client)
    assert not client.auth_breaker_open and client._auth_failures == 0


def test_a_402_resets_the_run_but_429_and_5xx_do_not_count_or_reset(monkeypatch):
    script = _Script(401, 500, 401, 402, 401)
    _install(monkeypatch, script)
    monkeypatch.setattr(fmp_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.0)
    client = FMPClient(api_key="x", auth_breaker_threshold=3, auth_breaker_cooldown_seconds=60)
    client._note_status(401, "/a")
    client._note_status(500, "/a")
    client._note_status(429, "/a")
    assert client._auth_failures == 1
    client._note_status(402, "/a")
    assert client._auth_failures == 0


def test_breaker_allows_a_trial_after_the_cooldown_and_closes_on_success(monkeypatch):
    script = _Script(401, 401, 200)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x", auth_breaker_threshold=2, auth_breaker_cooldown_seconds=0.2)
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            _get(client)
    with pytest.raises(FMPCircuitOpenError):
        _get(client)
    time.sleep(0.25)
    assert _get(client) == {"symbol": "AAPL"}  # the trial went through and succeeded
    assert not client.auth_breaker_open and client._auth_failures == 0
    assert _get(client) == {"symbol": "AAPL"}


def test_a_failed_trial_reopens_the_breaker_at_once(monkeypatch):
    script = _Script(401)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x", auth_breaker_threshold=2, auth_breaker_cooldown_seconds=0.2)
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            _get(client)
    time.sleep(0.25)
    with pytest.raises(httpx.HTTPStatusError):  # the trial: sent, answered 401
        _get(client)
    assert script.calls == 3
    with pytest.raises(FMPCircuitOpenError):  # reopened without needing N more failures
        _get(client)
    assert script.calls == 3


def test_breaker_threshold_zero_is_off(monkeypatch):
    script = _Script(401)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x", auth_breaker_threshold=0)
    for _ in range(10):
        with pytest.raises(httpx.HTTPStatusError):
            _get(client)
    assert script.calls == 10 and not client.auth_breaker_open


def test_probes_respect_the_breaker(monkeypatch):
    script = _Script(401)
    _install(monkeypatch, script)
    client = FMPClient(api_key="x", auth_breaker_threshold=2, auth_breaker_cooldown_seconds=60)
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            _get(client)
    calls = script.calls
    assert asyncio.run(client.probe_group("profile_quote")) == "inconclusive"
    assert script.calls == calls


def test_default_singleton_reads_the_settings_defaults():
    assert fmp_client_module.fmp_client.auth_breaker_threshold == fmp_client_module.settings.fmp_auth_breaker_threshold == 5
    assert fmp_client_module.settings.fmp_api_rate_per_minute < 300  # comfortably under the Starter plan limit
