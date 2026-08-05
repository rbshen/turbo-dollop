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
       positive?
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
| `PRICE_TO_BOOK` | Mean/SD Price-to-Book (§3) | n/a |
| `PSG` | Price-to-Sales-Growth (§4) | n/a |
| `PASS` | none — no value computed | n/a |

---

## 2. The 20-Year Discounted Model (DCF / DFCF / DNI / DNI_NORMALIZED)

One calculation engine drives all four cash-flow/income-based methods.
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
| `fx_rate` | statement → listing currency | **always 1.0** in the live app — every supported ticker is US-listed and USD-only; no currency conversion is actually performed despite the field's presence |
| `last_close` | current market price | |

All of `growth_yr_1_5`, `growth_yr_6_10`, `growth_yr_11_20`, and
`discount_rate` are pre-filled from the above and then freely user-editable
in the Manual Calculation panel — see that panel's own note on
persistence below.

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
| `book_value_per_share` | current Book Value per share |
| `historical_pb_ratios` | up to 10 most recent year-end P/B ratios, chronological |
| `lookback` | **auto-selected**, not user-chosen at the Auto Calculation stage: `"10 years"` if at least 10 years of historical P/B data exist, else `"5 years"` if at least 5 exist, else no Price-to-Book result is produced at all |
| `last_close` | current market price |

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
- **US-only in the live app.** The original workbook spec describes a
  parallel China/HK rate series; the underlying data model has a `region`
  key that could hold one, but no HK/China region, rate pair, or any
  region-selection UI is actually implemented — every valuation currently
  runs on the single US risk-free-rate/market-risk-premium pair regardless
  of the company's own listing.
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

## Manual Calculation panel

Below the automatic result, every input above is editable in a what-if
panel that re-runs the same formulas with user-supplied values. It is
**not persisted anywhere** — edits live only in the browser session and
reset the moment the page is left or reloaded; nothing here ever feeds
back into the automatic calculation or any other part of the app.

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
