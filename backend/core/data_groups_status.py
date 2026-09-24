"""Read/write API surface for the data-group toggles (GET/PUT
/api/config/data-groups*). Kept out of core/data_groups.py so that module
stays free of schema imports."""

import core.data_groups as dg
from core.schemas import DataGroupOut, DataGroupsOut

_STATE_BY_REASON = {
    "live": "live",
    "master_off": "cached_only",
    "user_off": "cached_only",
    "above_plan": "not_on_plan",
    "restricted": "restricted",
}


def build_data_groups_out() -> DataGroupsOut:
    snap = dg.get_snapshot()
    groups = []
    for key, meta in dg.GROUPS.items():
        st = snap.groups[key]
        live, reason = dg.effective_state_from(snap, key)
        state = _STATE_BY_REASON[reason]
        if meta.falls_back and reason in ("master_off", "user_off"):
            state = "using_fallback"
        if live and st.status == "failing":
            state = "failing"
        groups.append(
            DataGroupOut(
                key=key,
                label=meta.label,
                wired=meta.live,
                falls_back=meta.falls_back,
                enabled=st.enabled,
                state=state,
                reason=reason,
                required_tier=st.required_tier,
                tier_verified=st.tier_verified,
                restricted_since=st.restricted_since,
                last_success_at=st.last_success_at,
                last_error=st.last_error,
                feeds=list(meta.feeds),
                can_toggle=snap.master_on and reason not in ("above_plan", "restricted"),
            )
        )
    return DataGroupsOut(
        master_on=snap.master_on,
        fmp_plan=snap.fmp_plan,
        tiers=list(dg.TIERS),
        key_problem_at=snap.key_problem_at,
        key_problem_detail=snap.key_problem_detail,
        groups=groups,
    )
