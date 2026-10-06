"""The one definition of every adjustable score weight: the shape of a weight set, its defaults and the pure derivations
the scorers share (docs/specs/overview.md, "Overall weighting").

Pure: no I/O, no DB. A `ScoreWeights` is handed to the scorers as a parameter (defaulting to `DEFAULT_WEIGHTS`); where it is
saved and loaded is data/score_weights.py. Weights are whole numbers; the scorers never assume they sum to anything, they divide
by the sum of the components that actually apply, so any weight set works and a component that does not apply to a company
(an exempt type, a dropped metric) simply leaves the others to share its weight.

Economic Moat's 31% is NOT part of a weight set (scoring/overall.py::MOAT_WEIGHT): it is a constant, never saved, never accepted
as input.
"""

from dataclasses import dataclass
from typing import Iterable, Mapping

# The four automated steps share this many points of Overall (the rest, 31, is Moat's).
OVERALL_TOTAL = 69
# Every step's own component set sums to this.
STEP_TOTAL = 100


@dataclass(frozen=True)
class OverallWeights:
    financials: int  # Step 1
    growth: int  # Step 2
    profitability: int  # Step 4
    debt: int  # Step 5


@dataclass(frozen=True)
class Step1Weights:
    revenue: int
    net_income: int
    cfo: int
    margins: int
    fcf: int


@dataclass(frozen=True)
class Step2Weights:
    magnitude: int
    agreement: int


@dataclass(frozen=True)
class Step4Weights:
    roe: int
    roic: int
    ar: int
    ccc: int


@dataclass(frozen=True)
class Step5Weights:
    current_ratio: int
    debt_to_ebitda: int
    debt_servicing: int


@dataclass(frozen=True)
class ScoreWeights:
    overall: OverallWeights
    step1: Step1Weights
    step2: Step2Weights
    step4: Step4Weights
    step5: Step5Weights


# The single source for the lazy seed, the reset and the tests. Step 5's default is 33/33/34 (Current Ratio, Debt/EBITDA, Debt
# Servicing): whole numbers cannot express exact thirds, so the third ratio carries the odd point (2026-10-06 decision).
DEFAULT_WEIGHTS = ScoreWeights(
    overall=OverallWeights(financials=24, growth=10, profitability=20, debt=15),
    step1=Step1Weights(revenue=35, net_income=20, cfo=30, margins=10, fcf=5),
    step2=Step2Weights(magnitude=70, agreement=30),
    step4=Step4Weights(roe=25, roic=35, ar=20, ccc=20),
    step5=Step5Weights(current_ratio=33, debt_to_ebitda=33, debt_servicing=34),
)


def as_dict(group) -> dict[str, int]:
    """One group's fields, in declaration order, as a plain dict (the keys the scorers use)."""
    return {name: getattr(group, name) for name in group.__dataclass_fields__}


def normalize(weights: Mapping[str, int | float], applicable: Iterable[str]) -> dict[str, float] | None:
    """Each applicable component's share of the applicable total, in the order given. None when that total is not positive
    (every applicable weight is 0): the caller treats that as its existing "cannot be scored" outcome, never a division by
    zero. A weight of 0 on an applicable component is a legitimate share of 0: the component is not counted in the blend."""
    keys = list(applicable)
    total = sum(weights[key] for key in keys)
    if total <= 0:
        return None
    return {key: weights[key] / total for key in keys}


def overall_fractions(weights: OverallWeights) -> dict[str, float]:
    """Each automated step's share of the 69 points (the keys scoring/overall.py's steps use). Not renormalized: the
    caller renormalizes across the steps that apply."""
    return {
        "step1": weights.financials / OVERALL_TOTAL,
        "step2": weights.growth / OVERALL_TOTAL,
        "step4": weights.profitability / OVERALL_TOTAL,
        "step5": weights.debt / OVERALL_TOTAL,
    }


def step1_tables(
    weights: Step1Weights,
) -> tuple[dict[str, float] | None, dict[str, float] | None, dict[str, float] | None]:
    """(standard, CFO/FCF-exempt, Bank) weight tables for Step 1, derived from one base set by the same procedures the
    scorer always used. Each is None when it cannot be built (a zero total), which the scorer reads as insufficient data.

    - standard: the base set as shares of its total.
    - CFO/FCF-exempt (Bank, Insurance, REIT/Property Developer, Commodity Company): CFO's and FCF's combined weight is
      split EQUALLY across Revenue, Net Income and Margins. A target whose own weight is 0 is not counted in the blend and
      gets no share (Margins at 0 stays 0).
    - Bank: Margins is also dropped; its weight is spread PROPORTIONALLY over Revenue and Net Income (28/47 and 19/47 at the
      defaults), not split equally and not returned to the standard ratio."""
    base = as_dict(weights)
    standard = normalize(base, base)
    if standard is None:
        return None, None, None

    targets = [key for key in ("revenue", "net_income", "margins") if standard[key] > 0]
    if not targets:
        return standard, None, None
    bonus = (standard["cfo"] + standard["fcf"]) / len(targets)
    cfo_exempt = {key: (standard[key] + bonus if key in targets else 0.0) for key in standard}
    cfo_exempt["cfo"] = 0.0
    cfo_exempt["fcf"] = 0.0

    revenue_and_net_income = cfo_exempt["revenue"] + cfo_exempt["net_income"]
    if revenue_and_net_income <= 0:
        return standard, cfo_exempt, None
    bank = {
        "revenue": cfo_exempt["revenue"] / revenue_and_net_income,
        "net_income": cfo_exempt["net_income"] / revenue_and_net_income,
        "cfo": 0.0,
        "margins": 0.0,
        "fcf": 0.0,
    }
    return standard, cfo_exempt, bank
