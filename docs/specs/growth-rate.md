# Growth Rate

The Growth Rate card looks forward rather than backward — it asks "how much do analysts expect
this company to grow over the next few years?" It's built from two pieces:

- **Projected growth rate** — the expected annual growth rate between now and roughly four years
  out, based on analyst projections. Fathom prefers earnings-per-share (EPS) growth when it's
  usable, and falls back to revenue growth when EPS projections aren't usable (most often
  because the company's current earnings are negative, which makes an EPS growth rate
  mathematically meaningless).
- **REITs are the one exception** — they're scored on revenue (effectively rental income for
  this kind of company) rather than EPS, since REIT earnings are heavily distorted by non-cash
  depreciation on real estate, and the data source has no forward-looking dividend/distribution
  estimate to use instead. A note on the card explains this whenever it applies, alongside the
  company's historical dividend-per-share trend shown for context only (it doesn't affect the
  score).
- **Estimate agreement** — how tightly the individual analysts' estimates cluster around that
  average. If most analysts are projecting a similar number, that's read as higher-confidence; if
  the high and low estimates are far apart, that's read as genuine uncertainty about where the
  company is headed.

**Be aware: this is one data source, not several.** Fathom's growth methodology was originally
designed to average projections across several independent research platforms and check whether
they agree with each other. In practice, Fathom sources this data from a single provider's
analyst-estimates feed, which itself aggregates many individual analysts into one average, high,
and low estimate. So "estimate agreement" here means how much individual analysts covering the
stock agree with each other, not how much different research platforms agree with each other.
The app labels this explicitly wherever it's shown.

## What the verdict means

Growth Rate's verdict follows its score, like every other check: Fail below 70, Pass from 70,
Strong Pass above 90. It has no automatic fail of its own (the negative-growth hard fail was
removed on 2026-10-08). Two properties of the scoring keep the old behaviour without an override:
a negative projected growth rate cannot score 70 (its Magnitude points top out at 35), and a
projection that is zero or positive is never scored under 70, however scattered the estimates
(the score floor below).

- **Fail** (displayed "May not pass") — the score is under 70. In practice that is analysts
  projecting the company will actually shrink (negative growth): every negative rate scores under
  70. A zero-or-positive projection never lands here.
- **Pass** — analysts project positive growth, with the actual score reflecting both how strong
  that growth is and how much analysts agree on it.
- **Strong Pass** — a high score requires both a strong projected growth rate and
  tightly-clustered analyst estimates.

If there simply isn't enough analyst estimate data to compute a usable growth rate for a
company, Growth Rate reports **insufficient data** rather than treating the gap as a Fail. See
the [Glossary](glossary.md) for how every verdict label is defined.

---

## Technical reference

### Data source

Sourced entirely from FMP's `/analyst-estimates` endpoint, which aggregates individual analysts
into an average, high, and low estimate per future fiscal year. Only forward-dated rows
(estimate date after today) are used; past-dated rows in the same response are discarded.

### Base and target year selection

- **Base row**: the nearest forward-dated estimate row (earliest future date in the response).
- **Target window**: rows dated 3–5 years after the base year.
- **Target row**: within that window, the row closest to **4 years** after the base year. If no
  rows fall in the 3–5yr window at all, every remaining forward row is used as the candidate pool
  instead.
- Within the candidate pool, rows with a usable (non-null, non-zero) average estimate are
  preferred over rows without one — FMP sometimes reports a `0` average for sparsely-covered
  far-out years even when a nearer year in the same pool has a real estimate.

### Growth rate (CAGR)

```
growth_rate_pct = ((target_avg / base_avg) ^ (1 / years) − 1) × 100
```

where `years` is the whole-year gap between the base and target rows. Requires `base_avg > 0`, a
non-null/non-zero `target_avg`, and `years > 0`.

**EPS is preferred over Revenue.** The CAGR above is computed first using EPS average estimates
(`epsAvg`). If that doesn't yield a usable value — most commonly because the base-year EPS is
negative or zero — the same calculation is retried using Revenue average estimates
(`revenueAvg`). Whichever field actually produced a usable value determines the `basis`
(`"eps"` or `"revenue"`) reported alongside the score. This is also reused directly as
Valuation's Yr 1-5 growth input (`growth_yr_1_5` in [Valuation](valuation.md)), so this basis
choice changes Valuation outputs project-wide, not just Growth Rate's own verdict.

The EPS-first preference is a deliberate reversal of the app's original revenue-first choice.
Revenue was originally preferred because EPS is more exposed to buyback and margin-expansion noise
than the underlying growth story; that reasoning still holds, but EPS growth is now judged the more
decision-relevant figure for this methodology and the noise tradeoff is accepted. `basis` in
`Step2Out` reflects whichever field actually produced the score, and the UI and Valuation-input
labeling read it dynamically, so nothing hardcodes "Revenue".

**REIT / Property Developer override.** REIT tickers skip the EPS attempt entirely and are
always scored on Revenue — not just as a fallback, but as the sole basis. Two reasons: EPS is
depreciation-heavy and doesn't reflect REIT economics (confirmed real case: several REITs failed
Growth Rate purely from EPS/depreciation noise while every one passes cleanly on a Revenue
basis); and DPU (distribution/dividend per share) growth — the metric this methodology's own
framework calls for — has no forward-looking equivalent in FMP's data (no forward DPU/dividend
estimate field exists). Revenue is used in its place because REIT revenue is already effectively
rental income for this universe, so Revenue growth already reads as rental-income growth
without needing a new metric. A REIT-specific `growth_basis_note` explains this on the card;
historical (trailing) DPU/share growth is also surfaced as a separate, purely informational note
(`dpu_growth_note`), never scored.

### Estimate agreement (spread)

For the same target year:

```
spread_pct = (high_estimate − low_estimate) / average_estimate × 100
```

using the high/low/average fields matching whichever basis produced the growth rate. If the
spread can't be computed, it defaults to 100% (maximally wide/uncertain) for scoring purposes
only. The result is an **analyst estimate range**, not cross-platform consensus, and is labeled as
such in the API and UI (`core/schemas.py::Step2Out`, `frontend/components/step2/Step2Card.tsx`) so
it is never mistaken for the original methodology's cross-platform agreement check. The average
projected growth rate (CAGR from the nearest forward estimate to the one closest to 4 years out)
stands in for what a cross-platform average would have been.

### Scoring

**Magnitude tiers** (on `growth_rate_pct`, half-open `[low, high)`):

| Growth rate | Tier | Points |
|---|---|---|
| > 15% | strong | 100 |
| 10% – 15% | solid | 85 |
| 5% – 10% | modest | 65 |
| 0% – 5% | weak | 40 |
| -10% – 0% | mildly_negative | graduated, 10–35 |
| < -10% | negative | 0 |

**Negative-magnitude graduated scale (2026-08-13)**: below 0%, points scale linearly from **35**
(near 0%) down to **10** (at `MAGNITUDE_SEVERE_NEGATIVE` = -10%, a first-pass round-number choice
mirroring the `solid` tier's own magnitude) — the ceiling is deliberately kept below the `weak`
tier's 40, so a mildly-negative ticker can never outscore a genuinely-positive-but-weak one.
Beyond -10%, the tier is still a flat 0. The flat 0 used to apply to *any* negative growth, so a
projection statistically indistinguishable from flat (-0.03%) scored identically to a genuine
collapse (-60%). At the time of the change, 27 tickers hit this branch: 20 sat at or above -9.0%
("mildly negative") and only 7 were genuinely severe (the tail from -10.8% to -60%).

**Why a negative rate can never pass (2026-10-08).** The best Magnitude a negative rate can score
is **35** (the ceiling of the graduated scale, approached as the rate nears 0%), below the `weak`
tier's 40. With Agreement at its best (100) the blend is `35×0.70 + 100×0.30 = 54.5` at the
70/30 defaults, and `35×0.50 + 100×0.50 = 67.5` (reads 68) at the loosest allowed weights
(Magnitude 50 / Agreement 50, the bounds in `scoring/weights.py::BOUNDS["step2"]`). Both are under 70,
so no override is needed. That guarantee rests on exactly two things: the 35 ceiling and the
weight bounds (Magnitude at least 50, Agreement at most 50). It is guarded by
`scoring/test_step2.py::test_negative_growth_ceiling_stays_below_pass_line_at_loosest_weights`,
which sweeps every allowed weight split and a spread of negative rates and fails if any reaches 70.
Raise the ceiling, loosen the bounds or change the blend and that test (not a runtime rule) is
what catches it. The Score floor is gated on `growth_rate_pct ≥ 0` directly, never on the
magnitude score's value, so a mildly-negative ticker's nonzero magnitude score cannot trip it.

**Agreement tiers** (on `spread_pct`):

| Spread | Tier | Points |
|---|---|---|
| < 10% | tight | 100 |
| 10% – 20% | moderate | 60 |
| > 20% | wide | 20 |

**Blend**: `score = round(magnitude_points × w_m + agreement_points × w_a)`, clamped to
[0, 100], where the weights default to **70 / 30** and are adjustable (Settings > Score weighting; Magnitude 50-100, Agreement 0-50,
adding up to 100). A weight of 0 leaves that component out of the blend only; the 70 floor below reads no weights.

**Score floor** (`PASS_SCORE_FLOOR`): whenever `growth_rate_pct ≥ 0`, the blended score is floored
at **70** if it would otherwise land lower. This raises only the displayed score for an
already-passing result — it never touches `magnitude_score`/`agreement_score` (the UI's breakdown
still shows the raw component tiers), and it can never push a score into Strong Pass range
(floor 70 < the >90 threshold). A negative-growth result is never floored and displays its real
sub-70 score. The floor applies at **every** growth rate from exactly 0% up (the test is
`growth_rate_pct >= 0`), not above some higher rate: +0.1% growth is lifted to 70 while -0.1%
keeps its real score (54 with perfect Agreement), a deliberate step at 0%.

Why the floor exists: because the verdict is not gated on the blended score, a weak-but-positive
projection (a "weak" 40-point magnitude tier with a "tight" 100-point agreement tier blends to
`40×0.70 + 100×0.30 = 58`) would otherwise show a Fail-range number next to "Pass" text — and be
coloured by the shared color system (amber then; since 2026-10-08 a plain 70-74 Pass is green) (`frontend/lib/tierColor.ts`), which has no visibility
into Growth Rate's different verdict semantics.

### Verdict

Follows the blended score alone (`step2.py::_verdict_for`), the same bands as every other step:

- **Strong Pass** if the blended score is **> 90**.
- **Pass** if it is **70–90**.
- **Fail** (stored key; displayed "May not pass") below **70**.

There is no negative-growth override (removed 2026-10-08, docs/decisions.md). It never changed a
score, and every negative rate already scores under 70 (see above), so no score or verdict moved
when it went. Because the floor lifts every non-negative rate to 70, only a negative rate can read Fail.

### Insufficient data

If neither EPS nor Revenue yields a usable CAGR (too few or no forward estimate rows, including
a failed upstream data fetch — `cache.py::safe_fetch` swallows the error to `{}`,
indistinguishable from a genuinely thin response), the check returns `score: null,
verdict: "insufficient_data"` rather than a fabricated `score: 0` Fail (the convention Profitability
and Debt already used). A prior version scored these identically to a genuinely weak or negative
projection, feeding a false Fail into Overall Assessment's blend and the Screener with no way to
tell "no data" from "bad growth". This also
feeds `scoring/overall.py`'s existing "any null-score/non-`not_supported`step is incomplete"
rule, so the whole Overall Assessment is marked incomplete for these tickers rather than folding
a false Fail into the blend.

### Growth catalysts

Growth catalysts (originally envisioned as qualitative research into why a company is expected
to grow) are a manually-curated free-text field (`models.py::GrowthCatalystNote`), not factored
into the score. No edit UI exists yet; it's backend-settable only.
