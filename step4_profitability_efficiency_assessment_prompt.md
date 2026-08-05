# Step 4: Profitable and Operationally Efficient

**Ticker: {{TICKER}}**

You are assessing whether {{TICKER}} is not just growing, but growing **profitably and efficiently**. A company can show strong revenue growth and still be a poor business if it generates weak returns on the capital it deploys, or if its earnings quality is deteriorating. This step checks four things together:

1. Return on Equity (ROE) — consistently ≥ 12–15% over 5 years
2. Return on Invested Capital (ROIC) — consistently ≥ 12–15% over 5 years (skip for Banks, Insurance, Utility/Regulated companies — ROE only)
3. Revenue growing at the same or faster rate than Accounts Receivable
4. Cash Conversion Cycle (CCC) consistent or declining over 5 years (applies only to companies with physical inventory)

**Pass criterion:** All four sub-metrics should pass (or be validly exempted). A single red flag on Receivables or CCC should be investigated before proceeding; ROE or ROIC persistently below threshold is a fail.

---

## Metric 1 — Return on Equity (ROE)

`ROE (%) = (Net Profit After Tax / Total Shareholders' Equity) × 100`

ROE shows how much profit the company generates from shareholders' stake in the business. High ROE = management effectively turning equity into profit; low ROE = capital poorly deployed.

Pull ROE for each of the last 5 fiscal years plus TTM:

| Year | Net Profit After Tax | Shareholders' Equity | ROE % |
|---|---|---|---|
| FY-4 … FY-1 | | | |
| FY0 | | | |
| TTM | | | |

| ROE Level | Assessment |
|---|---|
| > 15% | ✅ Excellent — highly profitable business |
| 12–15% | ✅ Good — solidly profitable |
| 8–12% | ⚠️ Below threshold — marginal |
| < 8% | ❌ Fail — poor use of equity capital |

**Important exception — negative shareholders' equity:** Some companies (e.g., those with aggressive share buyback programs) show negative shareholders' equity due to high treasury stock. This can make ROE appear negative on financial data sites, which is misleading. Profit generated from negative equity is effectively an extremely high (mathematically undefined/"infinite") ROE — this is actually a **positive** sign, not a fail. Do not penalize {{TICKER}} for this; instead, check consistent profitability directly in the income statement (positive and growing Net Profit After Tax) as the substitute signal.

## Metric 2 — Return on Invested Capital (ROIC)

`ROIC (%) = [EBIT × (1 − Tax Rate)] / (Total Shareholders' Equity + Total Debt − Cash & Equivalents) × 100`

ROIC shows how efficiently the company generates profit from **all** capital deployed — equity and debt combined. It closes a blind spot in ROE: a company can inflate ROE by loading up on debt to fund buybacks. ROIC penalizes this by including total debt in the denominator.

Pull ROIC for each of the last 5 fiscal years plus TTM:

| Year | EBIT × (1−Tax Rate) | Equity + Debt − Cash | ROIC % |
|---|---|---|---|
| FY-4 … FY-1 | | | |
| FY0 | | | |
| TTM | | | |

| ROIC Level | Assessment |
|---|---|
| > 15% | ✅ Excellent — exceptional capital efficiency |
| 12–15% | ✅ Good — strong capital deployment |
| 8–12% | ⚠️ Below threshold — marginal efficiency |
| < 8% | ❌ Fail — poor use of total invested capital |

**Exception — when ROIC does not apply:** ROIC does NOT apply to Banks, Insurance Companies, or Utility/Regulated Infrastructure companies. These industries carry structurally high debt/leverage by the nature of their business model, not mismanagement — applying ROIC would produce artificially depressed, non-comparable figures. If {{TICKER}} falls into one of these categories, state so explicitly and assess ROE only for this metric.

## Metric 3 — Revenue vs. Accounts Receivable

Accounts Receivable = sales made but cash not yet collected. **Rule: Revenue must grow at the same or faster rate than Accounts Receivable.** If Receivables grow faster than Revenue, this is a major red flag — it can mean weak collections, customers in financial difficulty, or even fictitious revenue (accounting fraud); cash quality of earnings is deteriorating.

### Step 3a — Calculate YoY Growth % for Both

`YoY Growth % = ((Current Year − Previous Year) / Previous Year) × 100`

Apply to both Revenue and AR for every year transition (last 5 years plus TTM):

| Year | Revenue | Revenue YoY % | AR | AR YoY % |
|---|---|---|---|---|
| FY-4 | | — | | — |
| FY-3 | | | | |
| FY-2 | | | | |
| FY-1 | | | | |
| FY0 | | | | |
| TTM | | | | |

### Step 3b — Compare Growth Rates Side by Side

| Outcome | Flag |
|---|---|
| Revenue Growth % ≥ AR Growth % | ✅ Healthy |
| AR Growth % slightly higher (within ~5–10%) | ⚠️ Monitor |
| AR Growth % significantly higher than Revenue | 🚩 Red Flag |
| Revenue declining but AR still growing | 🚩 Strong Red Flag |

### Step 3c — Count the Pattern and Assess Magnitude

Tally: ✅ years Revenue ≥ AR growth: **___ of ___** | 🚩 years AR outpaced Revenue: **___ of ___**

| Score | Assessment |
|---|---|
| AR outpacing in 1–2 isolated years | ⚠️ Acceptable if explainable |
| AR outpacing in 3+ years | ⚠️ Concerning pattern |
| AR outpacing in majority of years | 🚩 May Not Pass |
| AR outpacing consistently in recent years | 🚩 Fail — escalating risk |

For any flagged year, compute the gap (`AR YoY % − Revenue YoY %`) and classify: Small (~5–15% faster) ⚠️ / Medium (~15–50% faster) 🚩 / Large (>50% faster) 🚩🚩.

### Step 3d — Absolute AR-to-Revenue Ratio

`AR as % of Revenue = (AR / Revenue) × 100` — check the trend: stable/shrinking ✅, gradually rising ⚠️, spiking 🚩.

### Step 3e — Context Before Concluding

| Situation | What it could mean |
|---|---|
| AR outpacing during an explosive growth phase | May be temporary — fast-growing companies sometimes extend credit to win customers |
| AR outpacing in a downturn year | More serious — revenue shrinking but obligations still outstanding |
| AR declining in a good revenue year | ✅ Very positive — company collecting faster than it's growing |
| Persistent AR outpacing over 3+ years | Could signal weak collections or customers in financial distress |
| Industry context | B2B companies naturally carry higher AR than B2C — compare {{TICKER}} against peers where possible |

## Metric 4 — Cash Conversion Cycle (CCC)

`CCC = Days Inventory Outstanding (DIO) + Days Sales Outstanding (DSO) − Days Payable Outstanding (DPO)`

Applies only to companies with physical inventory (e.g., retail, manufacturing). Lower/declining CCC = cash comes back faster = more operationally efficient. If {{TICKER}} has no physical inventory (e.g., pure software/services), state this explicitly and skip this metric — do not count it against the overall Step 4 verdict.

### Step 4a — Plot the Trend (YoY + TTM)

| Period | DIO | DSO | DPO | CCC (days) | YoY Δ |
|---|---|---|---|---|---|
| FY-4 | | | | | — |
| FY-3 | | | | | |
| FY-2 | | | | | |
| FY-1 | | | | | |
| FY0 | | | | | |
| TTM | | | | | |

### Step 4b — Ask the Key Questions

1. Is CCC declining over time (FY-4 → TTM)?
2. Is CCC consistent within a narrow range?
3. Is there a clear downward trend (not just noise)?
4. Is the latest TTM improving vs. the most recent full fiscal year?
5. Is there any year with a spike? If yes — which component drove it (DIO/DSO/DPO), and **why**: industry-wide supply chain issue, deliberate inventory build-up ahead of demand, change in payment terms, one-off M&A distortion, or receivables collection issue? State whether it reads as a temporary blip or a structural concern.

### Step 4c — Classification

| Pattern | Verdict |
|---|---|
| Consistent & declining | ✅ Strong Pass |
| Consistent within narrow band | ✅ Pass |
| Volatile but trending down | ⚠️ Pass with caution |
| Volatile with no clear trend | ⚠️ May Not Pass |
| Sustained upward trend | ❌ Fail |

---

## Where to Source These Metrics

| Metric | Suggested Source |
|---|---|
| ROE (5-year trend) | Morningstar, SEC EDGAR XBRL, or equivalent financial data platform — Operating Performance / Profitability section |
| ROIC (5-year trend) | Same as above |
| Revenue vs. Receivables | Plot both on the same chart panel (e.g., TradingView or equivalent charting tool) over 5 years |
| Cash Conversion Cycle | Financial indicators section of a charting/data platform, plotted annually over 5 years |

---

## Overall Assessment Framework

Answer the 4 governing questions explicitly:

1. **ROE** — Consistently ≥ 12–15% over the last 5 years? → Yes, consistent & above threshold ✅ / Borderline or declining ⚠️ / Below threshold or erratic ❌ Fail
2. **ROIC** — Consistently ≥ 12–15% over the last 5 years? (Skip if Bank/Insurance/Utility — assess ROE only) → Yes ✅ / Borderline or declining ⚠️ / Below threshold or erratic ❌ Fail
3. **REVENUE vs RECEIVABLES** — Is Revenue growing equal to or faster than AR? → Yes ✅ / Receivables slightly faster ⚠️ / Receivables significantly faster 🚩 Red Flag
4. **CCC** — Is CCC consistent or declining? (Skip if no physical inventory) → Yes, flat or declining ✅ / Gradually rising ⚠️ / Spiking or erratic 🚩 Red Flag

| Result | Verdict |
|---|---|
| All 4 Green | ✅ Strong Pass — highly profitable & efficient |
| 3 Green, 1 Yellow | ⚠️ Pass — monitor the weak metric closely |
| Any single Red Flag on Receivables or CCC | 🚩 Investigate before proceeding |
| ROE or ROIC below threshold consistently | ❌ Fail — eliminate from watchlist |

## Output Format

Conclude with a structured summary block:

```
STEP 4 ASSESSMENT — {{TICKER}}
ROE (5yr + TTM): [trend, avg %] — [✅/⚠️/❌] — [note negative-equity exception if applicable]
ROIC (5yr + TTM): [trend, avg % or N/A — Bank/Insurance/Utility] — [✅/⚠️/❌]
Revenue vs AR: [X of Y years Revenue ≥ AR growth; largest gap and magnitude tier] — [✅/⚠️/🚩]
CCC (5yr + TTM): [X days → Y days; pattern] — [✅/⚠️/🚩/❌ or N/A — no physical inventory]
Verdict: [✅ Strong Pass / ⚠️ Pass — monitor / 🚩 Investigate before proceeding / ❌ Fail]
Rationale: [2-3 sentences tying the verdict to the specific metrics, any exemptions applied, and any spikes/context that changed the read]
```

---

**Notes for use:**
- Source all figures from the same filing basis (10-K/10-Q or SEC EDGAR XBRL) to avoid definitional mismatches across periods and metrics.
- Apply industry exemptions carefully and state them explicitly: ROIC exemption (Banks/Insurance/Utilities), CCC exemption (no physical inventory).
- If fewer than 5 years of data are available, note the shortened window explicitly.
- This prompt should be run identically for any ticker supplied; only the data pulled changes.
