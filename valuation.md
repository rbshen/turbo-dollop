# Valuation

Technical reference for the Valuation tab. Calculated entirely separately
from the Overall Assessment blend (Financials / Growth Rate / Profitability
/ Debt / Economic Moat) — no valuation figure is ever folded into that
score, and nothing here is "Step 3" of that framework. This document
defines (1) which valuation method applies to a given company, and (2) the
exact formula each method uses.

Original source: `PP_VMI_Investing_Tools_-_2026_-_v1_1.xlsx`, tabs `VMI IV
Calculator (20 years)`, `VMI IV Calculator (Mean PB)`, `VMI IV Calculator
(PSG)`, `Discount Rate Data`. The formulas below reproduce that workbook's
math; deviations from the original workbook spec, where the live app
behaves differently, are called out explicitly.

---

## 1. Method Selection

Evaluated in order; stops at the first match.

```
1. Company type check
   Bank or REIT/Property Developer?
     → YES: use PRICE_TO_BOOK
     → NO: continue

1a. Insurance check
   Insurance company?
     → YES: skip steps 2/3/3a/3b entirely (the whole cash-flow-based
       method family) — claim timing, reserve movements, and investment
       portfolio fluctuations make Operating Cash Flow too unreliable a
       signal for insurers, the same reasoning behind the Financials
       check's own CFO de-emphasis for this company type. Insurance still
       falls through to step 4 (Net Income) and its own normal fallback
       chain unchanged — it is NOT unconditionally forced to a Net-Income-
       based method regardless of data quality; a distressed insurer with
       genuinely insufficient Net Income history still falls all the way
       through to PASS.
     → NO: continue to step 2 as normal

2. Cash flow quality check
   CFO positive and increasing consistently over the last 5+ years?
   (see "Positive-and-increasing" below for the exact recency-gated rule)
     → NO: go to step 4
     → YES: continue

3. CFO vs Net Income check (both TTM figures)
   CFO > 1.5 × Net Income?
     → NO:  use DCF, current value = CFO (TTM)
     → YES: continue

3a. FCF quality check
   FCF (CFO − CapEx) positive and consistent? (same recency-gated rule)
     → YES: use DFCF, current value = FCF (TTM)
     → NO:  continue

3b. Normalized FCF
   Replace each year's actual CapEx with the trailing 5-year average
   CapEx, recompute FCF, retest positive-and-consistent
     → YES: use DFCF, current value = the normalized series' TTM value
     → NO:  go to step 4

4. Net income check
   Net Income increasing consistently over the last 5+ years?
     → YES: use DNI, current value = Net Income (TTM)
     → NO:  continue

4a. Profitable but inconsistent?
   Is TTM Net Income positive?
     → YES: is the average of the last 5 periods' Net Income also
       positive? (see "Smoothed current-value averages" below for exactly
       which 5 periods -- TTM is excluded, not just appended, whenever it
       duplicates the latest annual filing's own period)
              → YES: use DNI_NORMALIZED, current value = that 5-period
                average
              → NO: continue
     → NO: continue

5. Unprofitable / inconsistent company
   Is revenue growing aggressively? (CAGR from the earliest year with
   POSITIVE revenue — not simply the window's first year, which avoids
   a pre-revenue/IPO period poisoning the base — to TTM, ≥ 15%)
     → YES: use PSG
     → NO:  PASS — no method in the tree applies; no value is computed
            or estimated
```

There is no PE/PEG fallback in the live app — when nothing above applies,
the result is `PASS` with no intrinsic value produced, not a fallback
method.

**"Positive-and-increasing" (steps 2 and 4, and the FCF-flavored version
in 3a/3b):** requires at least 5 data points. A non-positive value
disqualifies the series outright only if it falls within the last 3
periods (matching the recency-gated convention used throughout this app —
see the Financials reference). An older non-positive value doesn't
disqualify on its own; the series instead falls through to the shared
trend classifier (see the Financials reference), and passes if that
classifier reads a recovery pattern.

**Method → calculation family:**

| Method | Engine | "Current value" represents |
|---|---|---|
| `DCF` | 20-year discounted model (§2) | Operating Cash Flow |
| `DFCF` | 20-year discounted model (§2) | Free Cash Flow (raw or normalized) |
| `DNI` | 20-year discounted model (§2) | Net Income |
| `DNI_NORMALIZED` | 20-year discounted model (§2) | 5-period-average (smoothed) Net Income |
| `CF_NORMALIZED`¹ | 20-year discounted model (§2) | 5-period-average (smoothed) Operating Cash Flow |
| `FCF_NORMALIZED`¹ | 20-year discounted model (§2) | 5-period-average (smoothed) Free Cash Flow |
| `PRICE_TO_BOOK` | Mean/SD Price-to-Book (§3) | n/a |
| `PSG` | Price-to-Sales-Growth (§4) | n/a |
| `PASS` | none — no value computed | n/a |

¹ `CF_NORMALIZED`/`FCF_NORMALIZED` are **Manual Calculation / Custom
Valuation-only** method choices — the method-selection tree above never
produces either. They exist for a case the tree doesn't otherwise handle:
CFO/FCF growing so fast in the last 2-3 years that the raw TTM figure would
overstate a sustainable run-rate, where a user judges the growth to be
transient rather than durable (see the "growing very fast" investigation
that motivated these two methods). A mechanical trigger for this — a CAGR
or spike-ratio threshold — was tested against the live universe and
rejected: it couldn't distinguish a genuine cyclical spike (e.g. a
memory-pricing supercycle) from a durable structural ramp (e.g. an AI-
buildout-driven CFO increase) using CFO/FCF figures alone, and risked
auto-suppressing exactly the highest-quality compounders in the tracked
universe. Selecting `CF_NORMALIZED`/`FCF_NORMALIZED` is therefore left to
the user's own judgment via Manual Calculation/Custom Valuation, never
auto-selected.

---

## 2. The 20-Year Discounted Model (DCF / DFCF / DNI / DNI_NORMALIZED / CF_NORMALIZED / FCF_NORMALIZED)

One calculation engine drives all six cash-flow/income-based methods.
Only the **meaning of the "current value" input** changes — the growth,
discounting, and terminal math are identical.

### 2.1 Inputs

| Field | Description | How it's actually sourced |
|---|---|---|
| `current_value` | Operating CF, Net Income, or FCF, TTM (or smoothed) | per the method table above |
| `total_debt` | Short-term + long-term debt, latest balance sheet | |
| `cash_and_st_investments` | Cash & equivalents + short-term investments, latest balance sheet | falls back to cash-only if the combined figure isn't available |
| `growth_yr_1_5` | Annual growth rate, years 1–5 | **the Growth Rate check's own projected growth CAGR**, reused directly (not independently estimated) |
| `growth_yr_6_10` | Annual growth rate, years 6–10 | defaults to `growth_yr_1_5`, capped at **15%** — an unmoderated 5yr analyst-estimate growth rate isn't a credible assumption to carry unmoderated into years 6–10 |
| `growth_yr_11_20` | Annual growth rate, years 11–20 | fixed terminal default of **4%** |
| `shares_outstanding` | Diluted shares outstanding | |
| `discount_rate` | see §5 (CAPM) | |
| `fx_rate` | statement (`reportedCurrency`) → USD spot rate | **1.0 for a USD reporter** (the vast majority of tickers); resolved per-ticker for a non-USD reporter — see §2.1b |
| `last_close` | current market price | |

All of `growth_yr_1_5`, `growth_yr_6_10`, `growth_yr_11_20`, and
`discount_rate` are pre-filled from the above and then freely user-editable
in the Manual Calculation panel — see that panel's own note on
persistence below.

### 2.1a Smoothed current-value averages (DNI_NORMALIZED / CF_NORMALIZED / FCF_NORMALIZED)

All three "smoothed" methods share one mechanism: a trailing average of
the last 5 periods of the underlying figure (Net Income / Operating CF /
Free Cash Flow respectively), each period's annual filing plus TTM
appended as the most current period — the same convention every other
TTM-inclusive series in this app uses.

**TTM-duplicate exclusion.** TTM is computed as the sum of the 4 most
recently reported quarters (see "Data sourcing notes" below), independent
of the annual filings. When a fiscal year has just closed and no newer
quarter has been reported since, those 4 quarters ARE the latest annual
filing's own Q1–Q4 — TTM and the last annual figure describe the
*identical* underlying period. Appending TTM after the annual series
unconditionally, as a naive implementation would, counts that one period
**twice** in a 5-point average (2/5 weight instead of the intended 1/5)
while every other period counts once — the opposite of what "smoothed"
is supposed to do, most visible for a company whose just-closed year was
itself an outlier (a cyclical earnings spike, say) that normalization
exists to dilute, not amplify.

This is detected by comparing the 4 most recent quarters' own
`fiscalYear`/`period` labels against the latest annual filing's — a
period-identity check, not a value-equality check (a coincidental value
match isn't the same condition; a genuine period match can differ
slightly in value after a restatement). When detected, TTM is **excluded**
and the average is taken over the prior **5 distinct fiscal years**
instead (not 4 — the window stays a true 5 points either way). Falls back
to including TTM if excluding it would leave fewer than 2 points to
average (not reachable for any currently-tracked ticker, all of which
have 5+ years of annual history, but guards a future thin-history ticker
the same way the average is never allowed to shrink to nothing).

Confirmed real case: SNDK's FY2026 (a memory-pricing supercycle year,
$11.4B Net Income — more than the prior 4 years combined) was being
counted at 2/5 weight in `net_income_smoothed` instead of the intended
1/5, before this exclusion existed.

### 2.1b Non-USD reported-currency conversion

A ticker's fundamentals aren't always reported in USD (e.g. TSM/ASML/BABA
report in TWD/EUR/CNY) — the stock's own last-close price is always USD
regardless, so a non-USD reporter's raw monetary figures must be converted
before they're compared against it. This is genuinely implemented, not a
theoretical `fx_rate` field left at a permanent 1.0 as an earlier version
of this document claimed.

- **Resolution**: `reportedCurrency` is read directly off the ticker's own
  income-statement filing (FMP's own field). A USD reporter short-circuits
  to `fx_rate = 1.0` with **zero** forex API calls. A non-USD reporter
  resolves a `<reportedCurrency>USD` spot rate (FMP's own forex-quote
  endpoint), cached the same way fundamentals are — via the same
  `FundamentalsCache` table and `get_or_fetch`/staleness machinery every
  other fetch in this app uses, keyed as its own `forex_rate`/`latest`
  cache row per currency pair, on the same `Settings.cache_staleness_days`
  window (default 7 days) as every other fundamentals fetch in this app —
  a deliberate choice to keep FX refresh aligned with fundamentals rather
  than running its own separate cadence.
- **Never a silent fallback to 1.0.** If a live forex fetch fails and no
  cached rate (fresh or stale) exists at all, the whole ticker reads
  `selected_method = "PASS"` / `insufficient_data = true` with an explicit
  reason — rendering a wildly-wrong Fair Value at the raw local-currency
  scale would be worse than showing nothing. A live fetch failure with a
  *stale* cached rate still available falls back to that stale rate rather
  than failing outright — a several-day-old spot rate is still far more
  useful than blocking the whole calculation.
- **Applied once, upfront.** Every raw monetary figure (Net Income, CFO,
  FCF, Revenue, debt, cash, book value per share, sales per share — every
  field that ultimately feeds Auto Calculation's `current_value_candidates`
  and the `§2.1`/`§3.1`/`§4.1` inputs above) is converted to USD
  immediately after being pulled from FMP, before `select_method`'s own
  tree runs and before any of the smoothing math in §2.1a. `select_method`
  itself is scale-invariant (every check it runs — CFO/NI ratio, CAGR,
  trend shape — is a ratio or a relative comparison), so converting before
  or after method selection can never change which method gets picked;
  doing it upfront just means every downstream consumer (Auto's own
  displayed inputs, Manual Calculation's pre-fill, a saved Custom
  Valuation's parameters) always sees genuine USD, never a raw
  local-currency number silently masquerading as one that some later step
  forgot to convert. `fx_rate` is therefore pure display metadata by the
  time it reaches the 20-year engine (§2.2–2.4) or the P/B formula (§3.2)
  — multiplying an already-USD figure by `fx_rate = 1.0` again is a
  deliberate, harmless no-op at every one of those call sites, not a
  double-conversion bug.
- **Shown in the UI** as a caption directly under the Fair Value headline
  (both Auto Calculation and the Manual Calculation panel) — "Converted
  from `<CCY>` @ `<rate>` (as of `<date>`)" — for a non-USD reporter only;
  nothing renders for a USD reporter. If `reportedCurrency` is set but no
  rate could be resolved, the caption instead reads "`<CCY>` → USD rate
  unavailable — Valuation may be incomplete."

### 2.2 Projection (years 1–20)

```
for t = 1..5:   value[t] = value[t-1] * (1 + growth_yr_1_5)     # value[0] = current_value
for t = 6..10:  value[t] = value[t-1] * (1 + growth_yr_6_10)
for t = 11..20: value[t] = value[t-1] * (1 + growth_yr_11_20)
```

### 2.3 Discounting

```
discount_factor[t]  = 1 / (1 + discount_rate) ** t
discounted_value[t] = value[t] * discount_factor[t]
```

### 2.4 Roll-up to intrinsic value

```
pv_sum                    = Σ discounted_value[t]  for t = 1..20
intrinsic_value_pre_adj   = pv_sum / shares_outstanding
less_debt_per_share       = total_debt / shares_outstanding
plus_cash_per_share       = cash_and_st_investments / shares_outstanding

intrinsic_value_per_share = intrinsic_value_pre_adj - less_debt_per_share + plus_cash_per_share
final_iv_per_share        = intrinsic_value_per_share * fx_rate

discount_premium_pct      = last_close / final_iv_per_share - 1
```

`discount_premium_pct < 0` → stock trades below intrinsic value.
`discount_premium_pct > 0` → stock trades above intrinsic value.

---

## 3. Price to Book (Bank, REIT/Property Developer)

### 3.1 Inputs

| Field | Description |
|---|---|
| `book_value_per_share` | current Book Value per share -- `(Total Assets − Intangible Assets − Total Liabilities) / Shares Outstanding`, computed from the **latest quarter's** balance sheet (2026-08-13 fix; see below) |
| `historical_pb_ratios` | up to 10 most recent year-end P/B ratios, chronological |
| `lookback` | **auto-selected**, not user-chosen at the Auto Calculation stage: `"10 years"` if at least 10 years of historical P/B data exist, else `"5 years"` if at least 5 exist, else no Price-to-Book result is produced at all |
| `last_close` | current market price |

**Book value formula/anchor fix (2026-08-13):** `book_value_per_share` previously came
straight from FMP's own `bookValuePerShare` ratio field (raw stockholders' equity per share,
i.e. **not** intangibles-stripped -- confirmed identical to FMP's own
`shareholdersEquityPerShare` field) off the **latest annual** `ratios` row -- up to ~12
months stale versus the quarterly balance-sheet data this same calculation already used for
`total_debt`/`cash_and_st_investments`. It's now computed directly from the latest quarter's
balance sheet (`totalAssets − goodwillAndIntangibleAssets − totalLiabilities`, divided by
shares outstanding) -- matching this section's own formula above, and the same
latest-quarter-instant convention used everywhere else in this calculation. Confirmed via
real cached data: JPM's book value/share moved from $129.97 (FY2025 annual, raw equity) to
$115.80 (Q2 2026 quarter, tangible); O's (Realty Income) moved from $44.35 (FY2025 annual,
raw equity) to $39.52 (Q2 2026 quarter, tangible) -- both changes reflect the anchor moving
forward by ~2 quarters *and* intangibles being stripped out, not either alone.

**Known, accepted inconsistency:** `historical_pb_ratios` (used for the mean/SD bands in
§3.2 below) still comes from FMP's own `priceToBookRatio` ratio series, which is itself
computed against FMP's raw (non-tangible) `bookValuePerShare`, not the tangible figure above
-- so the *historical* series and the *current* book value now sit on slightly different
bases. Rebuilding the full 10-year historical series on a tangible/latest-quarter basis would
require a new annual balance-sheet fetch this calculation doesn't otherwise need; the cheaper
fix (align only the current book value, leave the historical series as FMP reports it) was
chosen deliberately over that cost. Not expected to matter much in practice -- the two bases
track closely for most companies -- but is a known, documented approximation, not an
oversight.

### 3.2 Calculation

```
window  = the most recent N entries of historical_pb_ratios, per lookback above
mean_pb = average(window)
sd_pb   = sample standard deviation of window   # n-1 denominator

pb_minus_2sd = mean_pb - 2 * sd_pb
pb_minus_1sd = mean_pb - 1 * sd_pb
pb_mean      = mean_pb
pb_plus_1sd  = mean_pb + 1 * sd_pb
pb_plus_2sd  = mean_pb + 2 * sd_pb

iv[band] = pb[band] * book_value_per_share * fx_rate   for each of the 5 bands above

discount_premium_pct = last_close / iv["mean"] - 1
```

All five bands (−2SD, −1SD, mean, +1SD, +2SD) are shown as the valuation
range; the **mean** band is what `discount_premium_pct` and the verdict
(§6) are based on.

### 3.3 Informational-only additions (never change the calculation above)

- **Historical P/B buy signal**: `last_close ≤ iv["minus_1sd"]` — a
  supplementary flag surfaced alongside the 5-band range. Never wired into
  the verdict logic in §6, which keeps its own mean ± 10% read unchanged.
- **Benchmark P/B ranges**, shown as fixed context (never used to gate or
  adjust the calculation): Bank **1.2× – 1.4×**; REIT/Property Developer
  **up to 1.2×** as "fair," with up to **1.5×** noted as acceptable given
  high double-digit DPU (dividend-per-unit) growth — that DPU-growth
  qualifier is a judgment call for whoever reads the note, not a second
  automated numeric threshold.
- **REIT dividend yield check** (REIT/Property Developer only): flags
  whether trailing dividend yield is **≥ 4%**. Informational only.
- **REIT DPU growth note** (REIT/Property Developer only): a simple
  last-vs-first comparison of the dividend-per-share series across the
  reporting window ("grew from X to Y" / "declined from X to Y") — not a
  full trend classification, since the underlying judgment ("consistently
  growing or stable") is meant to be read qualitatively. Informational
  only.

---

## 4. Price to Sales Growth (PSG) — unprofitable, fast-growing companies

### 4.1 Inputs

| Field | Description |
|---|---|
| `sales_per_share` | current revenue per share |
| `projected_growth_rate` | forward revenue growth rate (decimal) — same figure as `growth_yr_1_5` above (the Growth Rate check's own projected CAGR) |
| `fair_psg_ratio` | benchmark "fair" PSG ratio — default **0.2**, not automated |
| `last_close` | current market price |

### 4.2 Calculation

```
current_psg_ratio        = last_close / sales_per_share / (projected_growth_rate * 100)
intrinsic_value_per_share = fair_psg_ratio * sales_per_share * projected_growth_rate * 100
final_iv_per_share        = intrinsic_value_per_share * fx_rate
discount_premium_pct      = last_close / final_iv_per_share - 1
```

Note the `* 100`: growth is expressed as a percentage number inside this
specific formula, not a decimal fraction — this is deliberate, matching
the original workbook exactly.

---

## 5. Discount Rate (CAPM) — feeds §2 only

```
discount_rate = risk_free_rate + beta * market_risk_premium
```

- `risk_free_rate` and `market_risk_premium` are **manually-maintained
  settings** (editable via the app's Settings page), not auto-fetched from
  any live source — current defaults are 5-year trailing averages (~3.61%
  risk-free rate, ~2.73% market risk premium) sourced from
  market-risk-premia.com at the time they were entered, and drift out of
  date until manually refreshed.
- **CAPM itself is US-only in the live app** — a narrower claim than it
  may sound: this is about the risk-free-rate/market-risk-premium pair
  specifically, not about currency conversion (§2.1b), which does handle
  non-USD reporters. The original workbook spec describes a parallel
  China/HK rate series; the underlying data model has a `region` key that
  could hold one, but no HK/China region, rate pair, or any
  region-selection UI is actually implemented — every valuation currently
  runs on the single US risk-free-rate/market-risk-premium pair regardless
  of the company's own listing or reporting currency.
- `beta` is the company's equity beta from the data provider's company
  profile.
- CAPM is applied directly to the actual beta value — **not** bucketed to
  the original workbook's own 0.1-increment manual reference table (that
  table was a manual reference only in the source workbook, never
  formula-linked). A beta below 0.8 is used as-is (not floored), flagged
  as outside the workbook's original reference range for display purposes
  only.

---

## 6. Reading the result

```
verdict = "undervalued"  if discount_premium_pct ≤ -10%
          "overvalued"   if discount_premium_pct ≥ +10%
          "fair"          otherwise
```

Displayed as **Undervalued** / **Fair Valued** / **Overvalued** — this is
a live-price-vs-fair-value read, unrelated to the Overall Assessment's
Fail/Pass/Strong Pass verdict scale. `verdict` is `null` whenever no
valuation method could be applied (`PASS`) or a required input is missing.

## Manual Calculation panel / Custom Valuation

Below the automatic result, every input above is editable in a what-if
panel that re-runs the same formulas with user-supplied values. Every
field pre-fills from Auto Calculation's own live figures — for
DNI_NORMALIZED/CF_NORMALIZED/FCF_NORMALIZED specifically, "Current Value"
pre-fills from the smoothed candidate described in §2.1a, computed fresh
on every page load, regardless of which method Auto itself picked for
this ticker.

An edit here is a live what-if by default — recomputed against the panel's
own inputs, never written anywhere, and gone on reload. **Saving it as a
Custom Valuation** (one persistent row per ticker, no history/versioning)
is a separate, explicit action: once saved and activated, the saved method
+ parameter set — including whatever "Current Value" was showing at save
time — becomes this ticker's valuation everywhere (Valuation tab, ticker
header pill, Screener, Watchlist), replacing Auto Calculation's own pick,
until deactivated or resaved. A saved value is **frozen as of save time**,
same convention this app uses elsewhere for saved/static data: reopening
a saved Custom Valuation shows the number that was saved, not a
freshly-recomputed smoothed figure, even if the underlying fundamentals
have since changed. Only `last_close` (and, for Auto's own
company_type/method_reasoning context shown alongside a saved custom
value, Auto Calculation's own separately-live figures) stay live on every
page load; the saved numeric inputs themselves do not re-derive.

---

## Data sourcing notes (practical lessons from the original build-out)

1. **FCF and Operating CF are TTM (trailing twelve months), not
   last-fiscal-year annual** — computed as the sum of the 4 most recent
   reported quarters. This materially changes the result for fast-growing
   companies.
2. **Balance-sheet inputs (debt, cash, shares) use the single most recent
   reported quarter, not fiscal year-end** — for the same reason: a stale
   year-end snapshot understates how current the picture actually is.
3. **"Cash and Short-Term Investments" is ambiguous** when a company
   splits marketable securities into debt vs. equity tranches (e.g. large
   strategic equity stakes) — the data provider's standardized schema
   doesn't split this out, so the combined figure (cash + all short-term
   investments, potentially including equity positions) is used, falling
   back to cash-only if the combined figure isn't available.
4. **A company with near-zero or explicitly-stated-zero debt** reads as
   `total_debt = 0` rather than a missing/null value that would break the
   formula.
5. **Pending stock splits** are not specially handled — share count and
   price are taken as currently reported, with no split-adjustment logic.
