# Debt

Technical reference for the Debt check (the "Debt" card on the Analysis
tab). A bankruptcy-risk filter, not a plain continuous score — a genuine
breach of a hard limit fails the whole check regardless of how the other
ratios blend.

## Company-type routing

- **Bank** → CET1 + NPL path (below).
- **Insurance** → always `not_supported`, no ratios attempted at all.
- **REIT/Property Developer** → Gearing Ratio path.
- **Utility, Commodity, and every other type** → Standard path (the same
  3-ratio path as an ordinary operating company; Utility is **not**
  exempted here, unlike its exemptions in Profitability).

## Standard path: the three ratios

All figures are the latest reported quarter (balance sheet) or trailing
twelve months (flow figures — EBITDA, interest expense, CFO), never
fiscal-year-end.

```
Current Ratio            = Current Assets / Current Liabilities
Adjusted Current Ratio    = Current Assets / (Current Liabilities − Deferred Revenue)
Debt / EBITDA             = (Short-Term Debt + Long-Term Debt) / EBITDA (TTM)
Debt Servicing Ratio (%)  = Net Interest Expense (TTM) / CFO (TTM) × 100
Interest Coverage Ratio   = EBIT (TTM) / Interest Expense (TTM, gross, not netted)
```

`Net Interest Expense (TTM)` is `max(0, −Net Interest Income TTM)` — a
company earning net interest income has no interest burden for this
ratio, floored at 0 rather than left negative. The Adjusted Current Ratio
falls back to the raw ratio if subtracting deferred revenue would leave a
non-positive denominator.

### Severity bands

Each ratio has three zones. The **Comfortable** boundary is the same
threshold the check has always used; **Borderline** and **Severe** are
gradations beyond it — a Borderline breach gets a second look (below)
before failing; a Severe breach never does.

| Ratio | Comfortable | Borderline | Severe |
|---|---|---|---|
| Current Ratio | ≥ 1.0 | 0.7 – 1.0 | < 0.7 |
| Debt / EBITDA | ≤ 3.0 | 3.0 – 4.0 | > 4.0 |
| Debt Servicing Ratio | < 30% | 30% – 40% | ≥ 40% |

### Comfortable-zone sub-tiers

| Current Ratio | Tier | Points |
|---|---|---|
| > 2.0 | excellent | 100 |
| 1.5 – 2.0 | good | 85 |
| 1.0 – 1.5 | acceptable | 70 |

| Debt / EBITDA | Tier | Points |
|---|---|---|
| ≤ 1.0 | excellent | 100 |
| 1.0 – 2.0 | good | 85 |
| 2.0 – 3.0 | acceptable | 70 |

| Debt Servicing Ratio | Tier | Points |
|---|---|---|
| < 10% | excellent | 100 |
| 10% – 20% | good | 85 |
| 20% – 30% | approaching_limit | 60 |

### Current Ratio's deferred-revenue rescue

If the **raw** Current Ratio is already ≥ 1.0, it's scored off the raw
value directly (deferred revenue has nothing to rescue). If the raw ratio
is below 1.0 but the **adjusted** ratio (deferred revenue subtracted out
of current liabilities) reaches ≥ 1.0, it's rescued: scored off the
adjusted ratio's own Comfortable-zone tier, flagged
`saved_by_tiebreaker`. If the adjusted ratio is still below 1.0 but at
least 0.7, it's `borderline_fail` (0 points, eligible for the
breach-context second look below). Below 0.7, it's `severe` (0 points,
no second look).

### Debt/EBITDA and Debt Servicing Ratio's Borderline zone

- **Debt/EBITDA** Borderline (3.0–4.0×) always starts as a hard-fail
  breach, then gets the richer breach-context evaluation below.
- **Debt Servicing Ratio** Borderline (30–40%) uses a narrower, separate
  rescue: if the Interest Coverage Ratio is "safe" (**> 3.0×**), the
  breach is excused to `borderline_saved_by_icr`, flat **60 points**,
  `saved_by_tiebreaker`. If ICR isn't safe, it stays a plain hard fail.
  This is the *only* rescue mechanism available to Debt Servicing Ratio —
  it is never a subject of the breach-context framework below, only one
  of its **inputs** (as a primary gate for the other two ratios).

Interest Coverage Ratio itself carries no weight of its own — it never
counts as a fourth ratio in the blend below.

| ICR | Classification |
|---|---|
| > 3.0× | safe |
| 1.0× – 3.0× | tight |
| < 1.0× | dangerous |
| unavailable | not_applicable |

### When Debt/EBITDA or Debt Servicing Ratio is undefined

- **EBITDA (TTM) ≤ 0** — Debt/EBITDA is not scored as a ratio at all; the
  result is `negative_ebitda`, 0 points, hard-fail, with an explanatory
  note attached, and it stays IN the blend below as a genuine Fail — a
  company not generating positive operating earnings at all is a real
  weakness, not a neutral "can't measure this." This never enters the
  Borderline breach-context framework (it isn't a Borderline breach, it's
  an unconditional Fail), and it also fails Current Ratio's own
  breach-context primary gate (Debt/EBITDA is one of its two gates) — an
  undefined Debt/EBITDA can't vouch for a different ratio's rescue any
  more than a bad one could.
- **CFO (TTM) ≤ 0 or unavailable** — Debt Servicing Ratio's denominator
  is non-positive, so it can't be meaningfully calculated either. Unlike
  negative EBITDA, this is treated as a genuine, neutral exclusion
  (`excluded_negative_cfo`, with an explanatory note attached) rather
  than a Fail — a temporary/seasonal CFO swing isn't evidence Debt
  Servicing Ratio itself is unhealthy. It drops out of the blend
  entirely; see "Blend and verdict" below for how its weight is
  redistributed. It also fails both breach-context frameworks' primary
  gates the same way an undefined Debt/EBITDA does above (Debt Servicing
  Ratio is a gate input for both Debt/EBITDA's and Current Ratio's
  frameworks).

Total Debt or EBITDA (TTM) being genuinely missing (not merely
non-positive) still gates the whole Standard path to `insufficient_data`
before any ratio is scored — only a *present-but-non-positive* EBITDA
reaches the negative-EBITDA Fail path above. Current Ratio and
Debt/EBITDA are never subject to the exclusion treatment Debt Servicing
Ratio gets — a real Fail on either always counts fully toward the blend.

## Breach-context framework (Debt/EBITDA and Current Ratio, Borderline only)

A **Borderline** breach on Debt/EBITDA, or a Current Ratio still
Borderline **after** the deferred-revenue rescue above has already been
tried and failed to reach Comfortable, gets a second, richer look before
falling back to a flat Fail. **Severe** breaches never reach this
framework — no exceptions.

### Primary gates (must both pass cleanly, using literal raw values — not the other ratio's own possibly-rescued classification)

| Breach being evaluated | Gate 1 | Gate 2 |
|---|---|---|
| Debt/EBITDA | Current Ratio (raw) ≥ 1.0 | Debt Servicing Ratio < 30% |
| Current Ratio | Debt/EBITDA ≤ 3.0 | Debt Servicing Ratio < 30% |

If either gate fails, the breach-context framework doesn't apply and the
ratio stays a plain hard fail.

### Secondary signals

Each signal is `favorable`, `unfavorable`, or `not_computable` (missing
data). Two signals per ratio are always informational-only (shown to the
user, never counted toward the vote below), since neither is reliably
determinable from the data source.

**Debt/EBITDA's secondary signals:**

| Signal | Favorable when |
|---|---|
| 5yr trend | Debt/EBITDA has declined by more than 10% (relative) from 5 years ago to now |
| FCF vs. Total Debt | TTM FCF is positive **and** ≥ 15% of total debt |
| Interest Coverage | ICR classifies "safe" (> 3.0×) |
| Cause of debt *(informational only)* | never scored — always prompts a manual check (e.g. recent-acquisition debt) |
| Net Debt vs. Gross Debt *(informational only)* | never scored — shown as context only |

**Current Ratio's secondary signals:**

| Signal | Favorable when |
|---|---|
| Deferred revenue | Deferred revenue is ≥ 15% of current liabilities |
| 5yr trend | The (adjusted) Current Ratio has **not** materially declined (a >10% relative drop from 5 years ago disqualifies; stable or rising is favorable) |
| Cash position | Cash & equivalents ≥ 50% of current liabilities |
| Asset quality | Liquid current assets (cash + receivables) ≥ 50% of total current assets |
| Undrawn revolving credit *(informational only)* | never scored — always prompts a manual 10-K/10-Q check |

A signal reads `not_computable` (excluded from the vote, not counted as
unfavorable) when its 5-year history is too short, or its underlying
figures are missing.

### Qualification and grading

Among the signals that count toward the gate and are actually computable,
a **strict majority** (more than half) must be `favorable` for the breach
to qualify for downgrade. If it qualifies:

```
score = round(40 + (60 − 40) × favorable_fraction)
```

— ranging from just above 40 (a bare majority) up to 60 (every countable
signal favorable). The result is relabeled `marginal_via_breach_context`,
flagged `saved_by_tiebreaker` — the same "Pass with caution" state the
deferred-revenue and ICR rescues use, not a new verdict.

If it doesn't qualify (either gate fails, no strict majority, or no
signals were computable at all), the ratio stays at its plain Borderline
hard-fail result (0 points).

## Blend and verdict (Standard path)

```
applicable = {current_ratio, debt_to_ebitda, debt_servicing_ratio} minus
             whichever of them is excluded this period (only
             debt_servicing_ratio can be excluded -- see above)
weight[r]  = (1/3) / sum(1/3 for r in applicable)
score      = round(sum(points[r] * weight[r] for r in applicable))
```

An equal 1/3 split when all three ratios are computable — unchanged from
before this exclusion mechanism existed. When Debt Servicing Ratio is
excluded (CFO ≤ 0, EBITDA still positive), Current Ratio and Debt/EBITDA
each take 50% instead, mirroring Profitability's own equal-weight
redistribution for its exempt metrics. Current Ratio and Debt/EBITDA
themselves are never excluded from the blend this way — a negative-EBITDA
Fail still counts fully as a 0-point result rather than being dropped out.

```
hard_fail          = any of the 3 ratios' own hard-fail flag is true
                      (negative-EBITDA's Fail counts here too)
saved_by_tiebreaker = any of the 3 ratios was rescued (deferred revenue,
                       ICR-on-DSR, or either breach-context downgrade)
```

If `saved_by_tiebreaker` is true and `hard_fail` is false, the blended
score is capped at **74** — without this, a rescued ratio could still
blend to a high score (95–100) if the other two ratios are excellent,
which would read as contradictory next to a "caution" label. The cap
lands the score in the same lowest Pass shade the shared score badge
already uses for a plain, unrescued 70–74 score.

**Verdict**, in this order:

1. `hard_fail` → **Fail**, regardless of score.
2. `score < 70` → **Fail** — this residual floor catches both a rescued
   breach whose capped blend still lands under 70, and a plain
   mediocre-but-non-breaching combination with no rescue involved at all
   (e.g. a low-but-not-breaching Debt Servicing Ratio dragging the
   average down).
3. `saved_by_tiebreaker` → **Pass with caution** — checked before Strong
   Pass, since a rescued breach can never read as a Strong Pass regardless
   of score.
4. `score > 90` → **Strong Pass**.
5. Otherwise → **Pass**.

Missing Current Ratio outright, or missing Total Debt/EBITDA data outright
(not merely EBITDA being present but non-positive — see above) →
`score: null, verdict: "insufficient_data"`. Debt Servicing Ratio's inputs
being missing or non-positive never triggers this — it's excluded from
the blend instead (see above).

## REIT / Property Developer path

```
Gearing Ratio (%) = Total Debt / Total Assets × 100
```

using the data provider's broader `totalDebt` aggregate — a different,
wider figure than the Standard path's short-term + long-term debt sum.

| Gearing | Tier | Points |
|---|---|---|
| < 30% | excellent | 100 |
| 30% – 40% | good | 85 |
| 40% – 45% | approaching_limit | 60 |
| > 45% | fail | 0 (hard fail) |

Single-ratio blend (100% weight). Same verdict logic as the Standard
path's steps 1–2 and 4–5 above (hard-fail → Fail; score < 70 → Fail —
this is what actually fails the 60-point `approaching_limit` tier, since
it has no hard-fail flag of its own; > 90 → Strong Pass; else Pass). No
rescue/tiebreaker mechanism exists for REIT gearing, so step 3 above never
applies here. Missing Total Debt or Total Assets → `insufficient_data`.

## Bank path

Blends two ratios 50/50, **only once both are available**:

- **CET1 (Common Equity Tier 1) Ratio** — manual entry only; the data
  provider has no source for it. Until a value is entered, the whole
  check reads `not_supported`, even if NPL is already available and shown
  standalone.
- **NPL (Non-Performing Loan) Ratio** — `nonaccrual loans / total loans ×
  100`, computed from the data provider's raw filer-reported tag dump
  (never the provider's own pre-computed ratio, since those aren't
  standardized across filers). Sourced from the latest quarter's filing;
  falls back to the latest annual filing if the quarterly nonaccrual-loan
  tag is specifically absent (a real 10-K-only disclosure gap for some
  filers, not a data error — never mixes nonaccrual and total-loan figures
  across periods). Discarded as unreliable (treated as unavailable) if the
  resulting total-loan figure is under **10%** of total assets, a
  plausibility floor against a mis-scoped XBRL tag. Manually overridable.

| CET1 | Tier | Points |
|---|---|---|
| < 10% | fail | 0 (hard fail) |
| 10% – 12% | acceptable | 70 |
| 12% – 14% | good | 85 |
| ≥ 14% | excellent | 100 |

| NPL | Tier | Points |
|---|---|---|
| ≥ 5% | fail | 0 (hard fail) |
| 3% – 5% | acceptable | 70 |
| 1% – 3% | good | 85 |
| < 1% | excellent | 100 |

```
score = round(CET1_points × 0.5 + NPL_points × 0.5)
```

Same verdict bands as the REIT path (hard-fail → Fail; < 70 → Fail; > 90
→ Strong Pass; else Pass). No rescue/tiebreaker mechanism exists for
either Bank ratio.

**IBKR and HOOD are permanently excluded** from the CET1/NPL path — no
manual-entry UI is offered and the check stays `not_supported`
indefinitely, since neither has a customer deposit-taking business (their
data has no `deposits` figure at all), the precondition CET1 as a
regulatory capital-adequacy ratio assumes.

## Insurance path

Always `not_supported`, with **no ratios computed or attempted at all** —
not even a partial signal the way Bank has NPL as a fallback. An
insurer's balance sheet is dominated by loss reserves and unearned
premiums, which don't map onto a real short-term-liquidity or leverage
read the way a typical company's does, and there is currently no
substitute capital-adequacy signal computable from the data source for
insurers.
