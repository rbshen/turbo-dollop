import core.data_groups as dg


def test_lazy_seed_defaults():
    snap = dg.get_snapshot()
    assert snap.master_on is True
    assert snap.fmp_plan == "Ultimate"
    assert set(snap.groups) == set(dg.GROUPS)
    assert snap.groups["fundamentals"].required_tier == "Premium"
    assert "daily_prices_intl" not in snap.groups
    assert all(not g.tier_verified for g in snap.groups.values())
    assert dg.group_live("fundamentals")
    assert not dg.group_live("insider")  # shelved, seeded off


def test_master_off_beats_everything_and_writes_are_live_without_ttl_wait():
    dg.set_master(False)
    assert dg.effective_state("fundamentals") == (False, "master_off")
    dg.set_master(True)
    assert dg.effective_state("fundamentals") == (True, "live")


def test_group_toggle_reason():
    dg.set_group_enabled("news", False)
    assert dg.effective_state("news") == (False, "user_off")
    assert dg.group_live("fundamentals")


def test_above_plan_is_off():
    dg.set_fmp_plan("Starter")
    assert dg.effective_state("fundamentals") == (False, "above_plan")
    assert dg.effective_state("profile_quote") == (True, "live")
    dg.set_fmp_plan("Premium")
    assert dg.effective_state("daily_prices_long") == (True, "live")  # Premium
    assert dg.group_live("fundamentals")
    dg.set_fmp_plan("Starter")
    assert dg.effective_state("daily_prices_long") == (False, "above_plan")


def test_editing_required_tier_resets_verified_unless_stated():
    dg.set_tier_verified("news", True)
    dg.set_required_tier("news", "Starter")  # unchanged value keeps the tick
    assert dg.get_snapshot().groups["news"].tier_verified is True
    dg.set_required_tier("news", "Premium")  # changed -> unverified
    assert dg.get_snapshot().groups["news"].tier_verified is False
    dg.set_required_tier("news", "Ultimate", verified=True)
    assert dg.get_snapshot().groups["news"].tier_verified is True


def test_restricted_then_cleared():
    dg.mark_restricted("segmentation", "402")
    assert dg.effective_state("segmentation") == (False, "restricted")
    assert dg.get_snapshot().groups["segmentation"].restricted_since is not None
    dg.clear_restricted("segmentation")
    assert dg.effective_state("segmentation") == (True, "live")


def test_failing_after_consecutive_failures_and_reset_on_success():
    for _ in range(dg.FAILING_AFTER_CONSECUTIVE):
        dg.record_group_failure("news", "boom")
    assert dg.get_snapshot().groups["news"].status == "failing"
    assert dg.group_live("news")  # failing is a chip, not an off state
    dg.record_group_success("news")
    st = dg.get_snapshot().groups["news"]
    assert st.status == "ok" and st.consecutive_failures == 0 and st.last_success_at is not None


def test_job_skip_reason():
    assert dg.job_skip_reason("fundamentals") is None
    dg.set_group_enabled("fundamentals", False)
    msg = dg.job_skip_reason("fundamentals")
    assert msg.startswith("skipped (group fundamentals")


def test_unknown_group_write_rejected():
    import pytest

    with pytest.raises(ValueError):
        dg.set_group_enabled("nope", True)
    with pytest.raises(ValueError):
        dg.set_fmp_plan("Gold")


def test_job_skip_reason_master_off_and_per_group_wording():
    dg.set_master(False)
    assert dg.job_skip_reason("fundamentals") == "skipped (FMP master switch off)"
    dg.set_master(True)
    dg.set_group_enabled("analyst_ratings", False)
    assert dg.job_skip_reason("analyst_ratings") == "skipped (group analyst_ratings disabled)"
    dg.mark_restricted("news", "402")
    assert dg.job_skip_reason("news") == "skipped (group news restricted by FMP (plan))"
