"""The Warren replay-anchor headroom (data/warren_watch_data.py::anchor_headroom) and its admin-only banner data on
GET /api/technical-ideas/warren (docs/specs/warren-signals-page.md, "Anchor headroom and re-anchor runbook"). The function is a pure computation from
the nightly slice's start: no DB, no FMP, no clock but the `now` it is given."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import clients.shared_bars_cache as sbc
import core.main as main
import data.warren_watch_data as wwd
from data.warren_watch_data import (
    ANCHOR_DEADLINE_DAYS,
    ANCHOR_URGENT_DAYS,
    ANCHOR_WARNING_DAYS,
    REPLAY_ANCHOR,
    anchor_headroom,
)
from pipeline.backfills import reconcile_warren_events as reconcile

LOOKBACK = 730  # the nightly step's LOOKBACK_DAYS (pinned here on purpose: a change of it must be a conscious one for the thresholds)


def noon_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 17, 0, tzinfo=timezone.utc)  # 12:00-13:00 ET: the same Eastern date


def now_for(days: int) -> datetime:
    """A `now` at which the headroom is exactly `days`: the slice starts (today - 729 days), so today = anchor date - days + 729."""
    return noon_utc(REPLAY_ANCHOR.date() - timedelta(days=days) + timedelta(days=LOOKBACK - 1))


def test_the_thresholds_are_the_documented_ones():
    assert (ANCHOR_WARNING_DAYS, ANCHOR_URGENT_DAYS, ANCHOR_DEADLINE_DAYS) == (300, 270, 180)


def test_headroom_on_2026_10_18_is_361_days_with_the_documented_dates():
    h = anchor_headroom(now=noon_utc(date(2026, 10, 18)))
    assert h.days == 361 and h.level == "none"
    assert h.slice_start == date(2024, 10, 19) and h.anchor == datetime(2025, 10, 15, 15, 30)
    assert (h.warning_date, h.urgent_date, h.deadline_date) == (date(2026, 12, 19), date(2027, 1, 18), date(2027, 4, 17))


def test_the_slice_start_is_the_nightly_steps_own():
    now = noon_utc(date(2026, 10, 18))
    assert anchor_headroom(now=now).slice_start == reconcile.nightly_bars_start(now)


def test_the_headroom_follows_the_lookback(monkeypatch):
    now = noon_utc(date(2026, 10, 18))
    before = anchor_headroom(now=now).days
    monkeypatch.setattr(reconcile, "LOOKBACK_DAYS", LOOKBACK - 100)  # the slice start moves 100 days forward: 100 days less headroom
    assert anchor_headroom(now=now).days == before - 100


@pytest.mark.parametrize(
    "days, level",
    [(361, "none"), (301, "none"), (300, "none"), (299, "warning"), (271, "warning"), (270, "warning"), (269, "urgent"), (180, "urgent"), (100, "urgent")],
)
def test_levels_at_the_300_and_270_boundaries(days, level):
    h = anchor_headroom(now=now_for(days))
    assert h.days == days and h.level == level


def test_the_dates_are_the_days_the_levels_start_and_the_day_the_deadline_is_reached():
    h = anchor_headroom(now=now_for(361))
    day = lambda d: anchor_headroom(now=noon_utc(d))  # noqa: E731
    one = timedelta(days=1)
    assert day(h.warning_date - one).level == "none" and day(h.warning_date).level == "warning"
    assert day(h.urgent_date - one).level == "warning" and day(h.urgent_date).level == "urgent"
    assert day(h.deadline_date).days == ANCHOR_DEADLINE_DAYS and day(h.deadline_date - one).days == ANCHOR_DEADLINE_DAYS + 1


def test_a_date_already_passed_stays_in_the_past():
    h = anchor_headroom(now=now_for(250))  # urgent already
    today = now_for(250).date()
    assert h.level == "urgent" and h.warning_date < h.urgent_date <= today
    assert h.deadline_date == today + timedelta(days=70)


def test_the_threshold_arguments_override_the_rule():
    now = now_for(361)
    assert anchor_headroom(now=now, warning_days=400).level == "warning"
    assert anchor_headroom(now=now, warning_days=400, urgent_days=380).level == "urgent"
    assert anchor_headroom(now=now, anchor=REPLAY_ANCHOR + timedelta(days=100)).days == 461


def test_it_reads_no_database(monkeypatch):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("the headroom must not touch the database")

    monkeypatch.setattr(wwd, "engine", Boom())
    monkeypatch.setattr(sbc, "engine", Boom())
    assert anchor_headroom(now=now_for(299)).level == "warning"


# ---- the endpoint: admin only, nothing extra when the level is none

def at(days: int):
    """Pin the endpoint's headroom to the real function at a chosen `now`."""
    return lambda: anchor_headroom(now=now_for(days))


def get(client=None):
    return (client or TestClient(main.app)).get("/api/technical-ideas/warren")


def test_an_admin_gets_the_warning_banner_data(monkeypatch):
    monkeypatch.setattr(main, "anchor_headroom", at(298))
    body = get().json()["anchor_headroom"]
    assert body["days"] == 298 and body["level"] == "warning"
    assert body["anchor"] == "2025-10-15T15:30:00"
    assert set(body) == {"days", "level", "anchor", "slice_start", "warning_date", "urgent_date", "deadline_date"}
    h = anchor_headroom(now=now_for(298))
    assert (body["warning_date"], body["urgent_date"], body["deadline_date"]) == (h.warning_date.isoformat(), h.urgent_date.isoformat(), h.deadline_date.isoformat())


def test_an_admin_gets_the_urgent_banner_data(monkeypatch):
    monkeypatch.setattr(main, "anchor_headroom", at(250))
    body = get().json()["anchor_headroom"]
    assert body["days"] == 250 and body["level"] == "urgent"


def test_an_admin_gets_nothing_when_the_level_is_none(monkeypatch):
    monkeypatch.setattr(main, "anchor_headroom", at(361))
    assert get().json()["anchor_headroom"] is None


@pytest.mark.auth("viewer")
def test_a_viewer_gets_no_banner_data_and_the_function_is_not_even_called(monkeypatch):
    calls = []

    def spy():
        calls.append(1)
        return anchor_headroom(now=now_for(250))

    monkeypatch.setattr(main, "anchor_headroom", spy)
    response = get()
    assert response.status_code == 200
    assert response.json()["anchor_headroom"] is None and calls == []
