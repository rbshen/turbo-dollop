"""scoring/opportunity_triggers.py: the pure trigger rules of the daily opportunity flags -- which triggers apply to which list, the
knowable-before-the-next-open test, the stage ladder, the pullback ceiling and the separate trigger version."""

from datetime import date, datetime

import pytest

from scoring import opportunity_rules as rules
from scoring import opportunity_triggers as t


def test_applicable_triggers_per_list():
    assert t.applicable_triggers("reversal", {}) == (t.TRIGGER_D1, t.TRIGGER_D2)
    assert t.applicable_triggers("momentum", {}) == (t.TRIGGER_D3,)
    assert t.applicable_triggers("momentum", {"deep_pullback": True}) == (t.TRIGGER_D1, t.TRIGGER_D3)
    assert t.applicable_triggers("momentum", {"deep_pullback": False}) == (t.TRIGGER_D3,)
    assert t.applicable_triggers("other", {}) == ()


def test_the_d1_event_kinds_are_the_weekly_b3_kinds():
    assert t.D1_WARREN_KINDS == rules.B3_WARREN_KINDS


def test_the_trigger_version_is_separate_from_the_list_rules_version():
    assert t.TRIGGERS_VERSION == "1" and all(i.endswith(".v1") for i in t.TRIGGER_IDS)
    assert set(t.TRIGGER_IDS).isdisjoint(rules.RULE_IDS)


def test_the_triggers_hash_moves_with_a_threshold(monkeypatch):
    before = t.triggers_hash()
    monkeypatch.setattr(t, "PULLBACK_MAX_VS_MA_PCT", 6.0)
    assert t.triggers_hash() != before


# --- the knowable-before-the-next-open test (created_at, never the event date) ---------------------------------------------------


NEXT_OPEN = datetime(2026, 10, 13, 13, 30)  # Tuesday 09:30 EDT


@pytest.mark.parametrize(
    "created, knowable",
    [
        (datetime(2026, 10, 13, 1, 20), True),  # the usual: written by the 01:20 job the night after the session
        (datetime(2026, 10, 13, 13, 30), True),  # exactly at the open
        (datetime(2026, 10, 13, 13, 31), False),  # one minute after the open: could not have been acted on at it
        (datetime(2026, 10, 14, 1, 20), False),  # a night late (a profiled Warren Blue that needed the EOD volume)
    ],
)
def test_an_event_is_knowable_only_if_written_before_the_next_open(created, knowable):
    assert t.event_is_knowable(date(2026, 10, 12), created, NEXT_OPEN) is knowable


def test_without_a_calendar_the_next_weekday_open_is_used():
    friday = date(2026, 10, 9)
    assert t.event_is_knowable(friday, datetime(2026, 10, 12, 13, 30), None)  # Monday 13:30 UTC
    assert not t.event_is_knowable(friday, datetime(2026, 10, 12, 13, 31), None)


# --- D2 stage upgrade ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frozen, frozen_pending, stage, pending, expected",
    [
        ("decline", None, "base", None, t.UPGRADE_STAGE),
        ("decline", None, "advance", None, t.UPGRADE_STAGE),
        ("base", None, "advance", None, t.UPGRADE_STAGE),
        ("decline", None, "decline", "advance", t.UPGRADE_PENDING),  # a new pending Advance
        ("base", None, "base", "advance", t.UPGRADE_PENDING),
        ("base", "advance", "base", "advance", None),  # the list row already had the pending Advance
        ("advance", None, "advance", None, None),  # a fresh Advance on the Reversal list: nothing above it
        ("advance", None, "top", None, None),  # Top is not an upgrade
        ("base", None, "decline", None, None),  # a downgrade
        ("decline", None, "decline", None, None),
        ("base", None, "advance", "advance", t.UPGRADE_STAGE),  # stage up wins over the pending flag
        ("base", None, None, None, None),  # tonight's stage unknown
        (None, None, "advance", None, None),  # the list row's stage unknown
        ("top", None, "advance", None, None),  # not a Reversal stage
    ],
)
def test_stage_upgrade(frozen, frozen_pending, stage, pending, expected):
    assert t.stage_upgrade(frozen, frozen_pending, stage, pending) == expected


# --- D3 pullback -------------------------------------------------------------------------------------------------------------------


def test_the_pullback_ceiling_is_five_percent_inclusive():
    assert t.PULLBACK_MAX_VS_MA_PCT == 5.0
    assert t.pullback_to_ma("advance", 5.0, 1.0, 1.0)
    assert t.pullback_to_ma("advance", 0.0, 1.0, 1.0)
    assert t.pullback_to_ma("advance", -2.0, 1.0, 1.0)  # under the MA but still an Advance inside the band
    assert not t.pullback_to_ma("advance", 5.01, 1.0, 1.0)


@pytest.mark.parametrize(
    "stage, vs, slope, rs",
    [
        ("top", 3.0, 1.0, 1.0), ("base", 3.0, 1.0, 1.0), ("decline", 3.0, 1.0, 1.0), (None, 3.0, 1.0, 1.0),
        ("advance", 3.0, 0.0, 1.0), ("advance", 3.0, -0.5, 1.0),  # the MA must be rising
        ("advance", 3.0, 1.0, 0.0), ("advance", 3.0, 1.0, -1.0),  # RS must be above 0
        ("advance", None, 1.0, 1.0), ("advance", 3.0, None, 1.0), ("advance", 3.0, 1.0, None),  # any unknown figure fails it
    ],
)
def test_the_pullback_needs_every_condition(stage, vs, slope, rs):
    assert not t.pullback_to_ma(stage, vs, slope, rs)


def test_every_trigger_names_the_upstream_jobs_it_depends_on():
    assert t.TRIGGER_JOBS[t.TRIGGER_D1] == (t.JOB_BB_RSI, t.JOB_WARREN)
    assert t.TRIGGER_JOBS[t.TRIGGER_D2] == t.TRIGGER_JOBS[t.TRIGGER_D3] == (t.JOB_TREND,)
    assert set(t.UPSTREAM_JOBS) == {t.JOB_TREND, t.JOB_BB_RSI, t.JOB_WARREN}
