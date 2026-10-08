"""Regenerates overall_verdict_cases.json, the case file shared by backend/tests/test_overall_multiplier.py and
frontend/lib/overallScore.test.ts (both implementations of Overall = Steps score x Moat multiplier must agree on every case).

Run from backend/:  uv run python tests/fixtures/generate_overall_verdict_cases.py

Curated and rounding cases are written by hand below; every `expected` block is produced by the backend implementation
(scoring/overall.py), which is the reference. `rounding_cases` are found by search: Steps score x multiplier lands on an exact .5 in
double arithmetic, where Python's round (half to even) and JavaScript's Math.round (half up) disagree. `parity_cases` are 150
random weight sets (seeded, so the file is reproducible). Pure: no DB, no network."""

import json
import math
import random
from pathlib import Path

from scoring.overall import (
    DEFAULT_NARROW_MOAT_MULTIPLIER,
    MOAT_NOT_RATED_NOTE,
    NARROW_MOAT_MULTIPLIER_OPTIONS,
    NO_MOAT_MULTIPLIER,
    WIDE_MOAT_MULTIPLIER,
    StepSnapshot,
    compute_overall_assessment,
)
from scoring.weights import BOUNDS, DEFAULT_WEIGHTS, OVERALL_TOTAL, OverallWeights, as_dict

KEYS = ("step1", "step2", "step4", "step5")
OUT = Path(__file__).parent / "overall_verdict_cases.json"


def verdict_for(score: int) -> str:
    return "Strong Pass" if score > 90 else "Pass" if score >= 70 else "Fail"


def step(key: str, score: int | None, verdict: str | None = None) -> dict:
    if verdict is None:
        verdict = "insufficient_data" if score is None else verdict_for(score)
    return {"key": key, "score": score, "verdict": verdict}


def steps_of(*scores) -> list[dict]:
    return [step(k, s) for k, s in zip(KEYS, scores)]


def expected(case: dict) -> dict:
    weights = OverallWeights(**case["weights"]["overall"]) if "weights" in case else DEFAULT_WEIGHTS.overall
    steps = [StepSnapshot(s["key"], s["key"], False, s["score"], s["verdict"]) for s in case["steps"]]
    result = compute_overall_assessment(
        steps, moat=case["moat"], weights=weights, narrow_multiplier=case.get("narrow_multiplier", DEFAULT_NARROW_MOAT_MULTIPLIER)
    )
    return {
        "status": result.status,
        "score": result.score,
        "verdict": result.verdict,
        "steps_score": result.steps_score,
        "moat_multiplier": result.moat_multiplier,
        "moat_note": result.moat_note,
        "caution_steps": result.caution_steps,
        "weak_steps": result.weak_steps,
        "caution_reasons": result.caution_reasons,
    }


def case(name: str, steps: list[dict], moat: str | None, **extra) -> dict:
    c = {"name": name, **extra, "steps": steps, "moat": moat}
    c["expected"] = expected(c)
    return c


def curated() -> list[dict]:
    w = lambda f, g, p, d: {"overall": {"financials": f, "growth": g, "profitability": p, "debt": d}}  # noqa: E731
    cases = [
        case("Narrow 0.85: Steps 83.8 x 0.85 = 71 (the Analysis card example)", steps_of(84, 84, 83, 84), "narrow_moat"),
        case("Wide, steps 90 (top of the Pass band)", steps_of(90, 90, 90, 90), "wide_moat"),
        case("Wide, steps 91 (Strong Pass)", steps_of(91, 91, 91, 91), "wide_moat"),
        case("Wide, steps 70 (Pass boundary)", steps_of(70, 70, 70, 70), "wide_moat"),
        case("Wide, steps 69 (Fail boundary)", steps_of(69, 69, 69, 69), "wide_moat"),
        case("Narrow 0.85, steps 100", steps_of(100, 100, 100, 100), "narrow_moat"),
        case("Narrow 0.85, steps 83 passes (70.55 -> 71)", steps_of(83, 83, 83, 83), "narrow_moat"),
        case("Narrow 0.85, steps 82: 69.7 rounds up to 70, a Pass at the boundary", steps_of(82, 82, 82, 82), "narrow_moat"),
        case("Narrow 0.85, steps 81 fails (68.85 -> 69)", steps_of(81, 81, 81, 81), "narrow_moat"),
        case("No Moat, steps 90", steps_of(90, 90, 90, 90), "no_moat"),
        case("No Moat, perfect steps reach exactly 70", steps_of(100, 100, 100, 100), "no_moat"),
        case("Unrated, steps 90 (scored as No moat, with the note)", steps_of(90, 90, 90, 90), None),
        case("Unrated, steps 76", steps_of(90, 80, 70, 60), None),
        case("Unrated, steps Fail (40)", steps_of(40, 40, 40, 40), None),
        case("Wide keeps Pass with caution", [step("step1", 100), step("step2", 100), step("step4", 100), step("step5", 74, "Pass with caution")], "wide_moat"),
        case("Narrow Pass with caution carries up", [step("step1", 100), step("step2", 100), step("step4", 100), step("step5", 74, "Pass with caution")], "narrow_moat"),
        case("Debt Fail (stored key, shown as May not pass) blends by its score; no hard-fail override", [step("step1", 95), step("step2", 95), step("step4", 95), step("step5", 55, "Fail")], "wide_moat"),
        case("Debt caution from an unrescued breach (74) carries up like any caution step", [step("step1", 90), step("step2", 90), step("step4", 90), step("step5", 74, "Pass with caution")], "wide_moat"),
        case("Fail stays Fail beside a caution step", [step("step1", 40), step("step2", 40), step("step4", 40), step("step5", 74, "Pass with caution")], "wide_moat"),
        case("Weak step on a Pass: Profitability 60 beside a Wide Pass reads Pass with caution", steps_of(90, 90, 60, 90), "wide_moat"),
        case("Weak step on a Strong Pass: Growth 65 beside 100s still reads Pass with caution", steps_of(100, 65, 100, 100), "wide_moat", weights=w(30, 5, 30, 35)),
        case("Several weak steps: Financials 60 and Debt 55 are both named", steps_of(60, 100, 100, 55), "wide_moat", weights=w(25, 25, 25, 25)),
        case("A step at exactly 70 is not weak", steps_of(70, 90, 90, 90), "wide_moat"),
        case("A step at 69 is weak", steps_of(69, 95, 95, 95), "wide_moat"),
        case("Step 5 exempt (Insurance): the exempt step is not weak, the rest are clean", [step("step1", 90), step("step2", 90), step("step4", 90), step("step5", None, "not_supported")], "wide_moat"),
        case("Step 5 exempt, another step weak: Pass with caution from the weak step only", [step("step1", 90), step("step2", 90), step("step4", 60), step("step5", None, "not_supported")], "wide_moat"),
        case("Step 5 caution plus a weak step: both reasons", [step("step1", 95), step("step2", 95), step("step4", 60), step("step5", 74, "Pass with caution")], "wide_moat"),
        case("Review-gated shape (Financials 45, Debt strong) is still just a weak step to the verdict", [step("step1", 45), step("step2", 100), step("step4", 100), step("step5", 100)], "wide_moat", weights=w(10, 30, 30, 30)),
        case("Weak step but a Fail overall stays Fail with no caution reasons", steps_of(40, 90, 60, 80), "narrow_moat"),
        case("Weak step, unrated: Fail stays Fail", steps_of(60, 100, 100, 100), None),
        case("A hard-fail verdict at a score of 70 or more is weak by its verdict", [step("step1", 90), step("step2", 90), step("step4", 72, "Fail"), step("step5", 90)], "wide_moat"),
        case("A step with insufficient data: incomplete (Wide cannot rescue it)", [step("step1", 90), step("step2", 90), step("step4", 90), step("step5", None)], "wide_moat"),
        case("A step with insufficient data, unrated: incomplete, no note", [step("step1", 90), step("step2", 90), step("step4", 90), step("step5", None)], None),
        case("Step 5 exempt (not_supported): the other three renormalize", [step("step1", 100), step("step2", 0, "Fail"), step("step4", 100), step("step5", None, "not_supported")], "wide_moat"),
        case("Step 5 exempt, Narrow 0.9", [step("step1", 90), step("step2", 80), step("step4", 70), step("step5", None, "not_supported")], "narrow_moat", narrow_multiplier=0.9),
        case("Every step exempt or missing: incomplete", [step("step1", None, "not_supported"), step("step2", None, "not_supported"), step("step4", None, "not_supported"), step("step5", None, "not_supported")], "wide_moat"),
        case("custom weights 10/30/30/30 (Financials at the floor), Wide", steps_of(95, 60, 80, 55), "wide_moat", weights=w(10, 30, 30, 30)),
        case("custom weights 50/5/5/40 (Financials at the cap), Narrow 0.87", steps_of(95, 60, 80, 55), "narrow_moat", weights=w(50, 5, 5, 40), narrow_multiplier=0.87),
        case("custom weights 25/25/25/25, unrated", steps_of(90, 80, 70, 60), None, weights=w(25, 25, 25, 25)),
        case("custom weights with Debt exempt renormalize the other three", [step("step1", 90), step("step2", 80), step("step4", 70), step("step5", None, "not_supported")], "narrow_moat", weights=w(15, 15, 15, 55)),
    ]
    for m in NARROW_MOAT_MULTIPLIER_OPTIONS:
        cases.append(case(f"Narrow multiplier {m:.2f}, steps 88", steps_of(88, 88, 88, 88), "narrow_moat", narrow_multiplier=m))
    return cases


def rounding_cases() -> list[dict]:
    """Uniform steps s with a multiplier m where round(s * m) is on an exact .5 whose floor is even (half-to-even rounds down, half-up
    rounds up): found by search against the real implementation."""
    found = []
    options = [("narrow_moat", m) for m in NARROW_MOAT_MULTIPLIER_OPTIONS] + [("no_moat", NO_MOAT_MULTIPLIER), (None, NO_MOAT_MULTIPLIER)]
    for moat, m in options:
        for s in range(30, 101):
            c = {"name": "", "steps": steps_of(s, s, s, s), "moat": moat}
            if moat == "narrow_moat":
                c["narrow_multiplier"] = m
            result = compute_overall_assessment(
                [StepSnapshot(x["key"], x["key"], False, x["score"], x["verdict"]) for x in c["steps"]],
                moat=moat, narrow_multiplier=c.get("narrow_multiplier", DEFAULT_NARROW_MOAT_MULTIPLIER),
            )
            product = result.steps_score * result.moat_multiplier
            if product % 1 == 0.5 and math.floor(product) % 2 == 0:
                c["name"] = f"rounding: steps {s} x {m} = exactly {product} ({moat or 'unrated'})"
                c["expected"] = expected(c)
                found.append(c)
                break
    return found


def parity_cases(n: int = 150, seed: int = 20261007) -> list[dict]:
    rng = random.Random(seed)
    lows = {k: v[0] for k, v in BOUNDS["overall"].items()}
    highs = {k: v[1] for k, v in BOUNDS["overall"].items()}
    fields = ["financials", "growth", "profitability", "debt"]
    verdicts = ["Fail", "Pass", "Strong Pass", "Pass with caution"]
    out = []
    while len(out) < n:
        weights = {f: rng.randint(lows[f], highs[f]) for f in fields}
        if sum(weights.values()) != OVERALL_TOTAL or any(weights[f] > highs[f] for f in fields):
            continue
        steps = []
        for k in KEYS:
            r = rng.random()
            if r < 0.07:
                steps.append(step(k, None, "not_supported"))
            elif r < 0.09:
                steps.append(step(k, None, "insufficient_data"))
            else:
                score = rng.randint(0, 100)
                steps.append({"key": k, "score": score, "verdict": rng.choice(verdicts)})
        moat = rng.choice(["wide_moat", "narrow_moat", "no_moat", None])
        c = {"name": f"parity {len(out)}", "weights": {"overall": weights}, "steps": steps, "moat": moat}
        if moat == "narrow_moat":
            c["narrow_multiplier"] = rng.choice(NARROW_MOAT_MULTIPLIER_OPTIONS)
        c["expected"] = expected(c)
        out.append(c)
    return out


def main() -> None:
    data = {
        "_comment": (
            "Shared by backend/tests/test_overall_multiplier.py and frontend/lib/overallScore.test.ts: both implementations of "
            "Overall = Steps score x Moat multiplier must produce these results. `moat` is wide_moat / narrow_moat / no_moat or null "
            "(unset, scored as No moat). A case's optional `weights.overall` is the saved weight set it runs under (absent = "
            "`defaults`) and its optional `narrow_multiplier` the saved Narrow setting (absent = defaults.narrow_multiplier). "
            "`rounding_cases` sit on an exact .5 (Python round is half to even, JS Math.round is not); `parity_cases` are generated "
            "random weight sets (expected values produced by the backend). Regenerate with "
            "`uv run python tests/fixtures/generate_overall_verdict_cases.py` from backend/."
        ),
        "defaults": {
            "overall": as_dict(DEFAULT_WEIGHTS.overall),
            "overall_total": OVERALL_TOTAL,
            "narrow_multiplier": DEFAULT_NARROW_MOAT_MULTIPLIER,
            "narrow_multiplier_options": list(NARROW_MOAT_MULTIPLIER_OPTIONS),
            "wide_multiplier": WIDE_MOAT_MULTIPLIER,
            "no_moat_multiplier": NO_MOAT_MULTIPLIER,
            "not_rated_note": MOAT_NOT_RATED_NOTE,
        },
        "cases": curated(),
        "rounding_cases": rounding_cases(),
        "parity_cases": parity_cases(),
    }
    OUT.write_text("{\n" + ",\n".join(f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in data.items()) + "\n}\n")
    print(f"wrote {OUT}: {len(data['cases'])} cases, {len(data['rounding_cases'])} rounding, {len(data['parity_cases'])} parity")


if __name__ == "__main__":
    main()
