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

Growth Rate has one deliberate difference from every other check in Fathom: **a company is only
marked Fail if its projected growth rate is negative.** A modest-but-positive growth projection,
even a fairly weak one, is never scored as an outright Fail — scattered, disagreeing estimates
lower the score, but they don't flip a positive growth projection into a Fail by themselves.

- **Fail** — analysts project the company will actually shrink (negative growth).
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
only.

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
tier's 40. Beyond -10%, the tier is still a flat 0.

This graduated score is display/blend-only — it does **not** change the Verdict section below.
Fail is gated on `growth_rate_pct`'s sign directly, and the Score floor is likewise gated on
`growth_rate_pct ≥ 0` directly — both deliberately decoupled from the magnitude score's value, so
a mildly-negative ticker's now-nonzero magnitude score can never accidentally trip either
mechanism into a false Pass.

**Agreement tiers** (on `spread_pct`):

| Spread | Tier | Points |
|---|---|---|
| < 10% | tight | 100 |
| 10% – 20% | moderate | 60 |
| > 20% | wide | 20 |

**Blend**: `score = round(magnitude_points × 0.70 + agreement_points × 0.30)`, clamped to
[0, 100].

**Score floor**: whenever `growth_rate_pct ≥ 0`, the blended score is floored at **70** if it
would otherwise land lower. This raises only the displayed score for an already-passing result —
it never touches the component scores themselves, and it can never push a score into Strong Pass
range (floor 70 < the >90 threshold). A negative-growth (Fail) result is never floored.

### Verdict

Deliberately **not** gated on the blended score:

- **Fail** if and only if `growth_rate_pct < 0` — regardless of the blended score.
- **Strong Pass** if the blended score is **> 90**.
- **Pass** otherwise.

### Insufficient data

If neither EPS nor Revenue yields a usable CAGR (too few or no forward estimate rows, including
a failed upstream data fetch — indistinguishable from a genuinely thin response), the check
returns `score: null, verdict: "insufficient_data"` rather than a fabricated Fail. This also
feeds `scoring/overall.py`'s existing "any null-score/non-`not_supported`step is incomplete"
rule, so the whole Overall Assessment is marked incomplete for these tickers rather than folding
a false Fail into the blend.

### Growth catalysts

Growth catalysts (originally envisioned as qualitative research into why a company is expected
to grow) are a manually-curated free-text field (`models.py::GrowthCatalystNote`), not factored
into the score. No edit UI exists yet; it's backend-settable only.
