# Step 1: Consistently Increasing Sales, Net Income & Cash Flow from Operations

**Ticker: {{TICKER}}**

You are assessing whether {{TICKER}}'s Sales Revenue, Net Income, and Cash Flow from Operations (CFO) are **all three** increasing and consistent over the last 5–10 years, including the latest TTM (trailing twelve months). This is the first and most powerful filter in the overall fundamental evaluation — the goal is predictability, not a single good year.

**Pass criterion:** Revenue, Net Income, AND Operating Cash Flow must **all** be BOTH increasing AND consistent. All three must pass — one or two is not enough.

---

## Step 1 — Check Each of the Three Metrics Separately

Pull annual figures for Revenue, Net Income, and CFO for the last 5–10 fiscal years, **plus the latest TTM**, and plot year by year:

| Year | Revenue | Net Income | CFO | Gross Margin % | Net Margin % |
|---|---|---|---|---|---|
| FY-9 … FY-1 | | | | | |
| FY0 (latest annual) | | | | | |
| TTM | | | | | |

For each of the three metrics, answer:

1. Is the overall direction **UP** over the 5–10 year window (through TTM)?
2. Is the growth **CONSISTENT** — no major unexplained breaks?
3. Are Gross Profit Margin and Net Profit Margin stable or improving alongside?
4. **Is the TTM figure itself consistent with the trend** — i.e., does including TTM confirm the trajectory, or does it introduce a new dip/spike that changes the read?

## Step 2 — Assess Consistency Using This Scale

Apply to each metric (Revenue, Net Income, CFO) individually, incorporating the TTM data point as part of the run of years, not as a separate afterthought:

| Pattern Observed | Flag |
|---|---|
| Grows steadily every single year (through TTM) | ✅ Strong Pass |
| Mostly growing with 1 small dip, then recovers | ✅ Acceptable |
| 1 significant dip but clear recovery after | ⚠️ Pass with note |
| Multiple dip years with uneven recovery | 🚩 Inconsistent |
| Flat for several years then sudden spike | 🚩 Not consistent growth |
| Declining trend in recent years (including TTM) | ❌ Fail |

## Step 3 — Handle One-Off Items Correctly

Before judging consistency, **strip out exceptional items and one-off gains/losses** from Net Income and CFO where disclosed (check MD&A / notes for the annual periods and for the trailing quarters that make up TTM):

- Asset sale proceeds
- Insurance payouts
- One-time write-offs or impairments
- Tax windfalls or penalties
- Non-recurring litigation settlements

State explicitly whether any adjustment was needed for TTM specifically, since TTM aggregates the most recent 4 quarters and can carry a one-off from a single quarter that wouldn't be obvious at the annual level. The goal is to see underlying business performance, not accounting noise.

## Step 4 — Check Profit Margins Alongside the Numbers

Compute for every period including TTM:

`Gross Profit Margin = Gross Profit / Revenue × 100`
`Net Profit Margin = Net Income / Revenue × 100`

| Margin Trend | Meaning |
|---|---|
| Stable or expanding over time (TTM included) | ✅ Business getting more efficient |
| Gradually compressing slightly | ⚠️ Monitor — may be competitive pressure |
| Sharply declining margins despite revenue growth | 🚩 Growing unprofitably — red flag |
| Wildly inconsistent margins year to year | 🚩 Unstable business model |

Flag if TTM margins diverge meaningfully from the most recent full fiscal year — this can be an early signal before it shows up in annual filings.

## Step 5 — Apply the Special Exceptions

The Cash Flow from Operations criterion does **NOT** apply to:

- ❌ Banks
- ❌ Property Developers
- ❌ Commodity Companies

These industries have fundamentally different cash flow structures — applying the same standard would give a misleading picture. If {{TICKER}} falls into one of these categories, state so explicitly and focus the assessment on Revenue and Net Income consistency only (including TTM), noting CFO as not applicable rather than a fail.

## Step 6 — Tally All Three Metrics Together

| Revenue | Net Income | Operating Cash Flow | Overall Step 1 |
|---|---|---|---|
| ✅ | ✅ | ✅ | ✅ Strong Pass |
| ✅ | ✅ | ⚠️ | ⚠️ Pass with caution |
| ✅ | ⚠️ | ✅ | ⚠️ Check Operating Income as backup |
| ✅ | 🚩 | ✅ | 🚩 May Not Pass |
| Any two or more 🚩 | — | — | ❌ Fail — do not proceed |

If Net Income is inconsistent, check Operating Income as a secondary indicator — it strips out interest and tax distortions and gives a cleaner view of core business profitability. Apply the same TTM-inclusive logic to this backup check.

---

## Overall Assessment Framework

Answer the 5 governing questions explicitly, each incorporating the TTM data point:

1. **DIRECTION** — Is the overall 5–10 year trend upward, through TTM? → Yes, clearly ✅ / Flat or down 🚩
2. **CONSISTENCY** — Are there major unexplained breaks, including any introduced by TTM? → 1 small dip only ✅ / Multiple dips 🚩
3. **MARGINS** — Are Gross and Net margins holding up through TTM? → Stable/expanding ✅ / Declining 🚩
4. **QUALITY** — Stripped of one-offs (including within TTM), is growth still there? → Yes ✅ / No 🚩
5. **COMPLETENESS** — Do all 3 metrics pass (or 2 of 3 where CFO is exempt)? → All pass ✅ Proceed to Step 2 / 1+ fail 🚩 Stop and reconsider

| Result | Verdict |
|---|---|
| All 5 Green | ✅ Strong Pass — high earnings predictability |
| 4 Green, 1 Yellow | ⚠️ Pass with monitoring |
| 2+ Red flags | 🚩 May Not Pass |
| Majority Red | ❌ Fail — eliminate from watchlist |

## Output Format

Conclude with a structured summary block:

```
STEP 1 ASSESSMENT — {{TICKER}}
Window assessed: [FY-9 → TTM] ([N] years + TTM)
Revenue: [✅/⚠️/🚩/❌] — [direction, consistency note, TTM read]
Net Income: [✅/⚠️/🚩/❌] — [direction, consistency note, one-offs stripped, TTM read]
Operating Cash Flow: [✅/⚠️/🚩/❌ or N/A — bank/developer/commodity] — [direction, consistency note, TTM read]
Gross Margin trend: [Stable/Expanding/Compressing/Volatile]
Net Margin trend: [Stable/Expanding/Compressing/Volatile]
One-off adjustments made: [None / list items and periods, including any within TTM]
Direction: [✅/🚩]  Consistency: [✅/🚩]  Margins: [✅/🚩]  Quality: [✅/🚩]  Completeness: [✅/🚩]
Verdict: [✅ Strong Pass / ⚠️ Pass with monitoring / 🚩 May Not Pass / ❌ Fail]
Rationale: [2-3 sentences tying the verdict to the trend, TTM confirmation/divergence, and any one-off explanations]
```

---

**Notes for use:**
- Source Revenue, Net Income, and CFO from the same filing basis (10-K/10-Q or SEC EDGAR XBRL) to avoid definitional mismatches across periods.
- TTM = sum of the most recent 4 reported quarters; recompute margins on the TTM figures directly rather than averaging annual margins.
- If fewer than 5 years of history are available, note the shortened window explicitly — the assessment is weaker with less data.
- This prompt should be run identically for any ticker supplied; only the data pulled changes.
