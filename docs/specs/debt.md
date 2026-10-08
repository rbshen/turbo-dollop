# Debt

The Debt card is a conservative check on whether a company's debt load is safe — it's built to
behave like a bankruptcy-risk filter. For most companies
("Standard" — see [Company type variations](company-type-variations.md)), it looks at three
things:

- **Current Ratio** — can the company cover its short-term (within one year) obligations with
  its short-term assets? A low ratio suggests a real near-term liquidity risk.
- **Debt / EBITDA** — how large the company's total debt is relative to its annual earnings
  (before interest, tax, depreciation, and amortization). A high ratio means debt is large
  relative to what the business actually earns.
- **Debt Servicing Ratio** — how much of the company's earnings are consumed just by servicing
  (paying interest and principal on) its debt. A high burden here means less room to absorb a
  downturn.

## A breach scores low, and the weights keep it from passing

Since 2026-10-07 Debt is a **pure weighted blend** of the three ratios' sub-scores (0–100 each); no single
ratio can force the verdict by itself. A ratio in breach scores 0 (or, past the Severe line, 15 sliding
to 0) instead of failing the card outright, and the weights — Debt/EBITDA 45, Debt Servicing 30,
Current Ratio 25 by default — do the rest: because Debt/EBITDA carries so much of the blend, a
Debt/EBITDA breach (or negative EBITDA) cannot be averaged away by healthy ratios elsewhere, however
good they are. The bounds and the strict order Debt/EBITDA > Debt Servicing > Current Ratio in
Settings exist to guarantee exactly that (see "Weights and bounds" below).

**70 or more passes; below 70 reads "May not pass"** on every Debt surface. That wording is display
only: the stored verdict key is still `Fail` (Overall, the Screener and the Watchlist
read it unchanged). Since 2026-10-08 every other step and the Overall verdict display their stored `Fail` as "May not pass" too
(`verdictDisplay` in `frontend/lib/tierColor.ts`).

## Borderline breaches get a second look

Not every breach is treated the same. A ratio that's only moderately over its safe threshold
gets a closer, second look before Fathom settles on a Fail — checking things like whether the
company's debt burden has been improving over time, whether free cash flow comfortably covers
total debt, and whether earnings comfortably cover interest payments. If enough of that
supporting evidence looks favorable, the result downgrades from a hard Fail to **Pass with
caution** rather than a clean Pass. A severe breach — well beyond the borderline zone — never
gets this second look; it scores 15 points at most.

Separately, for the Current Ratio specifically, some companies collect cash from customers
before delivering the product or service. That cash is booked as a liability ("deferred
revenue") even though it isn't really money the company owes anyone. Fathom checks for this and
can rescue an apparently weak Current Ratio when a low ratio turns out to be explained by this
pattern.

## When a ratio can't be meaningfully calculated

- **Negative earnings (Debt / EBITDA)** — not generating positive operating earnings at all is
  itself a real weakness, so it scores 0 and stays in the blend, the same as a genuine breach. The
  weights alone keep the card below 70 (see "Weights and bounds").
- **Negative operating cash flow (Debt Servicing Ratio)** — often a temporary, seasonal swing
  rather than a sign the company can't service its debt. Fathom sets Debt Servicing Ratio aside
  for that period and lets Current Ratio and Debt/EBITDA carry the full weight instead — it's
  set aside rather than counted as either a pass or a fail.

## Banks, Insurance companies, and REITs are judged differently

- **Banks** are judged on **capital adequacy** — a CET1 (Common Equity Tier 1) ratio — combined
  with a **Non-Performing Loan (NPL) ratio**. FMP doesn't publish CET1 data, so this figure must
  be entered manually before a Bank ticker gets a real Debt verdict; until then, it displays as
  **not supported**. NPL is computed automatically where the underlying data is available, and
  can also be manually overridden. A small number of tickers classified as Banks by sector/
  industry text aren't actually deposit-taking lenders (confirmed via a genuine-deposit-liability
  XBRL-tag check, see [Company type variations](company-type-variations.md)) — those tickers are
  reclassified out of Bank altogether, so they get the Standard path instead (see "Bank path"
  below).
- **Insurance companies** aren't judged on these ratios at all — no reliable substitute
  capital-adequacy signal is currently available for insurers from Fathom's data provider.
  Insurance tickers show as **not supported** for Debt.
- **REITs and Property Developers** are judged on a **Gearing ratio** instead — total debt
  relative to total assets.

## What the verdict means

- **May not pass** (stored as `Fail`) — the score is below 70. A Bank or REIT whose limit is breached
  always lands there (see "Bank path"); no Debt path has a hard fail any more.
- **Pass, ratio in breach** (stored as `Pass with caution`; display only since 2026-10-08) — the blend is 70 or more, but it contains
  a real breach: one a legitimate offsetting factor resolved, or one nothing excused that the other ratios outweighed. The card
  names the breached ratio. Treat this as "barely passing" (capped at 74), not equivalent to a clean Pass. The label is the Debt
  step's own word (`frontend/lib/tierColor.ts::debtVerdictDisplay`); "Pass with caution" now means the Overall verdict only, and the
  Overall card says "because Debt passed with a ratio in breach" when this is the reason. The stored value, the API value, the amber tone and
  `SCORE_FORMULA_VERSION` are unchanged.
- **Pass** — 70 to 90 with no ratio in breach.
- **Strong Pass** — above 90 with every ratio in safe territory.
- **Not supported** — this company type doesn't have a reliable way to compute this check with
  the data currently available.

See the [Glossary](glossary.md) for how every verdict label is defined.

---

## Technical reference

### Company-type routing

- **Bank** → CET1 + NPL path.
- **Insurance** → always `not_supported`, no ratios attempted at all.
- **REIT/Property Developer** → Gearing Ratio path.
- **Utility, Commodity, and every other type** → Standard path (Utility is **not** exempted
  here, unlike its exemptions in Profitability).

The type comes from a best-effort sector/industry text match, so it is surfaced rather than
hidden: `Step5Out.classification_note` (default text: "Best-effort classification from
sector/industry text — not a certified determination.") is shown in the UI/API, since a
misclassified ticker would silently apply the wrong ratio set. Insurance is checked before Bank
(both sit in "Financial Services"); see [Company type variations](company-type-variations.md)
for the detection order and the manually-verified overrides.

### Standard path: the three ratios

All figures are the latest reported quarter (balance sheet) or trailing twelve months (flow
figures), never fiscal-year-end. When FMP's newest quarterly balance sheet is partly filled in
(debt or current assets remapped into another line), the prior quarter's balance sheet is used
instead and the TTM windows are aligned to it — see
[Statement data quality](statement-data-quality.md), "Newest-quarter completeness gate". The ticker header's Total debt and
EBITDA tiles read the same cleaned rows through the shared loader, so they match this card.

```
Current Ratio            = Current Assets / Current Liabilities
Adjusted Current Ratio    = Current Assets / (Current Liabilities − Deferred Revenue)
Debt / EBITDA             = (Short-Term Debt + Long-Term Debt) / EBITDA (TTM)
Debt Servicing Ratio (%)  = Net Interest Expense (TTM) / CFO (TTM) × 100
Interest Coverage Ratio   = EBIT (TTM) / Interest Expense (TTM, gross, not netted)
```

`Net Interest Expense (TTM)` is `max(0, −Net Interest Income TTM)` — a company earning net
interest income has no interest burden for this ratio. The Adjusted Current Ratio falls back to
the raw ratio if subtracting deferred revenue would leave a non-positive denominator.

**Severity bands.** Comfortable is the check's original threshold; Borderline/Severe are
gradations beyond it — a Borderline breach gets the second look below before failing; Severe
never does.

| Ratio | Comfortable | Borderline | Severe |
|---|---|---|---|
| Current Ratio | ≥ 1.0 | 0.7 – 1.0 | < 0.7 |
| Debt / EBITDA | ≤ 3.0 | 3.0 – 4.0 | > 4.0 |
| Debt Servicing Ratio | < 30% | 30% – 40% | ≥ 40% |

**Severe zone's graduated display (2026-08-13)**: Debt/EBITDA and DSR's Severe points graduate
linearly instead of a flat 0 — 15 points (at the boundary) down to 0 (Debt/EBITDA at 10.0×,
`DEBT_EBITDA_SEVERE_FLOOR_RATIO`, 2.5× the 4.0× boundary; DSR at 120%, `DSR_SEVERE_FLOOR_PCT`,
3× the 40% boundary; floors chosen from the real tracked-universe distribution, covering 92%/59%
of actual Severe tickers). The ramp is `round(15 × (1 − (value − boundary) / (floor − boundary)))`
(`_graduated_severe_points`), and anything at or beyond the floor scores 0. Since 2026-10-07 these points are real blend inputs
(they were display-only while a hard fail forced the verdict); `label` stays `"severe"` and the
ratio stays flagged as an unrescued breach for the whole zone. The 15-point ceiling is kept below
`MARGINAL_SCORE_FLOOR` (40) so even the least-bad Severe reading can never numerically outscore
a genuine rescue. Current Ratio's Severe zone is unchanged.

**Comfortable-zone sub-tiers:**

| Current Ratio | Tier | Points | | Debt / EBITDA | Tier | Points | | Debt Servicing Ratio | Tier | Points |
|---|---|---|---|---|---|---|---|---|---|---|
| > 2.0 | excellent | 100 | | ≤ 1.0 | excellent | 100 | | < 10% | excellent | 100 |
| 1.5 – 2.0 | good | 85 | | 1.0 – 2.0 | good | 85 | | 10% – 20% | good | 85 |
| 1.0 – 1.5 | acceptable | 70 | | 2.0 – 3.0 | acceptable | 70 | | 20% – 30% | approaching_limit | 60 |

**Current Ratio's deferred-revenue rescue.** If the raw ratio is already ≥ 1.0, scored off the
raw value directly. If the raw ratio is below 1.0 but the adjusted ratio reaches ≥ 1.0, it's
rescued: scored off the adjusted ratio's own Comfortable-zone tier, flagged
`saved_by_tiebreaker`. If the adjusted ratio is still below 1.0 but at least 0.7, it's
`borderline_fail` (0 points, eligible for breach-context below). Below 0.7, `severe` (0 points,
no second look).

**Debt/EBITDA and DSR's Borderline zone.** Debt/EBITDA Borderline always starts as an unrescued
breach (0 points), then gets the richer breach-context evaluation below. DSR Borderline uses a narrower,
separate rescue: if ICR is "safe" (**> 3.0×**), the breach is excused to
`borderline_saved_by_icr`, flat **60 points**, `saved_by_tiebreaker`. If ICR isn't safe, it
stays an unrescued breach (0 points) — the only rescue mechanism available to DSR, never a subject of the
breach-context framework, only one of its **inputs**.

| ICR | Classification |
|---|---|
| > 3.0× | safe |
| 1.0× – 3.0× | tight |
| < 1.0× | dangerous |
| unavailable | not_applicable |

**When Debt/EBITDA or DSR is undefined.** EBITDA ≤ 0 → `negative_ebitda`, 0 points, flagged as an
unrescued breach, stays IN the blend (2026-08-06 fix; previously read `insufficient_data`, silently
blanking the entire Overall Assessment) — also fails Current Ratio's own breach-context primary
gate. With the hard fail gone (2026-10-07) it is the weights that end it below 70: at best 100 × (the
other two ratios' share), at most 59 for any saveable weight set. CFO ≤ 0 or unavailable → `excluded_negative_cfo` (2026-08-06 fix), a genuine
neutral exclusion (`RatioResult.excluded=True`), drops out of the blend (see below) and its
weight is redistributed across Current Ratio and Debt/EBITDA in proportion (25:45 at the defaults) — the same
proportional redistribution [Profitability](profitability.md) uses for its exempt metrics. Also
fails both breach-context frameworks' primary gates. A temporary or seasonal negative-CFO period
(a working-capital cycle, an inventory buildup) isn't evidence DSR itself is unhealthy, unlike
negative EBITDA, which is why the two are treated asymmetrically.

Both cases matter beyond Debt: `insufficient_data` (the old behaviour for both) marks the whole
Overall Assessment incomplete, whereas a genuine exemption or a real Fail stays in the blend —
see [Overview](overview.md), "What happens if a check can't be completed". `step5_data.py` now
reads `insufficient_data` only when Total Debt or TTM EBITDA is genuinely *missing*, not when
EBITDA is present but non-positive.

### Breach-context framework (Debt/EBITDA and Current Ratio, Borderline only)

**Primary gates** (must both pass cleanly, using literal raw values):

| Breach being evaluated | Gate 1 | Gate 2 |
|---|---|---|
| Debt/EBITDA | Current Ratio (raw) ≥ 1.0 | Debt Servicing Ratio < 30% |
| Current Ratio | Debt/EBITDA ≤ 3.0 | Debt Servicing Ratio < 30% |

If either gate fails, the ratio stays an unrescued breach (0 points). Using the OTHER ratios' *raw* values as
primary gates (2026-08-01) is a deliberate real behavior change — a DSR that itself needed
rescuing isn't "clean" enough to vouch for a different ratio's rescue.

**Secondary signals** are `favorable`, `unfavorable`, or `not_computable`. Two per ratio are
always informational-only:

**Debt/EBITDA's:** 5yr trend (declined >10% relative), FCF vs. Total Debt (TTM FCF positive and
≥15% of total debt), Interest Coverage (safe), Cause of debt (informational only), Net Debt vs.
Gross Debt (informational only).

**Current Ratio's:** Deferred revenue (≥15% of current liabilities), 5yr trend (not materially
declined), Cash position (≥50% of current liabilities), Asset quality (liquid current assets
≥50% of total current assets), Undrawn revolving credit (informational only).

Cause of debt, undrawn revolving credit and Net-vs-Gross Debt are **never scored** (neither is
reliably determinable from the provider's structured data); each always renders an explicit
manual-check note in the reasoning instead of being silently omitted. The two evaluators are
`evaluate_debt_to_ebitda_breach_context` and `evaluate_current_ratio_breach_context` in
`scoring/step5.py`; both guard a `None` `debt_to_ebitda`/`debt_servicing_pct` input (negative
EBITDA, or DSR excluded for negative CFO) by treating an undefined ratio the same as a real
breach for gating purposes — it can't vouch for another ratio's rescue any more than a bad one
could.

**Qualification and grading.** Among computable signals that count toward the gate, a strict
majority must be favorable:

```
score = round(40 + (60 − 40) × favorable_fraction)
```

Relabeled `marginal_via_breach_context`, flagged `saved_by_tiebreaker`. If it doesn't qualify,
the ratio stays at its plain Borderline result (0 points).

### Blend and verdict (Standard path)

Default base weights are **Current Ratio 25 / Debt/EBITDA 45 / Debt Servicing 30** (2026-10-07; they were
33/33/34 before). See `scoring/weights.py::DEFAULT_WEIGHTS.step5` and "Weights and bounds" below.

```
applicable = {current_ratio, debt_to_ebitda, debt_servicing_ratio} minus
             whichever is excluded this period (only debt_servicing_ratio can be excluded)
weight[r]  = base[r] / sum(base[a] for a in applicable)    # base = 25 / 45 / 30 (Current Ratio, Debt/EBITDA, Debt Servicing)
score      = round(sum(points[r] * weight[r] for r in applicable))
```

```
unrescued_breaches  = applicable ratios in an unrescued breach zone (Borderline not excused, Severe, negative EBITDA)
saved_by_tiebreaker = any of the 3 was rescued (deferred revenue, ICR-on-DSR, or either breach-context downgrade)
caution             = saved_by_tiebreaker or unrescued_breaches is non-empty
```

If `caution` and the blend is 70 or more, the blended score is capped at **74**
(`PASS_WITH_CAUTION_SCORE_CAP`) — for both kinds of caution, so a breach nothing excused reads like a
rescued one: barely passing. The cap never raises a lower blend and never changes pass/fail. This cap is
separate from `BORDERLINE_SAVED_SCORE` (60), the points an individual rescued ratio scores. **Why a
blend cap is needed**: Current Ratio's deferred-revenue rescue re-scores off the *adjusted* ratio's own
Comfortable-zone tier (up to 100), unlike the ICR rescue on Debt/EBITDA and DSR, which is always flat-capped at 60 — so a
rescued Current Ratio could blend to 95-100 despite a real breach (ADBE at 95 and AMP at 100 were
the real cases). The verdict text already couldn't say "Strong Pass" for a saved breach, but a
95-100 *number* beside an amber "caution" badge still read as contradictory. 74 is the top of
the 70-74 band (the same shade as any plain Pass since 2026-10-08; only the "caution" amber singles it out), so a
caution ticker reads as barely passing.

**Verdict**, in order (`_standard_verdict`):
1. `score < 70` → `Fail` (stored key; displayed "May not pass"). Nothing else can force this.
2. `caution` → stored `Pass with caution`, drawn "Pass, ratio in breach" (the card names every breached ratio).
3. `score > 90` → Strong Pass.
4. Otherwise → Pass.

No Debt path has a `hard_fail` flag any more (the payload field was removed 2026-10-08, with the Bank and REIT hard fail).
`unrescued_breaches` lists the breached ratio keys (Bank: `cet1_ratio` / `npl_ratio`; REIT: `gearing_ratio`).

Missing Current Ratio outright, or missing Total Debt/EBITDA data outright (not merely EBITDA
being non-positive) → `insufficient_data`.

### Weights and bounds

Saved in Settings > Score weighting (`ScoreWeightSettings`, `step5_*`; defaults 25/45/30). With no hard
fail the weights alone keep a breach below the Pass line, so the Step 5 bounds are tighter than the other
steps': Debt/EBITDA **35–60**, Debt Servicing **15–30**, Current Ratio **15–30**, whole numbers adding up
to 100, and a **strict order Debt/EBITDA > Debt Servicing > Current Ratio**
(`scoring/weights.py::BOUNDS`, `ORDERINGS`, `validate_group`; the endpoint serves them, the Settings form
checks the order live and `PUT` answers 422 with "Debt weights must keep this order, each strictly
larger than the next: Debt/EBITDA > Debt Servicing Ratio > Current Ratio."). With the sum of 100 and the 30
caps the lowest Debt/EBITDA weight in use is 41 (41/30/29). For every set that passes validation
(`test_no_valid_step5_set_lets_negative_ebitda_or_a_debt_ebitda_breach_reach_70`): negative EBITDA, a
Debt/EBITDA of 3.01× with no rescue and a severe Debt/EBITDA of 4.01× each end below 70 even when the other two ratios
are perfect (or Debt Servicing is excluded).

A row saved before 2026-10-07 that breaks these rules (the old 33/33/34 does) is replaced by the new
defaults at start-up (`core/db.py::_migrate_step5_weights`, `weights_version` +1, logged); until then
`data/score_weights.py` serves the default Step 5 set for it, so no process scores with weights that
would let a breach pass.

### Scenario table (default weights 25/45/30)

Sub-scores come from the unchanged curves above. "Limit" is the boundary value (the top of the
acceptable band: Debt/EBITDA 3.0×, Debt Servicing 30%, Current Ratio 1.0); "just past" is one
step beyond it with no rescue, where the sub-score drops to 0 (a cliff, as before — the old hard fail
was the same cliff in the verdict).

| Scenario | Sub-scores (CR / D/E / DSR) | Blend | Reads |
|---|---|---|---|
| Debt/EBITDA at 3.0×, others perfect | 100 / 70 / 100 | 86 | Pass |
| Debt/EBITDA 3.01×, others perfect | 100 / 0 / 100 | 55 | May not pass |
| Debt/EBITDA 3.01× rescued (40–60 pts), others perfect | 100 / 40–60 / 100 | 73–82, capped at 74 | Pass, ratio in breach |
| Debt/EBITDA 4.01× (severe), others perfect | 100 / 15 / 100 | 62 | May not pass |
| Negative EBITDA, others perfect | 100 / 0 / 100 | 55 | May not pass |
| Negative EBITDA, Debt Servicing excluded | 100 / 0 / – | 36 | May not pass |
| Debt/EBITDA perfect, Debt Servicing just past 30% (no rescue), Current Ratio perfect | 100 / 100 / 0 | 70 | Pass, ratio in breach |
| Debt/EBITDA perfect, Current Ratio just under 1.0, Debt Servicing perfect | 0 / 100 / 100 | 75 → 74 | Pass, ratio in breach |
| Current Ratio just under 1.0, Debt/EBITDA good (85) | 0 / 85 / 100 | 68 | May not pass |
| Debt/EBITDA perfect, Debt Servicing severe 45%, Current Ratio perfect | 100 / 100 / 14 | 74 | Pass, ratio in breach |

**Pass, ratio in breach at the threshold.** A Current Ratio breach, or a Servicing breach, beside two
perfect ratios passes (75 / 70); beside a merely "good" Debt/EBITDA it does not. Debt/EBITDA, the
heaviest ratio, can never be breached and still pass unless a rescue gives it 40–60 points.

### REIT / Property Developer path

```
Gearing Ratio (%) = Total Debt / Total Assets × 100
```

using the provider's broader `totalDebt` aggregate.

| Gearing | Tier | Points |
|---|---|---|
| < 30% | excellent | 100 |
| 30% – 40% | good | 85 |
| 40% – 45% | approaching_limit | 70 |
| > 45% | fail | 0 (a breach) |

**Gearing under 45% passes (2026-10-08).** The 40–45% band used to score 60, which the shared 70 floor read as a Fail, so a REIT at
42% failed although it was under the stated 45% limit (HST, KIM, O, REG and VMRK were in this band). It now scores 70, the lowest passing
score, and reads Pass; the boundary is unchanged (45.0 exactly is still in the 40–45% tier, anything above is a breach). Under 30%
and 30–40% keep 100 and 85.

Single-ratio score, **no hard fail (2026-10-08)**: the verdict is the Standard rule applied to the score (under 70 `Fail`, over 90
Strong Pass, otherwise Pass). Gearing past 45% scores 0, so it always lands under 70, and every passing tier scores 70 or more, so verdict
and score cannot disagree. A breach is listed in `unrescued_breaches` (`gearing_ratio`) so the card can name it. No rescue mechanism
exists for REIT gearing. Missing Total Debt or Total Assets → `insufficient_data`.

### Bank path

Blends two ratios 50/50, **only once both are available**:

| CET1 | Tier | Points | | NPL | Tier | Points |
|---|---|---|---|---|---|---|
| < 10% | fail | 0 (a breach) | | ≥ 5% | fail | 0 (a breach) |
| 10% – 12% | acceptable | 70 | | 3% – 5% | acceptable | 70 |
| 12% – 14% | good | 85 | | 1% – 3% | good | 85 |
| ≥ 14% | excellent | 100 | | < 1% | excellent | 100 |

NPL = `nonaccrual loans / total loans × 100`, computed from the provider's raw filer-reported tag
dump, never a pre-computed ratio. Falls back to the latest annual filing if the quarterly
nonaccrual-loan tag is specifically absent. Discarded as unreliable if the resulting total-loan
figure is under **10%** of total assets. Manually overridable.

**No hard fail (2026-10-08).** The verdict is the Standard rule applied to the score (under 70 `Fail`, over 90 Strong Pass, otherwise
Pass); a breached ratio scores 0 and is listed in `unrescued_breaches`. Weights alone keep verdict and score in agreement, with no cap:
with a CET1 weight w and an NPL weight 1 − w, a breach beside a perfect other ratio scores at most 100 × (1 − w) (CET1 breached) or
100 × w (NPL breached), and two ratios exactly at their limits score 70, so the blend is under 70 for a breach and 70 or more
otherwise for every w **strictly between 0.30 and 0.70**. The weights are the code constant `WEIGHTS_BANK` (50/50, not in Settings);
**if they are ever made adjustable they must stay within 0.31–0.69** (at 0.30 a CET1 breach beside a perfect NPL scores exactly 70
and passes; at 0.70 the same holds for NPL). `test_step5.py` checks the full CET1 × NPL grid, the gearing range and that band. A Bank
with no CET1 entered, or no resolvable NPL, is still `not_supported` (no score). No rescue mechanism for either Bank ratio.

**CET1 is manual-entry only, never fabricated or estimated.** Investigated against the provider:
no CET1 field and no raw components to compute one exist (ratios, ratios-ttm, key-metrics, the
balance sheet and speculative bank-specific endpoints all came back absent or 404). Values are
entered through `frontend/components/step5/BankCapitalMetricsForm.tsx` and stored via
`helpers/bank_capital_metrics.py`. A Bank ticker reads `verdict: "not_supported"` / `score: null`
only until a CET1 value is entered; once it is, `score_step5_bank` blends it 50/50
(`WEIGHTS_BANK`) with NPL into a real score and verdict (manual entry shipped 2026-08-02; before
that a Bank ticker was permanently `not_supported`). NPL itself is auto-computed from the
provider's XBRL tag dump via `helpers/npl.py` where available and manually overridable otherwise;
the original methodology never specified an NPL metric at all.

**IBKR and HOOD were permanently excluded** from the CET1/NPL path historically
(`BANK_CET1_NPL_EXCLUDED_TICKERS`); as of the 2026-09-05 company-classification fix both are
`"Standard"` everywhere (they never had a genuine deposit-liability tag), so neither reaches
this branch any more — see [Company type variations](company-type-variations.md). The constant
(`data/step5_data.py`) is now an empty set, kept as a mechanism (not deleted) since its own regression test exercises the
behavior generically.

### Insurance path

Always `not_supported`, with no ratios computed or attempted at all — not even a partial signal
the way Bank has NPL as a fallback. Debt is therefore not applied to Insurance: Overall excludes the step and renormalizes the other three
([Overview](overview.md), "What happens if a check can't be completed"); unchanged by the 2026-10-08 company-type rules.

---

## Calibration notes

- **Hard-fail removal and the 25/45/30 weights (2026-10-07)**: simulated on 494 scored Standard/Utility
  tickers before building (decision record: docs/decisions.md 2026-10-07). With the three weight sets
  compared (45/30/25 chosen), 7 tickers moved Fail → Pass (all with one Current Ratio or Servicing
  breach beside two excellent ratios), none Pass → Fail, 18 tickers still pass with Debt/EBITDA above 3×
  (all existing rescues). At 33/33/34 simply deleting the hard fail would have let five severe
  Debt/EBITDA breaches pass (4.1–5.5×), which is why the weights and bounds changed with it.

Validation facts behind the current numbers; the full investigation narratives are in
`docs/archive/claude-md-history-scoring.md`.

- **Breach-context framework (2026-08-01)**: a full-universe recompute (503 tickers) changed 42
  tickers' Debt score/verdict. Deferred-revenue-heavy business models (ROL, DAL) newly qualify;
  APD and AMGN lose their old ICR-only rescue (Debt/EBITDA genuinely up +103% / +17% over five
  years with weak FCF coverage of 6% / 15% of total debt). MA and FICO, the framework's original
  motivating cases, both stay unchanged: MA's Current Ratio breach reaches the framework but 3 of
  4 secondary signals are unfavorable (no deferred revenue, a ~24% five-year decline, cash
  covering 34% of current liabilities), and FICO's Debt/EBITDA (4.81×) is Severe so it never
  reaches the framework — confirming it doesn't extend into Severe territory.
- **Residual fallback floor**: the same recompute showed AVB/EQR/HST/KIM/O/REG (REIT gearing) and
  GEHC/HON/IFF (Standard-path fallback) flipping Pass → Fail at an unchanged score.
- **Negative EBITDA / negative-CFO DSR (2026-08-06)**: previously-blanked Overall Assessments now
  read genuine Fails (e.g. CNC, COIN, F, IP, KHC, PSKY, TAP); CTVA and SMCI (positive EBITDA,
  negative CFO) now compute with DSR excluded — CTVA 85/Pass, SMCI 50/Fail (a genuine Debt/EBITDA
  breach that, with DSR unverifiable, can no longer be breach-context-rescued).
- **Severe-zone graduation (2026-08-13)**: 86 tickers' points/score changed, 0 verdicts changed
  (PCAR's blend rose to 72 yet still read Fail then, since `hard_fail` was checked first and
  unconditionally). Universe scan: Debt/EBITDA's Severe population spans 4.04× to 84.56×, DSR's
  42.68% to 478.91% (HUM). HUM's DSR is genuine, not a data artifact (a seasonally-lumpy $147M
  TTM CFO against a normal ~$704M interest expense). FDXF's Current Ratio of 0.00 is a
  provider data gap (`totalCurrentAssets` reported as a literal 0 against $993M of current
  liabilities for the recently-spun-off subsidiary); Current Ratio's Severe zone is deliberately
  not graduated.
