"""Pure derivation of the Technical tab's Reversal / Trend Continuation
("Pullback") pill statuses from an already-computed TrendAnalysis row --
ported 1:1 from the same logic the Technical tab's own cards already use
client-side (frontend/components/technical/ReversalCard.tsx::reversalStatus,
TrendContinuationCard.tsx::resolutionStatus), so a Screener-wide bulk render
can show the same read without a per-ticker fetch or re-running the swing/
BOS engine. Deliberately kept in each card's own vocabulary rather than a
forced shared enum -- see CLAUDE.md's Screener surfacing note for why.

If either frontend function's logic ever changes, this must change with it
-- there is no shared source of truth between the two languages.
"""

# Matches ReversalCard.tsx's STALE_THRESHOLD_BARS exactly.
REVERSAL_STALE_THRESHOLD_BARS = 42

ReversalStatus = str  # "not_present" | "confirmed" | "confirmed_stale"
PullbackStatus = str  # "no_pullback" | "pending" | "recovered" | "invalidated"


def compute_reversal_status(
    magnitude_tier: str | None,
    last_confirmed_swing_classification: str | None,
    ad_bullish_divergence: bool | None,
    bars_since_confirmation: int | None,
) -> ReversalStatus:
    """Mirrors reversalStatus()/reversalDisplayStatus() in ReversalCard.tsx.
    classification == "LL" can only ever be true while trend_state ==
    "downtrend" (a state-machine invariant, see ReversalCard.tsx's own
    comment), so trend_state itself isn't needed as an input here."""
    confirmed_ll = last_confirmed_swing_classification == "LL" and magnitude_tier in ("confirmed", "strong")
    divergence_present = confirmed_ll and ad_bullish_divergence is True
    if not divergence_present:
        return "not_present"
    if bars_since_confirmation is not None and bars_since_confirmation >= REVERSAL_STALE_THRESHOLD_BARS:
        return "confirmed_stale"
    return "confirmed"


def compute_pullback_status(
    trend_state: str,
    warning_flag: bool,
    pullback_occurred_since_flip: bool | None,
) -> PullbackStatus:
    """Mirrors resolutionStatus() in TrendContinuationCard.tsx."""
    if trend_state == "downtrend":
        return "invalidated"
    if warning_flag:
        return "pending"
    return "recovered" if pullback_occurred_since_flip is True else "no_pullback"
