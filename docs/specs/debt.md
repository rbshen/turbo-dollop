# Debt

The Debt card is a conservative check on whether a company's debt load is safe — it's built to
behave like a bankruptcy-risk filter rather than a typical continuous score. For most companies
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

## A real breach usually fails the whole card

Unlike Fathom's other checks, Debt isn't a plain weighted average. If any one of these ratios
breaches a clearly unsafe level, the whole card fails, even if the other two ratios look fine —
averaging a genuine debt problem away against healthy ratios elsewhere would defeat the point of
a bankruptcy-risk filter. The numeric score still displays for context, but the verdict itself
reads Fail regardless.

## Borderline breaches get a second look

Not every breach is treated the same. A ratio that's only moderately over its safe threshold
gets a closer, second look before Fathom settles on a Fail — checking things like whether the
company's debt burden has been improving over time, whether free cash flow comfortably covers
total debt, and whether earnings comfortably cover interest payments. If enough of that
supporting evidence looks favorable, the result downgrades from a hard Fail to **Pass with
caution** rather than a clean Pass. A severe breach — well beyond the borderline zone — never
gets this second look and always fails outright.

Separately, for the Current Ratio specifically, some companies collect cash from customers
before delivering the product or service. That cash is booked as a liability ("deferred
revenue") even though it isn't really money the company owes anyone. Fathom checks for this and
can rescue an apparently weak Current Ratio when a low ratio turns out to be explained by this
pattern.

## When a ratio can't be meaningfully calculated

- **Negative earnings (Debt / EBITDA)** — not generating positive operating earnings at all is
  itself a real weakness, so this fails the check outright, the same as a genuine breach.
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
  XBRL-tag check, see `CLAUDE.md`'s "Company classification" section) — for these, Debt isn't
  assessed at all, a permanent, deliberate exemption.
- **Insurance companies** aren't judged on these ratios at all — no reliable substitute
  capital-adequacy signal is currently available for insurers from Fathom's data provider.
  Insurance tickers show as **not supported** for Debt.
- **REITs and Property Developers** are judged on a **Gearing ratio** instead — total debt
  relative to total assets.

## What the verdict means

- **Fail** — a hard breach occurred (or, for Banks/REITs, the relevant ratio is genuinely weak).
- **Pass with caution** — a real breach occurred but was resolved by a legitimate offsetting
  factor. Treat this as "barely passing," not equivalent to a clean Pass.
- **Pass** — no ratio breached its safe threshold.
- **Strong Pass** — every ratio is comfortably within safe territory.
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

### Standard path: the three ratios

All figures are the latest reported quarter (balance sheet) or trailing twelve months (flow
figures), never fiscal-year-end.

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
DSR at 120%; floors chosen from the real tracked-universe distribution, covering 92%/59% of
actual Severe tickers). **Display-only** — `label` stays `"severe"` and `hard_fail` stays
unconditionally `True` for the whole zone. The 15-point ceiling is kept below
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

**Debt/EBITDA and DSR's Borderline zone.** Debt/EBITDA Borderline always starts as a hard-fail
breach, then gets the richer breach-context evaluation below. DSR Borderline uses a narrower,
separate rescue: if ICR is "safe" (**> 3.0×**), the breach is excused to
`borderline_saved_by_icr`, flat **60 points**, `saved_by_tiebreaker`. If ICR isn't safe, it
stays a plain hard fail — the only rescue mechanism available to DSR, never a subject of the
breach-context framework, only one of its **inputs**.

| ICR | Classification |
|---|---|
| > 3.0× | safe |
| 1.0× – 3.0× | tight |
| < 1.0× | dangerous |
| unavailable | not_applicable |

**When Debt/EBITDA or DSR is undefined.** EBITDA ≤ 0 → `negative_ebitda`, 0 points, hard-fail,
stays IN the blend as a genuine Fail (2026-08-06 fix; previously read `insufficient_data`,
silently blanking the entire Overall Assessment) — also fails Current Ratio's own breach-context
primary gate. CFO ≤ 0 or unavailable → `excluded_negative_cfo` (2026-08-06 fix), a genuine
neutral exclusion, drops out of the blend (see below) — also fails both breach-context
frameworks' primary gates.

### Breach-context framework (Debt/EBITDA and Current Ratio, Borderline only)

**Primary gates** (must both pass cleanly, using literal raw values):

| Breach being evaluated | Gate 1 | Gate 2 |
|---|---|---|
| Debt/EBITDA | Current Ratio (raw) ≥ 1.0 | Debt Servicing Ratio < 30% |
| Current Ratio | Debt/EBITDA ≤ 3.0 | Debt Servicing Ratio < 30% |

If either gate fails, the ratio stays a plain hard fail. Using the OTHER ratios' *raw* values as
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

**Qualification and grading.** Among computable signals that count toward the gate, a strict
majority must be favorable:

```
score = round(40 + (60 − 40) × favorable_fraction)
```

Relabeled `marginal_via_breach_context`, flagged `saved_by_tiebreaker`. If it doesn't qualify,
the ratio stays at its plain Borderline hard-fail result (0 points).

### Blend and verdict (Standard path)

```
applicable = {current_ratio, debt_to_ebitda, debt_servicing_ratio} minus
             whichever is excluded this period (only debt_servicing_ratio can be excluded)
weight[r]  = (1/3) / sum(1/3 for r in applicable)
score      = round(sum(points[r] * weight[r] for r in applicable))
```

```
hard_fail          = any of the 3 ratios' own hard-fail flag is true (negative_ebitda counts here too)
saved_by_tiebreaker = any of the 3 was rescued (deferred revenue, ICR-on-DSR, or either breach-context downgrade)
```

If `saved_by_tiebreaker` is true and `hard_fail` is false, the blended score is capped at **74**
(`PASS_WITH_CAUTION_SCORE_CAP`).

**Verdict**, in order:
1. `hard_fail` → Fail.
2. `score < 70` → Fail (residual floor: catches both a rescued breach whose capped blend still
   lands under 70, and a plain mediocre-but-non-breaching combination with no rescue involved).
3. `saved_by_tiebreaker` → Pass with caution.
4. `score > 90` → Strong Pass.
5. Otherwise → Pass.

Missing Current Ratio outright, or missing Total Debt/EBITDA data outright (not merely EBITDA
being non-positive) → `insufficient_data`.

### REIT / Property Developer path

```
Gearing Ratio (%) = Total Debt / Total Assets × 100
```

using the provider's broader `totalDebt` aggregate.

| Gearing | Tier | Points |
|---|---|---|
| < 30% | excellent | 100 |
| 30% – 40% | good | 85 |
| 40% – 45% | approaching_limit | 60 |
| > 45% | fail | 0 (hard fail) |

Single-ratio blend. Same verdict logic as the Standard path's steps 1–2 and 4–5 (this is what
actually fails the 60-point `approaching_limit` tier). No rescue mechanism exists for REIT
gearing. Missing Total Debt or Total Assets → `insufficient_data`.

### Bank path

Blends two ratios 50/50, **only once both are available**:

| CET1 | Tier | Points | | NPL | Tier | Points |
|---|---|---|---|---|---|---|
| < 10% | fail | 0 (hard fail) | | ≥ 5% | fail | 0 (hard fail) |
| 10% – 12% | acceptable | 70 | | 3% – 5% | acceptable | 70 |
| 12% – 14% | good | 85 | | 1% – 3% | good | 85 |
| ≥ 14% | excellent | 100 | | < 1% | excellent | 100 |

NPL = `nonaccrual loans / total loans × 100`, computed from the provider's raw filer-reported tag
dump, never a pre-computed ratio. Falls back to the latest annual filing if the quarterly
nonaccrual-loan tag is specifically absent. Discarded as unreliable if the resulting total-loan
figure is under **10%** of total assets. Manually overridable.

Same verdict bands as the REIT path. No rescue mechanism for either Bank ratio.

**IBKR and HOOD were permanently excluded** from the CET1/NPL path historically
(`BANK_CET1_NPL_EXCLUDED_TICKERS`); as of the 2026-09-05 company-classification fix both are
`"Standard"` everywhere (they never had a genuine deposit-liability tag), so neither reaches
this branch any more — see `CLAUDE.md`'s "Company classification" section. The constant is now
an empty set, kept as a mechanism (not deleted) since its own regression test exercises the
behavior generically.

### Insurance path

Always `not_supported`, with no ratios computed or attempted at all — not even a partial signal
the way Bank has NPL as a fallback.
