import httpx
from fastapi.testclient import TestClient

import clients.fmp_client as fmp_client_module
import core.data_groups as dg
from core.main import app


def _by_key(body):
    return {g["key"]: g for g in body["groups"]}


def test_get_lists_every_group_with_defaults():
    with TestClient(app) as client:
        body = client.get("/api/config/data-groups").json()
    assert body["master_on"] is True
    assert body["fmp_plan"] == "Ultimate"
    assert body["tiers"] == ["Starter", "Premium", "Ultimate"]
    groups = _by_key(body)
    assert list(groups) == list(dg.GROUPS)
    assert groups["fundamentals"]["state"] == "live"
    assert groups["fundamentals"]["required_tier"] == "Premium"
    assert groups["fundamentals"]["tier_verified"] is False
    assert groups["insider"]["state"] == "cached_only" and groups["insider"]["enabled"] is False
    assert groups["daily_prices"]["wired"] is True and groups["intraday_bars"]["wired"] is False
    assert "News tab" in groups["news"]["feeds"]


def test_old_fmp_status_endpoint_is_gone():
    with TestClient(app) as client:
        assert client.get("/api/config/fmp-status").status_code == 404


def test_master_switch_makes_every_group_cached_only_and_untoggleable():
    with TestClient(app) as client:
        body = client.put("/api/config/data-groups/master", json={"master_on": False}).json()
        assert body["master_on"] is False
        for g in body["groups"]:
            assert g["state"] == ("using_fallback" if g["key"] in ("daily_prices", "daily_prices_long", "daily_prices_intl") else "cached_only") and g["reason"] == "master_off" and g["can_toggle"] is False
        body = client.put("/api/config/data-groups/master", json={"master_on": True}).json()
    assert _by_key(body)["fundamentals"]["state"] == "live"


def test_toggle_a_group_and_edit_tier_with_verified_tick():
    with TestClient(app) as client:
        body = client.put("/api/config/data-groups/news", json={"enabled": False}).json()
        assert _by_key(body)["news"]["state"] == "cached_only"
        body = client.put("/api/config/data-groups/news", json={"required_tier": "Premium", "tier_verified": True}).json()
        news = _by_key(body)["news"]
        assert news["required_tier"] == "Premium" and news["tier_verified"] is True
        body = client.put("/api/config/data-groups/news", json={"tier_verified": False}).json()
    assert _by_key(body)["news"]["tier_verified"] is False


def test_group_above_plan_reads_not_on_plan():
    with TestClient(app) as client:
        body = client.put("/api/config/data-groups/plan", json={"fmp_plan": "Starter"}).json()
    groups = _by_key(body)
    assert groups["fundamentals"]["state"] == "not_on_plan" and groups["fundamentals"]["can_toggle"] is False
    assert groups["profile_quote"]["state"] == "live"


def test_validation_and_unknown_group():
    with TestClient(app) as client:
        assert client.put("/api/config/data-groups/nope", json={"enabled": True}).status_code == 404
        assert client.put("/api/config/data-groups/news", json={"required_tier": "Gold"}).status_code == 422
        assert client.put("/api/config/data-groups/plan", json={"fmp_plan": "Gold"}).status_code == 422


def test_restricted_and_failing_states_and_key_problem_surface():
    dg.mark_restricted("segmentation", "simulated 402")
    for _ in range(dg.FAILING_AFTER_CONSECUTIVE):
        dg.record_group_failure("news", "HTTP 500")
    dg.set_key_problem("HTTP 401 from /profile")
    with TestClient(app) as client:
        body = client.get("/api/config/data-groups").json()
    groups = _by_key(body)
    assert groups["segmentation"]["state"] == "restricted" and groups["segmentation"]["restricted_since"]
    assert groups["news"]["state"] == "failing" and groups["news"]["last_error"] == "HTTP 500"
    assert body["key_problem_detail"] == "HTTP 401 from /profile"


def test_editing_the_plan_reprobes_restricted_groups(monkeypatch):
    dg.mark_restricted("news", "simulated 402")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[{"ok": True}]))
    real = httpx.AsyncClient
    monkeypatch.setattr(
        fmp_client_module.httpx, "AsyncClient", lambda *a, **k: real(**{**k, "transport": transport})
    )
    with TestClient(app) as client:
        body = client.put("/api/config/data-groups/plan", json={"fmp_plan": "Ultimate"}).json()
    assert _by_key(body)["news"]["state"] == "live"


def test_daily_prices_off_reads_using_fallback_not_cached_only():
    """daily_prices has a live fallback chain (Massive -> Yahoo) until P6, so off
    means "skip FMP, use the fallback", never the cache-only chip."""
    with TestClient(app) as client:
        body = client.get("/api/config/data-groups").json()
        assert _by_key(body)["daily_prices"]["state"] == "live"
        body = client.put("/api/config/data-groups/daily_prices", json={"enabled": False}).json()
        g = _by_key(body)["daily_prices"]
        assert g["state"] == "using_fallback" and g["falls_back"] is True and g["reason"] == "user_off"
        client.put("/api/config/data-groups/daily_prices", json={"enabled": True})
        body = client.put("/api/config/data-groups/master", json={"master_on": False}).json()
        assert _by_key(body)["daily_prices"]["state"] == "using_fallback"
        assert _by_key(body)["news"]["state"] == "cached_only"
