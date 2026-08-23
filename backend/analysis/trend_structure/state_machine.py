"""The flip-gate state machine -- the crux of this feature's "validated...
logic," so correctness here matters more than cleverness. A single
sequential pass over the ordered, classified swings; not vectorized, since
every step depends on the running trend_state built up so far.

Direction of a classification is fixed (classification.py's own docstring):
HH/HL are "bullish", LH/LL are "bearish" -- independent of the CURRENT
trend_state. Given that fixed direction, each swing is handled by comparing
its direction against the current trend_state:

  - Direction matches current trend_state ("same-direction"): a normal
    continuation/confirming swing (HH or HL while already uptrend; LH or LL
    while already downtrend). At ratio>=0.5 ("weak-confirmed+") this updates
    persistence_count, magnitude_tier, and last_confirmed_swing, and clears
    any pending warning_flag. At ratio<0.5 ("tentative") it only bumps
    persistence_count -- the specific fix this feature's spec calls out by
    name: a tentative swing must NOT change magnitude_tier.
  - Direction opposes current trend_state, AND the classification is the
    "primary" extreme for its direction (HH for bullish, LL for bearish) AND
    ratio>=1.0 ("confirmed"): a genuine flip. trend_state changes,
    persistence_count resets to 1, magnitude_tier/last_confirmed_swing are
    set from this swing, and any pending warning resolves (cleared, since
    the flip itself supersedes it).
  - Direction opposes current trend_state, AND the classification is the
    "secondary" type for its direction (HL for bullish-against-downtrend, LH
    for bearish-against-uptrend): this is "a confirmed LH or HL" in the
    spec's own words -- ALWAYS sets warning_flag + warning_swing, regardless
    of ratio, and never touches trend_state/persistence_count/magnitude_tier.
  - Direction opposes current trend_state, classification is the "primary"
    type for its direction, but ratio<1.0 (not yet strong enough to flip):
    the spec names only "LH or HL" as ever setting warning_flag, so this
    case (a weak/tentative HH-while-downtrend, or LL-while-uptrend) is a
    deliberate no-op -- not a flip, not a warning, no persistence/tier
    change. A documented literal reading of an otherwise-unstated case, not
    an oversight.
"""

from dataclasses import dataclass

from .classification import ClassifiedSwing
from .types import CONFIRMED_RATIO, Classification, MagnitudeTier, SwingDetail, TrendState

WEAK_RATIO = 0.5

_BULLISH: set[Classification] = {"HH", "HL"}
_PRIMARY_FOR_DIRECTION: dict[TrendState, Classification] = {"uptrend": "HH", "downtrend": "LL"}


def _direction_of(classification: Classification) -> TrendState:
    return "uptrend" if classification in _BULLISH else "downtrend"


def _magnitude_tier_for_ratio(ratio: float) -> MagnitudeTier:
    if ratio >= 1.5:
        return "strong"
    if ratio >= 1.0:
        return "confirmed"
    if ratio >= 0.5:
        return "weak"
    raise ValueError(f"ratio {ratio} is below the weak-confirmed floor ({WEAK_RATIO})")


def _to_detail(cs: ClassifiedSwing) -> SwingDetail:
    return SwingDetail(date=cs.swing.date, price=cs.swing.price, margin=cs.margin, atr=cs.atr, ratio=cs.ratio)


@dataclass
class TrendMachineState:
    trend_state: TrendState
    magnitude_tier: MagnitudeTier | None
    persistence_count: int
    last_confirmed_swing: SwingDetail | None
    warning_flag: bool
    warning_swing: SwingDetail | None


def run_state_machine(classified: list[ClassifiedSwing]) -> TrendMachineState:
    """classified must be chronologically ordered. Returns the FINAL state
    after processing every swing."""
    if not classified:
        # No classifiable swing at all -- an arbitrary, documented bootstrap
        # default; the spec has no rule for the zero-swing case.
        return TrendMachineState(
            trend_state="uptrend",
            magnitude_tier=None,
            persistence_count=0,
            last_confirmed_swing=None,
            warning_flag=False,
            warning_swing=None,
        )

    # Bootstrap trend_state from the first classified swing's own direction --
    # the spec has no rule for "what was the trend before any flip occurred";
    # this is a documented starting assumption, not part of the validated
    # flip-gate logic itself (which only ever governs subsequent flips).
    state = TrendMachineState(
        trend_state=_direction_of(classified[0].classification),
        magnitude_tier=None,
        persistence_count=0,
        last_confirmed_swing=None,
        warning_flag=False,
        warning_swing=None,
    )

    for cs in classified:
        direction = _direction_of(cs.classification)
        ratio = cs.ratio
        same_direction = direction == state.trend_state

        if same_direction:
            state.persistence_count += 1
            if ratio >= WEAK_RATIO:
                state.magnitude_tier = _magnitude_tier_for_ratio(ratio)
                state.last_confirmed_swing = _to_detail(cs)
                state.warning_flag = False
                state.warning_swing = None
            # ratio < WEAK_RATIO ("tentative"): persistence_count already
            # bumped above; magnitude_tier must NOT change (the specific fix
            # this feature's spec calls out by name).
            continue

        # Direction opposes the current trend_state.
        is_primary = cs.classification == _PRIMARY_FOR_DIRECTION[direction]
        if is_primary and ratio >= CONFIRMED_RATIO:
            # Genuine flip.
            state.trend_state = direction
            state.magnitude_tier = _magnitude_tier_for_ratio(ratio)
            state.persistence_count = 1
            state.last_confirmed_swing = _to_detail(cs)
            state.warning_flag = False
            state.warning_swing = None
        elif not is_primary:
            # "A confirmed LH or HL -- regardless of ratio -- does NOT flip
            # trend_state; it only sets warning_flag=true with its own
            # warning_swing detail."
            state.warning_flag = True
            state.warning_swing = _to_detail(cs)
        # else: primary-for-opposite-direction but ratio<1.0 -- deliberate
        # no-op, see module docstring's last bullet.

    return state
