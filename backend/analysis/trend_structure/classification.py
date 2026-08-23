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

A/D Bullish Divergence (validated separately, see ad_line.py) piggybacks on
this exact same single pass, per its own spec's explicit "fold into the
existing loop, don't re-walk the swing list" requirement -- whenever this
loop classifies a new "LL", it also looks up the Chaikin Oscillator's own
matched low (the literal minimum oscillator value within a
+/-AD_DIVERGENCE_MATCH_WINDOW-bar window centered on that swing's date --
truncated/asymmetric near either end of history, never waiting on bars that
don't exist yet) and compares it against a rolling floor built from the
trailing 3 prior *confirmed* (ratio >= CONFIRMED_RATIO) LL swings' own
matched lows -- exactly the same "new value vs. trailing-3 floor" shape
this file already uses for price itself (a low that stays above the
trailing-3 floor is the non-confirming "HL" case), just applied to the
oscillator instead of price. Only LL swings are ever eligible -- bullish
divergence has no bearish/HH-side equivalent (tested during the backtest,
no edge, intentionally excluded).
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .types import CONFIRMED_RATIO, Classification, SwingPoint

TRAILING_WINDOW = 3
AD_DIVERGENCE_MATCH_WINDOW = 10


@dataclass(frozen=True)
class ClassifiedSwing:
    swing: SwingPoint
    classification: Classification
    margin: float
    atr: float
    ratio: float
    ad_bullish_divergence: bool = False
    ad_divergence_swing_date: date | None = None


def _matched_oscillator_low(
    swing_date: date,
    osc_dates: list[date],
    osc_values,
    osc_pos_by_date: dict[date, int],
) -> tuple[float, date] | tuple[None, None]:
    """The literal minimum Chaikin Oscillator value within a
    +/-AD_DIVERGENCE_MATCH_WINDOW-bar window centered on swing_date,
    positional (trading bars), not calendar days -- naturally
    truncates/asymmetric near either end of the available series via plain
    slice bounds, never reaching for a bar that doesn't exist yet."""
    pos = osc_pos_by_date.get(swing_date)
    if pos is None:
        return None, None
    lo = max(0, pos - AD_DIVERGENCE_MATCH_WINDOW)
    hi = min(len(osc_values), pos + AD_DIVERGENCE_MATCH_WINDOW + 1)
    window_values = osc_values[lo:hi]
    window_dates = osc_dates[lo:hi]
    min_offset = int(window_values.argmin())
    return float(window_values[min_offset]), window_dates[min_offset]


def classify_swings(swings: list[SwingPoint], atr_by_date: dict, chaikin_osc: pd.Series) -> list[ClassifiedSwing]:
    """swings must be chronologically ordered (mixed highs/lows, as
    extract_swing_points returns). atr_by_date maps a swing's date to the
    ATR(14) value as of that date. chaikin_osc is the full date-indexed
    Chaikin Oscillator series (see ad_line.py), used only for LL swings'
    A/D Bullish Divergence check."""
    classified: list[ClassifiedSwing] = []
    highs_so_far: list[SwingPoint] = []
    lows_so_far: list[SwingPoint] = []
    confirmed_ll_osc_lows: list[float] = []

    osc_dates = [idx.date() if hasattr(idx, "date") else idx for idx in chaikin_osc.index]
    osc_values = chaikin_osc.to_numpy()
    osc_pos_by_date = {d: i for i, d in enumerate(osc_dates)}

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
                ratio = margin / atr

                ad_bullish_divergence = False
                ad_divergence_swing_date = None
                if kind == "LL":
                    matched_value, matched_date = _matched_oscillator_low(swing.date, osc_dates, osc_values, osc_pos_by_date)
                    if matched_value is not None and confirmed_ll_osc_lows:
                        osc_floor = min(confirmed_ll_osc_lows[-TRAILING_WINDOW:])
                        if matched_value > osc_floor:
                            ad_bullish_divergence = True
                            ad_divergence_swing_date = matched_date
                    if matched_value is not None and ratio >= CONFIRMED_RATIO:
                        # Appended AFTER computing this swing's own
                        # divergence above, so a swing never floors against
                        # itself.
                        confirmed_ll_osc_lows.append(matched_value)

                classified.append(
                    ClassifiedSwing(
                        swing=swing,
                        classification=kind,
                        margin=margin,
                        atr=atr,
                        ratio=ratio,
                        ad_bullish_divergence=ad_bullish_divergence,
                        ad_divergence_swing_date=ad_divergence_swing_date,
                    )
                )
            lows_so_far.append(swing)

    return classified
