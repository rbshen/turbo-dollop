# Intrinsic Value Calculation — Specification

Source: `PP_VMI_Investing_Tools_-_2026_-_v1_1.xlsx`, tabs `VMI IV Calculator (20 years)`,
`VMI IV Calculator (Mean PB)`, `VMI IV Calculator (PSG)`, `Discount Rate Data`.

This document defines (1) which valuation method to select for a given company, and
(2) the exact formulas each method uses, so the web app reproduces the workbook's math
cell-for-cell.

---

## 1. Method Selection Workflow

Evaluate in order; stop at the first match.

```
1. Company type check
   Bank / REIT / Property Developer?
     → YES: use PRICE_TO_BOOK
     → NO: continue

2. Cash flow quality check
   CFO positive AND increasing consistently over the last 5+ years?
     → NO: go to step 4
     → YES: continue

3. CFO vs Net Income check
   CFO > 1.5 × Net Income?
     → NO:  use DCF (Discounted Cash Flow from Operations)
     → YES: is FCF (CFO − CapEx) positive AND consistent?
              → YES: use DFCF (Discounted Free Cash Flow)
              → NO:  normalize FCF using 5-year average CapEx
                       → now positive & consistent? YES → use DFCF
                                                     NO  → go to step 4

4. Net income check
   Net Income increasing consistently over the last 5+ years?
     → YES: is it a finance company (insurance, broker, asset manager)?
              → YES or NO, either way → use DNI (Discounted Net Income)
              (the workflow converges on DNI in both branches)
     → NO:  is it profitable but inconsistent?
              → YES: use normalized DNI (apply a smoothed/averaged net income
                     input into the same DNI formula) or another method below
              → NO:  go to step 5

5. Unprofitable company
   Is revenue/sales growing aggressively?
     → YES: use PSG (Price to Sales Growth ratio)
     → NO:  PASS — do not force-fit a valuation method

FALLBACK — PE / PEG:
   Only when none of the above can be applied. Never use as a default
   or quick check.
```

**Method → workbook tab mapping**

| Method | Workbook location | Notes |
|---|---|---|
| `DCF` (Discounted Operating Cash Flow) | `VMI IV Calculator (20 years)`, `F12 = "Discounted Cash Flow"` | Same 20-yr engine, input = Operating Cash Flow |
| `DFCF` (Discounted Free Cash Flow) | `VMI IV Calculator (20 years)`, `F12 = "Discounted Free Cash Flow"` | Same 20-yr engine, input = FCF (CFO − CapEx) |
| `DNI` (Discounted Net Income) | `VMI IV Calculator (20 years)`, `F12 = "Discounted Net Income"` | Same 20-yr engine, input = Net Income |
| `PRICE_TO_BOOK` | `VMI IV Calculator (Mean PB)` | Mean historical P/B × current Book Value/share |
| `PSG` | `VMI IV Calculator (PSG)` | Fair P/S ratio × Sales/share × growth rate |
| `PE` / `PEG` | not modeled in workbook | fallback only; implement separately if reached |

---

## 2. Method 1: The 20-Year Discounted Model (DCF / DFCF / DNI)

One calculation engine drives all three cash-flow-based methods. Only the **meaning of
the "current" input figure** changes (Operating CF, FCF, or Net Income) — the growth,
discounting, and terminal math are identical.

### 2.1 Inputs (all in the financial-statement currency, consistent units — usually $M)

| Field | Description | Example (MSFT) |
|---|---|---|
| `method` | one of `DCF` / `DNI` / `DFCF` | Discounted Free Cash Flow |
| `current_value` | Operating CF, Net Income, or FCF for the current/last fiscal year | 101,030.4 |
| `total_debt` | Short-term + long-term debt, latest balance sheet | 43,208 |
| `cash_and_st_investments` | Cash & equivalents + short-term investments, latest balance sheet | 102,012 |
| `growth_yr_1_5` | Annual growth rate, years 1–5 | 0.1748 |
| `growth_yr_6_10` | Annual growth rate, years 6–10 | 0.15 |
| `growth_yr_11_20` | Annual growth rate, years 11–20 | 0.04 |
| `shares_outstanding` | Diluted shares outstanding, millions | 7,466 |
| `discount_rate` | see §4 (CAPM) | 0.0661 |
| `current_fiscal_year` | last completed fiscal year | 2025 |
| `fx_rate` | 1 statement-currency unit = `fx_rate` listing-currency units | 1.0 |
| `last_close` | current market price, in listing currency | 405.76 |

### 2.2 Projection (years 1–20)

For `t = 1..5`:
```
value[t] = value[t-1] * (1 + growth_yr_1_5)      # value[0] = current_value
```
For `t = 6..10`:
```
value[t] = value[t-1] * (1 + growth_yr_6_10)
```
For `t = 11..20`:
```
value[t] = value[t-1] * (1 + growth_yr_11_20)
```

### 2.3 Discounting

```
discount_factor[t] = 1 / (1 + discount_rate) ** t
discounted_value[t] = value[t] * discount_factor[t]
```

### 2.4 Roll-up to Intrinsic Value

```
pv_sum                    = Σ discounted_value[t]  for t = 1..20
intrinsic_value_pre_adj   = pv_sum / shares_outstanding
less_debt_per_share       = total_debt / shares_outstanding
plus_cash_per_share       = cash_and_st_investments / shares_outstanding

intrinsic_value_per_share = intrinsic_value_pre_adj - less_debt_per_share + plus_cash_per_share
final_iv_per_share        = intrinsic_value_per_share * fx_rate     # convert to listing currency

discount_premium_pct      = last_close / final_iv_per_share - 1
```

`discount_premium_pct < 0` → stock trades below intrinsic value (undervalued).
`discount_premium_pct > 0` → stock trades above intrinsic value (overvalued).

### 2.5 Method-specific field labels (for UI only — math is identical)

| Method | "Current value" label | Growth-rate labels |
|---|---|---|
| DCF | Operating Cash Flow (Current) | Operating Cash Flow Growth Rate (Yr 1-5 / 6-10 / 11-20) |
| DNI | Net Income (Current) | Net Income Growth Rate (Yr 1-5 / 6-10 / 11-20) |
| DFCF | Free Cash Flow (Current) | Free Cash Flow Growth Rate (Yr 1-5 / 6-10 / 11-20) |

---

## 3. Method 2: Price to Book (banks, REITs, property developers)

### 3.1 Inputs

| Field | Description |
|---|---|
| `book_value_per_share` | current BV/share, statement currency |
| `historical_pb_ratios` | 5 or 10 most recent year-end P/B ratios (array) |
| `lookback` | `"5 years"` or `"10 years"` — selects how many of the array to use |
| `last_close` | current market price, listing currency |
| `fx_rate` | statement → listing currency conversion |

### 3.2 Calculation

```
window = last 5 entries of historical_pb_ratios if lookback == "5 years"
         else all 10 entries if lookback == "10 years"

mean_pb = average(window)
sd_pb   = sample_stdev(window)          # Excel STDEV.S — n-1 denominator

# Five bands around the mean
pb_minus_2sd = mean_pb - 2 * sd_pb
pb_minus_1sd = mean_pb - 1 * sd_pb
pb_mean      = mean_pb
pb_plus_1sd  = mean_pb + 1 * sd_pb
pb_plus_2sd  = mean_pb + 2 * sd_pb

# Intrinsic value bands, statement currency
iv[band] = pb[band] * book_value_per_share      for each of the 5 bands

# Convert to listing currency
final_iv[band] = iv[band] * fx_rate

discount_premium_pct = last_close / final_iv["mean"] - 1
```

Output the full 5-band range (−2SD, −1SD, mean, +1SD, +2SD), not just the mean — the
workbook presents all five as the valuation range.

---

## 4. Method 3: Price to Sales Growth (PSG) — unprofitable, fast-growing companies

### 4.1 Inputs

| Field | Description |
|---|---|
| `sales_per_share` | current sales (revenue) per share, statement currency |
| `projected_growth_rate` | forward revenue growth rate (decimal, e.g. 0.3099) |
| `fair_psg_ratio` | benchmark "fair" PSG ratio — workbook default `0.2` |
| `last_close` | current market price, listing currency |
| `fx_rate` | statement → listing currency conversion |

### 4.2 Calculation

```
current_psg_ratio = last_close / sales_per_share / (projected_growth_rate * 100)

intrinsic_value_per_share = fair_psg_ratio * sales_per_share * projected_growth_rate * 100
final_iv_per_share        = intrinsic_value_per_share * fx_rate

discount_premium_pct = last_close / final_iv_per_share - 1
```

Note the `* 100`: the workbook expresses growth as a percentage number inside this
specific formula (not a decimal fraction) — implement literally as above to match.

---

## 5. Discount Rate (CAPM) — feeds §2 only

```
discount_rate = risk_free_rate + beta * market_risk_premium
```

- `risk_free_rate` and `market_risk_premium` are 5-year trailing averages, region-specific:
  - **US stocks**: average of last 5 year-end 10-year Treasury yields (Rf) and equity
    risk premiums (MRP) from market-risk-premia.com/us.html
  - **China/HK stocks**: same source, `/hk.html`, separate Rf/MRP series
- `beta` is the company's equity beta (from any standard data provider).
- The workbook's own lookup table snaps beta to the nearest 0.1 bucket from 0.8 to
  "more than 1.6" (which uses 1.6 flat) purely as a **manual reference table** — it is
  NOT formula-linked to the discount rate input cell. **The web app should compute
  discount rate directly from the actual beta value via CAPM**, not bucket it, unless a
  bucketed/rounded convention is explicitly wanted for consistency with manual analyst
  workflows.
- Known edge case: if actual beta < 0.8, CAPM still applies directly (do not floor at
  0.8) — flag it in the UI as outside the workbook's original reference range.

```
rf_us   = average(last 5 year-end 10yr Treasury yields) / 100
mrp_us  = average(last 5 year-end equity risk premiums) / 100
rf_hk   = average(last 5 year-end China/HK risk-free rates) / 100
mrp_hk  = average(last 5 year-end China/HK risk premiums) / 100
```

---

## 6. Data Sourcing Notes (from live implementation experience)

These are practical lessons from running this model end-to-end against SEC EDGAR /
market data for several tickers — worth encoding as app-level rules or at least
warnings surfaced to the user:

1. **FCF and Operating CF should be TTM (trailing twelve months), not last-fiscal-year
   annual.** Compute as: `TTM = latest_annual − same_period_last_year + latest_reported_period`,
   using the most recent 10-Q/10-K XBRL facts. This materially changes the result for
   fast-growing companies (seen a ~23% intrinsic-value swing on one ticker from this
   alone).
2. **Balance-sheet inputs (debt, cash, shares) should use the single most recent
   reported instant — latest quarter, not fiscal year-end** — for the same reason.
3. **"Cash and Short Term Investments" is ambiguous when a company splits marketable
   securities into debt vs. equity tranches** (e.g. large strategic equity stakes).
   Decide and document whether the app includes equity-security holdings in this field
   by default, or only debt/cash-equivalent instruments — this can swing the result
   significantly and should probably be a user-visible toggle rather than a silent
   default.
4. **No free, key-less API reliably provides a true "5-year consensus EPS growth
   rate."** In practice the best free proxies are (in rough order of preference):
   - a source's explicit "expected/projected long-term growth rate" if labeled as such
   - EPS-specific multi-year growth forecast (e.g. "EPS expected to grow X% per annum")
   - Net Income CAGR over the next N years (least preferred proxy — income ≠ EPS when
     share count is changing)
   Always store which proxy was used and surface it in the UI; never silently treat a
   1-year forward growth number as the 5-year rate — the two can differ by 5-10x for
   post-slump names.
5. **Watch for pending stock splits.** If a split has been announced but not yet
   effective, use pre-split share count and price consistently (both sides of the
   fraction), and flag that the app should re-fetch after the split's effective date.
6. **A company with near-zero or explicitly-stated-zero debt** ("no borrowings under
   credit facilities") should have `total_debt = 0` rather than defaulting to a missing
   or null value that breaks the formula.
