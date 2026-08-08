from typing import NamedTuple

import numpy as np

from scoring.series_trend import robust_late_direction

# A period-over-period change smaller than this counts as flat/noise, not a
# real move. 5% rather than something tighter because routine single-digit
# swings in large, otherwise-consistent companies (e.g. a ~2-3% single-year
# revenue dip) shouldn't read as a "dip" the way a human eyeballing a 10-year
# chart wouldn't call it one either.
NOISE_FLOOR = 0.05
# Boundary between a "small" and a "significant" single dip.
SIGNIFICANT_DIP = 0.10
# How large the final jump must be, and how flat everything before it must
# be, to read as "flat for years then a sudden spike" rather than gradual
# multi-dip growth.
SPIKE_THRESHOLD = 0.25
FLAT_WINDOW_THRESHOLD = 0.10
# How large a single-year jump must be before the value it produced is
# treated as an unreliable "pre-dip peak" to measure recovery against,
# rather than a genuine baseline (see CLAUDE.md's Step 1 deviations -- MPWR).
# Deliberately much higher than SPIKE_THRESHOLD: an ordinary strong-growth
# year routinely exceeds 25%, but a >=100% single-year jump is rare enough
# to reliably flag a one-time event (confirmed via real cases -- MPWR,
# PEP, GS, UNP -- all trace to genuine one-off items, not normal growth).
DIP_BASELINE_SPIKE_RATIO = 1.0
# Only a TTM decline steeper than this is still an unconditional
# disqualifier -- anything shallower now flows through as an ordinary dip
# transition, subject to the same merge/resolution logic as any other dip
# (see DipEvent below), rather than a flat, age-blind override. Confirmed
# via a 2026-08-08 investigation: ~12 tickers (APTV, PHM, FISV, HCA, PCG,
# TSCO, etc.) were dragged from Pass to Fail by a single mild (5-15%) TTM
# wobble after an otherwise long, clean growth run -- this threshold is
# where "confirm the trend is genuinely breaking" starts, not any decline.
SEVERE_TTM_DECLINE = 0.15
# Secondary "durably resolved" bar for a dip event that hasn't literally
# re-exceeded its own baseline by TTM -- see _dip_durably_resolved. Both
# values match the 2026-08-08 investigation's own already-run validation
# scripts (step1_stale_peak_scan.py), not blind guesses.
DIP_RESOLUTION_MIN_AGE = 4
DIP_RESOLUTION_MIN_RECOVERY_RUN = 3
# Shared early/late window for robust_late_direction, reused by both the
# durable-resolution direction check and flat_then_spike's narrowing below --
# matches the "3" convention already used by Step 1's MARGIN_TREND_WINDOW.
TREND_RECOVERY_WINDOW = 3
# flat_then_spike's own "was it really flat before the spike" check only
# looks at 2 points (arr[0] vs arr[-2]), which misses a genuine multi-year
# improvement sitting just behind the terminal jump. This relative
# (not point-based, since these are dollar-magnitude series, not
# percentage-point margins) threshold narrows the pattern to fire only when
# even the robust late-window average (single most extreme point excluded)
# shows no meaningful improvement over the early window.
FLAT_SPIKE_IMPROVEMENT_THRESHOLD = 0.10


class TrendResult(NamedTuple):
    pattern: str
    score: int


# classify_trend patterns that represent a durable recovery -- shared by
# every "an old, since-resolved dip/negative value shouldn't permanently
# disqualify" check in this app (Step 1 FCF, Step 3 method-selection, Step 4
# ROE/ROIC and negative-equity substitute). grows_every_year is included for
# completeness even though callers only ever reach this set after a
# disqualifying value has already occurred.
#
# dip_durably_resolved added 2026-08-08: it was introduced (89b1728) scored
# identically to multiple_dips_resolved (both 75, see classify_trend below)
# and documented there as "kept distinct only so the reasoning panel"
# reads differently -- i.e. always meant to be treated the same by any
# caller checking membership here, but this set wasn't updated at the time,
# leaving every consumer above unable to recognize an age-resolved dip
# (only classify_trend's own direct score, used by Step 1's Revenue/NI/OI/
# CFO scoring, benefited immediately). Confirmed via a full 503-ticker scan:
# 0 Step 1 changes (no ticker's cached data happened to hit the FCF-specific
# gap), 17 Step 3 method-selection changes (all upgrades to a more direct
# method, e.g. DAL DNI_NORMALIZED -> DFCF, KHC/SJM PASS -> DFCF), 1 Step 4
# verdict flip (MCK Pass -> Strong Pass, ROE's negative-equity substitute).
RECOVERY_PATTERNS = {
    "grows_every_year",
    "small_dip_recovers",
    "significant_dip_recovers",
    "multiple_dips_resolved",
    "dip_durably_resolved",
}


def _pct_changes(values: np.ndarray) -> np.ndarray:
    prev = values[:-1]
    curr = values[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(prev != 0, (curr - prev) / np.abs(prev), np.sign(curr))


def _effective_pre_dip_value(arr: np.ndarray, pct_changes: np.ndarray, dip_index: int) -> float:
    """The value to measure "has this dip recovered" against. Normally the
    value immediately before the dip -- but if THAT value was itself
    produced by a >=100% one-year jump, it's a spike, not a genuine
    baseline, and measuring recovery against a fake peak punishes durable
    growth for a single non-recurring event. Falls back to the value from
    before the jump in that case."""
    if dip_index > 0 and pct_changes[dip_index - 1] > DIP_BASELINE_SPIKE_RATIO:
        return float(arr[dip_index - 1])
    return float(arr[dip_index])


class DipEvent(NamedTuple):
    start: int       # transition index of the first declining leg in the run
    end: int         # transition index of the last declining leg in the run
    baseline: float  # _effective_pre_dip_value applied to the run's first leg
    trough: float    # value right after the run ends


def _dip_events(arr: np.ndarray, pct_changes: np.ndarray, real_dips: np.ndarray) -> list[DipEvent]:
    """Merge CONTIGUOUS real-dip transition indices into one event -- a
    multi-year decline (e.g. HWM's 2018-2021 revenue collapse, three
    consecutive declining transitions) is one real economic event, not
    three independent dips each needing its own recovery. A non-declining
    (or sub-noise-floor) point between two declines keeps them as separate
    events. Baseline is measured from the run's FIRST leg, reusing
    _effective_pre_dip_value's existing one-time-spike guard unchanged."""
    events: list[DipEvent] = []
    run_start: int | None = None
    run_prev: int | None = None
    for idx in (int(i) for i in real_dips):
        if run_start is None:
            run_start = run_prev = idx
        elif idx == run_prev + 1:
            run_prev = idx
        else:
            events.append(_build_dip_event(arr, pct_changes, run_start, run_prev))
            run_start = run_prev = idx
    if run_start is not None:
        events.append(_build_dip_event(arr, pct_changes, run_start, run_prev))
    return events


def _build_dip_event(arr: np.ndarray, pct_changes: np.ndarray, start: int, end: int) -> DipEvent:
    return DipEvent(
        start=start,
        end=end,
        baseline=_effective_pre_dip_value(arr, pct_changes, start),
        trough=float(arr[end + 1]),
    )


def _dip_durably_resolved(arr: np.ndarray, pct_changes: np.ndarray, event: DipEvent) -> bool:
    """Secondary resolution path for a dip event that hasn't literally
    re-exceeded `event.baseline` by TTM. All three required:

    1. `age` (periods between the event's own trough and TTM) is old enough
       that a still-recovering, recently-resolved dip isn't mistaken for a
       durable one -- reuses most_recent_real_dip_age's own age convention.
    2. The TRAILING run of consecutive non-dip transitions counting
       backward from TTM is long enough -- measured from TTM backward (not
       forward from the trough), so it's independent of `age`: an old dip
       with a messy stretch in between but a genuinely stable/growing
       recent tail can still resolve; a fresh relapse right before TTM
       cannot, however old the original dip is.
    3. The recovery segment (trough through TTM) shows non-negative robust
       late-vs-early direction (reusing series_trend's robust_late_direction,
       same convention already validated for Step 1's Margins and Step 4's
       CCC classifiers) -- confirms genuine improvement, not merely "no new
       dip since."
    """
    age = (len(pct_changes) - 1) - event.end
    if age < DIP_RESOLUTION_MIN_AGE:
        return False

    trailing_clean_run = 0
    for pct in reversed(pct_changes[event.end + 1 :]):
        if pct < -NOISE_FLOOR:
            break
        trailing_clean_run += 1
    if trailing_clean_run < DIP_RESOLUTION_MIN_RECOVERY_RUN:
        return False

    recovery_segment = arr[event.end + 1 :]
    return robust_late_direction(recovery_segment, TREND_RECOVERY_WINDOW) >= 0


def most_recent_real_dip_age(values: list[float]) -> int | None:
    """Periods before TTM that the most recent real (< -NOISE_FLOOR)
    year-over-year decline landed -- 0 if it's the transition into TTM
    itself, 1 if it's the transition before that, etc. None if there are
    no real dips, or too few points to have any transition. Reuses
    classify_trend's own "real dip" definition (same NOISE_FLOOR, same
    _pct_changes) rather than a separately-tuned notion of recency, so a
    caller gating a rescue on this checks the same thing classify_trend
    itself already decided counts as "real"."""
    if len(values) < 2:
        return None
    arr = np.asarray(values, dtype=float)
    pct_changes = _pct_changes(arr)
    real_dips = np.flatnonzero(pct_changes < -NOISE_FLOOR)
    if real_dips.size == 0:
        return None
    return (len(pct_changes) - 1) - int(real_dips[-1])


def resolved_dip_events(values: list[float]) -> list[DipEvent]:
    """All dip events in `values` that resolved by TTM -- literally
    (TTM >= event.baseline) or via the same durable-resolution path
    classify_trend uses (_dip_durably_resolved). Unlike classify_trend,
    which stops at the first UNRESOLVED event, this returns every event
    that DID resolve regardless of whether some other, unresolved event
    exists elsewhere in the series -- built for Step 4's ROE/ROIC
    recovery-aware exclusion (see scoring/step4.py), where a resolved
    dip's own stale years should stop dragging the average down even if
    a different year is still a live problem."""
    if len(values) < 2:
        return []
    arr = np.asarray(values, dtype=float)
    pct_changes = _pct_changes(arr)
    real_dips = np.flatnonzero(pct_changes < -NOISE_FLOOR)
    if real_dips.size == 0:
        return []
    events = _dip_events(arr, pct_changes, real_dips)
    return [e for e in events if arr[-1] >= e.baseline or _dip_durably_resolved(arr, pct_changes, e)]


def classify_trend(values: list[float]) -> TrendResult:
    """Classify a chronological (oldest fiscal year -> TTM) metric series into
    one of the Step 1 methodology's trend patterns (grows_every_year,
    small_dip_recovers, significant_dip_recovers, multiple_dips_resolved,
    dip_durably_resolved, multiple_dips, flat_then_spike, declining).

    Contract: `values` must already be filtered of None/missing periods and
    given in chronological order ending with TTM. Requires at least 2 points.
    """
    if len(values) < 2:
        return TrendResult("insufficient_data", 0)

    arr = np.asarray(values, dtype=float)
    pct_changes = _pct_changes(arr)
    real_dips = np.flatnonzero(pct_changes < -NOISE_FLOOR)

    # Only a SEVERE TTM decline is still an unconditional disqualifier,
    # regardless of earlier history -- a milder one (still a real dip, but
    # short of SEVERE_TTM_DECLINE) now flows through as an ordinary
    # transition below, subject to the same merge/resolution logic as any
    # other dip, rather than a flat, age-blind override.
    if pct_changes[-1] < -SEVERE_TTM_DECLINE:
        return TrendResult("declining", 0)

    if real_dips.size == 0:
        return TrendResult("grows_every_year", 100)

    # flat_then_spike: entry gate unchanged (raw dip count, same 2-point
    # flat/spike check) -- narrowed only by an additional AND-condition
    # below, which distinguishes "genuinely flat before a lone spike" from
    # "recent multi-year improvement the 2-point check can't see" (e.g. HON:
    # arr[0] vs arr[-2] reads flat, but the robust late-window average --
    # single most extreme point excluded, same convention as Margins/CCC --
    # is meaningfully above the early window even setting the terminal jump
    # aside).
    if real_dips.size >= 2:
        growth_before_last = _pct_changes(arr[[0, -2]])[0]
        last_jump = pct_changes[-1]
        if abs(growth_before_last) < FLAT_WINDOW_THRESHOLD and last_jump > SPIKE_THRESHOLD:
            w = min(TREND_RECOVERY_WINDOW, len(arr))
            early_avg = float(arr[:w].mean())
            delta = robust_late_direction(arr, TREND_RECOVERY_WINDOW)
            meaningful_improvement = early_avg != 0 and (delta / abs(early_avg)) > FLAT_SPIKE_IMPROVEMENT_THRESHOLD
            if not meaningful_improvement:
                return TrendResult("flat_then_spike", 20)

    events = _dip_events(arr, pct_changes, real_dips)

    # Deliberately refined beyond financials.md's original flat
    # 40-for-any-2+-dips read -- see CLAUDE.md's "Scoring rubric
    # deviations" section. Whether every dip event recovered by TTM
    # matters; how recently it happened doesn't -- either literally
    # re-exceeding its own baseline, or (new) durably resolving via
    # _dip_durably_resolved, counts as recovered regardless of when it
    # happened.
    literal_recovery: list[bool] = []
    for event in events:
        if arr[-1] >= event.baseline:
            literal_recovery.append(True)
        elif _dip_durably_resolved(arr, pct_changes, event):
            literal_recovery.append(False)  # resolved, but not literally
        else:
            # At least one dip event never got back to its baseline by TTM
            # and isn't old/durable enough to excuse -- genuinely uneven.
            return TrendResult("multiple_dips", 40)

    if len(events) == 1 and literal_recovery[0]:
        event = events[0]
        # A genuine single transition (start == end) must read its severity
        # directly off that transition's own pct_changes value, NOT a
        # recomputed baseline-vs-trough magnitude -- these differ whenever
        # the spike-guard substituted a pre-spike baseline
        # (_effective_pre_dip_value), and recomputing would silently change
        # severity classification for existing spike-adjusted cases (see
        # CLAUDE.md's MPWR case). Only a genuinely MERGED (start != end)
        # single event needs the aggregate magnitude, since no single
        # transition represents the whole run.
        if event.start == event.end:
            dip_pct = pct_changes[event.start]
        else:
            dip_pct = (event.trough - event.baseline) / abs(event.baseline) if event.baseline else -1.0
        if abs(dip_pct) <= SIGNIFICANT_DIP:
            return TrendResult("small_dip_recovers", 90)
        # Was 70 -- close enough to multiple_dips_resolved's 75 (2+ dips,
        # all recovered) that a single larger-but-fully-recovered dip
        # scored WORSE than two smaller resolved dips, an inversion with no
        # real justification (confirmed via AMZN: a clean 2022 net loss,
        # since fully recovered 3 years running, capped at 70). Raised to
        # 85 -- still below small_dip_recovers' 90 (a genuinely severe dip
        # is a different risk profile from a mild one, so some distinction
        # is kept), but much closer, matching a refined reading of the
        # methodology doc: "one or two down years acceptable if the
        # broader trend is up," not graded by dip magnitude. Verified via a
        # full 427-ticker simulation before adopting: purely monotonic,
        # zero tickers lose points at this value. multiple_dips_resolved's
        # 75 is untouched -- a separately, deliberately validated value
        # (see CLAUDE.md), out of scope here.
        return TrendResult("significant_dip_recovers", 85)

    if any(not recovered_literally for recovered_literally in literal_recovery):
        # At least one event only resolved via the durable (non-literal)
        # path -- kept as a distinct pattern (same score as
        # multiple_dips_resolved) purely so the reasoning panel can say
        # "durably improved, not yet a new high" rather than implying a
        # literal new peak was reached.
        return TrendResult("dip_durably_resolved", 75)

    return TrendResult("multiple_dips_resolved", 75)
