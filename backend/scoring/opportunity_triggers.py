"""Pure trigger rules of the daily opportunity flags (Phase 2b v1). No DB, no I/O, no clock: values in, a verdict out
(data/opportunity_daily_data.py reads and writes; pipeline/opportunity_daily_flags.py is the job). Spec: docs/specs/opportunities.md,
"Daily flags (Phase 2b v1)".

The triggers are versioned APART from the weekly list rules: `TRIGGERS_VERSION` and the ids below change only when a trigger changes, and the
weekly `RULES_VERSION` / `rules_hash` stay as they are (B3 is untouched). Change a threshold or a definition -> bump `TRIGGERS_VERSION`
and the id suffix, so an old flag is read against the rule it used.

  D1.entry_event.v1     a STORED Warren (blue_up / yellow_up) or BB+RSI event dated after the list's as-of date, knowable before the next
                        session's open (judged on the event row's `created_at`, never its event date). Reversal-list names, and Momentum-list names
                        carrying the `deep_pullback` tag. Monitored (covered) names only: any other is "not covered", never "no flag".
  D2.stage_upgrade.v1   the Weinstein stage moved UP against the stage frozen on the list row (decline -> base, decline -> advance,
                        base -> advance) or a pending Advance appeared that the list row did not have. Reversal-list names only.
  D3.pullback_to_ma.v1  a Momentum-list name whose `vs_ma_pct` is at or below PULLBACK_MAX_VS_MA_PCT while the stage is still Advance, the MA
                        slope is positive and Mansfield RS is above 0. Momentum-list names only.
"""

import hashlib
import json
from datetime import date, datetime, time, timedelta

TRIGGERS_VERSION = "1"

TRIGGER_D1 = "D1.entry_event.v1"
TRIGGER_D2 = "D2.stage_upgrade.v1"
TRIGGER_D3 = "D3.pullback_to_ma.v1"
TRIGGER_IDS = (TRIGGER_D1, TRIGGER_D2, TRIGGER_D3)
TRIGGER_LABELS = {
    TRIGGER_D1: "Entry signal after the list",
    TRIGGER_D2: "Stage upgrade",
    TRIGGER_D3: "Pullback to the MA",
}

LIST_MOMENTUM = "momentum"
LIST_REVERSAL = "reversal"

# D1 -- the event kinds that count as an up-signal (the same set the weekly B3 rule reads; scoring/opportunity_rules.py::B3_WARREN_KINDS)
D1_WARREN_KINDS = ("blue_up", "yellow_up")
D1_BB_RSI = "bb_rsi"
SOURCE_WARREN = "warren"
SOURCE_BB_RSI = "bb_rsi"

# D2 -- stage order of the Reversal stages; Top is not an upgrade target, so it ranks out of the ladder
STAGE_DECLINE, STAGE_BASE, STAGE_ADVANCE, STAGE_TOP = "decline", "base", "advance", "top"
STAGE_RANK = {STAGE_DECLINE: 0, STAGE_BASE: 1, STAGE_ADVANCE: 2}
PENDING_ADVANCE = "advance"
UPGRADE_STAGE = "stage_up"
UPGRADE_PENDING = "pending_advance"

# D3 -- the fixed, versioned pullback ceiling: vs_ma_pct (percent above the stage MA) at or below this
PULLBACK_MAX_VS_MA_PCT = 5.0

# The upstream nightly jobs a trigger depends on. D1 reads the signal events (BB+RSI 01:20, Warren 01:25); D2 and D3 read the stage row
# (Weinstein / bar-cache 01:05). All three also need the session's daily bar (the 01:05 job fills it).
JOB_TREND = "pipeline.nightly_trend_calculation"
JOB_BB_RSI = "pipeline.nightly_entry_signal_calculation"
JOB_WARREN = "pipeline.nightly_warren_signal_calculation"
UPSTREAM_JOBS = (JOB_TREND, JOB_BB_RSI, JOB_WARREN)
TRIGGER_JOBS = {
    TRIGGER_D1: (JOB_BB_RSI, JOB_WARREN),
    TRIGGER_D2: (JOB_TREND,),
    TRIGGER_D3: (JOB_TREND,),
}

# Why a trigger could not be judged for a name (stored in OpportunityDailyRun.incomplete_json; never read as "no flag")
INCOMPLETE_UPSTREAM = "upstream_job_not_successful"
INCOMPLETE_NO_BAR = "no_final_bar_for_session"  # no bar dated the session, or only a provisional one (the weekly gate's own test)
INCOMPLETE_STALE_STAGE = "stage_row_not_as_of_session"
INCOMPLETE_NO_STAGE = "no_stage_row"
INCOMPLETE_BARS_READ = "bars_read_failed"

# An event that reaches the table after the next session's open could not have been acted on at that open
KNOWABLE_OPEN_FALLBACK = time(13, 30)  # 09:30 US/Eastern in EDT, as a UTC clock time, used only if the calendar is unavailable


def applicable_triggers(list_name: str, tags: dict | None) -> tuple[str, ...]:
    """The triggers that apply to a listed row: D1 for Reversal rows and for Momentum rows tagged `deep_pullback`, D2 for Reversal rows,
    D3 for Momentum rows."""
    tags = tags or {}
    if list_name == LIST_REVERSAL:
        return (TRIGGER_D1, TRIGGER_D2)
    if list_name == LIST_MOMENTUM:
        return (TRIGGER_D1, TRIGGER_D3) if tags.get("deep_pullback") else (TRIGGER_D3,)
    return ()


def event_is_knowable(event_session: date, created_at: datetime, next_open_utc: datetime | None) -> bool:
    """True when the event row was written before the open of the session after the event's own session -- the first moment the entry
    convention (next session's open) can be acted on. `created_at` is the naive UTC time the row was inserted (the server clock is UTC);
    `next_open_utc` that open as a naive UTC time. With no calendar the open is taken as 13:30 UTC on the next weekday."""
    if next_open_utc is None:
        day = event_session + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        next_open_utc = datetime.combine(day, KNOWABLE_OPEN_FALLBACK)
    return created_at <= next_open_utc


def stage_upgrade(frozen_stage: str | None, frozen_pending: str | None, stage: str | None, pending: str | None) -> str | None:
    """None, or why the stage counts as an upgrade against the list row: `stage_up` (decline -> base / advance, base -> advance) or
    `pending_advance` (the row has a pending Advance and the list row had none, while the stage is not yet Advance). Any unknown stage
    -- the list row's or tonight's -- is no upgrade."""
    if frozen_stage not in STAGE_RANK or stage is None:
        return None
    if stage in STAGE_RANK and STAGE_RANK[stage] > STAGE_RANK[frozen_stage]:
        return UPGRADE_STAGE
    if pending == PENDING_ADVANCE and frozen_pending != PENDING_ADVANCE and stage != STAGE_ADVANCE:
        return UPGRADE_PENDING
    return None


def pullback_to_ma(stage: str | None, vs_ma_pct: float | None, ma_slope_pct: float | None, mansfield_rs: float | None) -> bool:
    """The Momentum pullback: still an Advance, price within PULLBACK_MAX_VS_MA_PCT of its MA (at or below it, even under it), the MA still
    rising and relative strength still above 0. Any unknown figure fails it."""
    if stage != STAGE_ADVANCE or vs_ma_pct is None or ma_slope_pct is None or mansfield_rs is None:
        return False
    return vs_ma_pct <= PULLBACK_MAX_VS_MA_PCT and ma_slope_pct > 0 and mansfield_rs > 0


def triggers_definition() -> dict:
    """Every id and threshold, for the hash: change any and the hash moves (and TRIGGERS_VERSION should be bumped by hand)."""
    return {
        "version": TRIGGERS_VERSION,
        TRIGGER_D1: {"warren_kinds": list(D1_WARREN_KINDS), "bb_rsi": True, "lists": [LIST_REVERSAL, "momentum:deep_pullback"], "knowable": "created_at <= next session open"},
        TRIGGER_D2: {"ladder": STAGE_RANK, "pending": PENDING_ADVANCE, "lists": [LIST_REVERSAL]},
        TRIGGER_D3: {"max_vs_ma_pct": PULLBACK_MAX_VS_MA_PCT, "stage": STAGE_ADVANCE, "slope": "> 0", "rs": "> 0", "lists": [LIST_MOMENTUM]},
    }


def triggers_hash() -> str:
    return hashlib.sha256(json.dumps(triggers_definition(), sort_keys=True).encode()).hexdigest()
