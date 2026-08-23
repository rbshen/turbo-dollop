"""The blended conviction score and its bar_level banding -- implemented
literally per this feature's spec formula. Both computed backend-only,
never re-derived in the frontend.
"""

import math

from .types import MagnitudeTier, Regime, TrendState

_TIER_SCORE: dict[MagnitudeTier, float] = {"weak": 0.33, "confirmed": 0.67, "strong": 1.0}

PERSISTENCE_CAP = 10
RECENCY_WINDOW_DAYS = 30
REGIME_TRENDING_MULTIPLIER = 1.0
REGIME_RANGE_BOUND_MULTIPLIER = 0.7
WARNING_MULTIPLIER = 0.7
NO_WARNING_MULTIPLIER = 1.0
# A/D Bullish Divergence conviction booster (see classification.py) --
# retrospective only: only boosts a ticker whose divergence-flagged LL has
# already played out into a confirmed uptrend, never a standalone trigger
# on a still-downtrend name. Validated as a minor edge (~+2pp hit rate,
# ~+2% mean/median return), not a magnitude/graduated signal -- a single
# flat multiplier, not a scaled one.
AD_BULLISH_DIVERGENCE_MULTIPLIER = 1.15


def compute_blended_score(
    trend_state: TrendState,
    magnitude_tier: MagnitudeTier | None,
    persistence_count: int,
    bars_since_confirmation: int | None,
    regime: Regime | None,
    warning_flag: bool,
    ad_bullish_divergence: bool = False,
) -> float:
    # magnitude_tier/bars_since_confirmation can be None only when the
    # swing history is too thin to have produced a weak-confirmed-or-
    # stronger swing yet (see state_machine.py) -- not a case the spec
    # covers explicitly; scored as the floor (0 contribution) rather than
    # raising, so a thin-history ticker still gets a (low-conviction) score.
    tier_score = _TIER_SCORE[magnitude_tier] if magnitude_tier is not None else 0.0
    persistence_score = min(persistence_count, PERSISTENCE_CAP) / PERSISTENCE_CAP
    recency_score = 0.0 if bars_since_confirmation is None else max(0.0, 1.0 - bars_since_confirmation / RECENCY_WINDOW_DAYS)

    conviction = 0.5 * tier_score + 0.3 * persistence_score + 0.2 * recency_score
    conviction *= REGIME_TRENDING_MULTIPLIER if regime == "trending" else REGIME_RANGE_BOUND_MULTIPLIER
    conviction *= WARNING_MULTIPLIER if warning_flag else NO_WARNING_MULTIPLIER

    sign = 1.0 if trend_state == "uptrend" else -1.0
    blended = sign * conviction * 10.0

    # Applied LAST -- strictly after the regime/warning_flag dampeners
    # already baked into `conviction` above, per this feature's own spec.
    # Only ever boosts an already-confirmed uptrend name; can push
    # blended_score slightly past the documented +/-10 range for a
    # near-ceiling score, which compute_bar_level's own min(4, ...) clamp
    # already tolerates.
    if ad_bullish_divergence and trend_state == "uptrend":
        blended *= AD_BULLISH_DIVERGENCE_MULTIPLIER

    return blended


def compute_bar_level(blended_score: float) -> int:
    """Continuous rescale, NOT a raw integer bin: maps -10..+10 onto 0..5
    continuously, then floors -- band width is 4 raw-score points each
    (1: -10..-6 strong downtrend, 2: -6..-2 moderate downtrend, 3: -2..2
    neutral/mixed, 4: 2..6 moderate uptrend, 5: 6..10 strong uptrend).

    The original spec text gave this as `(blended_score + 10) / 20 * 4`
    (dividing the 20-wide score range into 4 units) alongside a reference
    band table with width-4 boundaries at -6/-2/2/6 -- those two don't
    agree: `/20*4` actually produces width-5 bands (transitions at
    -5/0/5), leaving bar_level=5 reachable only at the single exact point
    blended_score=10. Confirmed with the user that the reference table is
    authoritative; `/20*5` (equivalently `/4`) is what actually reproduces
    it, matching all 5 documented band boundaries exactly."""
    rescaled = (blended_score + 10) / 20 * 5
    return min(4, math.floor(rescaled)) + 1
