"""Classifies each swing against the trailing 3 same-type swings' extreme.
Per this feature's spec, HH/HL are grouped "bullish" and LH/LL "bearish" --
that pairing (not a HIGH-type-vs-LOW-type split) is what state_machine.py
uses to decide same-direction-as-trend vs. warning-direction behavior:

  - HH ("Higher High"): a new swing high that broke ABOVE the trailing-3
    ceiling -- the only classification that can flip trend_state to uptrend.
  - HL ("Higher Low"): a new swing low that stayed ABOVE the trailing-3
    floor -- bullish, but never a flip trigger on its own (see state_machine.py).
  - LH ("Lower High"): a new swing high that stayed BELOW the trailing-3
    ceiling -- bearish, but never a flip trigger on its own.
  - LL ("Lower Low"): a new swing low that broke BELOW the trailing-3 floor
    -- the only classification that can flip trend_state to downtrend.

Compares against the highest/lowest of the TRAILING 3 same-type swings, not
just the single immediately-prior one, per this feature's spec. A swing
with fewer than 1 prior same-type swing to compare against, or no ATR value
yet available for its date, is skipped entirely (not classifiable).
"""

from dataclasses import dataclass

from .types import Classification, SwingPoint

TRAILING_WINDOW = 3


@dataclass(frozen=True)
class ClassifiedSwing:
    swing: SwingPoint
    classification: Classification
    margin: float
    atr: float
    ratio: float


def classify_swings(swings: list[SwingPoint], atr_by_date: dict) -> list[ClassifiedSwing]:
    """swings must be chronologically ordered (mixed highs/lows, as
    extract_swing_points returns). atr_by_date maps a swing's date to the
    ATR(14) value as of that date."""
    classified: list[ClassifiedSwing] = []
    highs_so_far: list[SwingPoint] = []
    lows_so_far: list[SwingPoint] = []

    for swing in swings:
        atr = atr_by_date.get(swing.date)
        if swing.kind == "high":
            trailing = highs_so_far[-TRAILING_WINDOW:]
            if trailing and atr is not None and atr > 0:
                ceiling = max(p.price for p in trailing)
                if swing.price > ceiling:
                    kind: Classification = "HH"
                    margin = swing.price - ceiling
                else:
                    kind = "LH"
                    margin = ceiling - swing.price
                classified.append(ClassifiedSwing(swing=swing, classification=kind, margin=margin, atr=atr, ratio=margin / atr))
            highs_so_far.append(swing)
        else:
            trailing = lows_so_far[-TRAILING_WINDOW:]
            if trailing and atr is not None and atr > 0:
                floor = min(p.price for p in trailing)
                if swing.price < floor:
                    kind = "LL"
                    margin = floor - swing.price
                else:
                    kind = "HL"
                    margin = swing.price - floor
                classified.append(ClassifiedSwing(swing=swing, classification=kind, margin=margin, atr=atr, ratio=margin / atr))
            lows_so_far.append(swing)

    return classified
