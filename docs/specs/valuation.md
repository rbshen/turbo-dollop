# Valuation

The Valuation tab answers a different question than the Analysis tab: not "is this a
fundamentally sound business?" but **"is the stock currently priced fairly, given what the
business is worth?"** It estimates a fair value per share and compares that against the stock's
current price.

**Valuation is calculated completely separately from Overall Assessment and is never blended
into it.** A company can have a strong Overall Assessment while its stock looks expensive, or a
weak Overall Assessment while its stock looks cheap — these are intentionally independent reads,
and the app never mixes them into one number.

## The fair-value method depends on the type of company

- **Banks and REITs/Property Developers** are valued using a **Price-to-Book**-based approach —
  comparing the stock's price to the company's book (net asset) value, rather than a cash-flow
  projection. As of 2026-09-14 the default is a **standard** (plain, non-tangible) book value
  basis; a tangible (intangibles-stripped) variant exists as a manual-only "Price to Book
  (custom)" alternative.
- **Typical operating companies with strong, reliable cash generation** are valued by projecting
  their cash flow forward and discounting it back to a present value. Fathom checks the quality
  of a company's cash flow first and prefers the most cash-based version it can reliably
  support, falling back to a profit-based version when cash flow itself isn't reliable enough
  (common for insurers, whose cash flow is naturally lumpy due to claims timing and reserve
  movements).
- **Unprofitable but fast-growing companies**, where neither a cash-flow nor a profit-based
  method has anything usable to project, are valued off their sales growth trajectory instead.
- If none of these approaches has enough usable data to apply, Valuation reports that no method
  currently applies, rather than forcing an estimate from insufficient data — and, as of
  2026-09-15, if a company's book value per share (or, for the cash-flow methods, its final
  per-share value after the debt/cash adjustment) works out non-positive, that one result is
  suppressed the same way rather than displayed as a fabricated negative "fair value."

## Reading the result

Once a fair value per share is calculated, Fathom compares it to the stock's live price and
labels the result **Undervalued**, **Fair Valued**, or **Overvalued**.

## The Manual Calculation panel — and saving it as a Custom Valuation

Below the automatic result, a **Manual Calculation** panel lets you override the underlying
inputs to see how the fair value estimate changes under different assumptions. By default this
is a what-if tool: changes reset the moment you leave the page.

You can also **save** your inputs as a **Custom Valuation** for that ticker. Once saved and
activated, it replaces the automatic result everywhere that ticker's valuation is shown (the
Valuation tab, the ticker's header price tag, the Screener, your Watchlists) — until you
deactivate it or save a new one. A saved Custom Valuation is a snapshot: it keeps showing the
numbers you saved, not numbers that silently update themselves as the underlying business
changes.

---

## Technical reference

Calculated entirely separately from the Overall Assessment blend — no valuation figure is ever
folded into that score, and nothing here is "Step 3" of that framework.

Original source: `PP_VMI_Investing_Tools_-_2026_-_v1_1.xlsx`, tabs `VMI IV Calculator (20
years)`, `VMI IV Calculator (Mean PB)`, `VMI IV Calculator (PSG)`, `Discount Rate Data`. The
formulas below reproduce that workbook's math; deviations, where the live app behaves
differently, are called out explicitly.

### 1. Method Selection

Evaluated in order; stops at the first match.

```
1. Company type check
   Bank or REIT/Property Developer?
     -> YES: use PRICE_TO_BOOK (standard basis, see section 3)
     -> NO: continue

1a. Insurance check
   Insurance company?
     -> YES: skip steps 2/3/3a/3b entirely (the whole cash-flow-based method family) --
       claim timing, reserve movements, and investment portfolio fluctuations make
       Operating Cash Flow too unreliable a signal for insurers. Insurance still falls
       through to step 4 (Net Income) and its own normal fallback chain unchanged.
     -> NO: continue to step 2 as normal

2. Cash flow quality check
   CFO positive and increasing consistently over the last 5+ years?
     -> NO: go to step 4
     -> YES: continue

3. CFO vs Net Income check (both TTM figures)
   CFO > 1.5 x Net Income?
     -> NO:  use DCF, current value = CFO (TTM)
     -> YES: continue

3a. FCF quality check
   FCF (CFO - CapEx) positive and consistent?
     -> YES: use DFCF, current value = FCF (TTM)
     -> NO:  continue

3b. Normalized FCF
   Replace each year's actual CapEx with the trailing 5-year average CapEx, recompute
   FCF, retest positive-and-consistent
     -> YES: use DFCF, current value = the normalized series' TTM value
     -> NO:  go to step 4

4. Net income check
   Net Income increasing consistently over the last 5+ years?
     -> YES: use DNI, current value = Net Income (TTM)
     -> NO:  continue

4a. Profitable but inconsistent?
   Is TTM Net Income positive?
     -> YES: is the average of the last 5 periods' Net Income also positive?
              -> YES: use DNI_NORMALIZED, current value = that 5-period average
              -> NO: continue
     -> NO: continue

5. Unprofitable / inconsistent company
   Is revenue growing aggressively? (CAGR from the earliest year with POSITIVE
   revenue to TTM, >= 15%)
     -> YES: use PSG
     -> NO:  PASS -- no method in the tree applies
```

There is no PE/PEG fallback — when nothing above applies, the result is `PASS` with no intrinsic
value produced.

**"Positive-and-increasing"** (steps 2 and 4, and the FCF-flavored version in 3a/3b): requires at
least 5 data points (`METHOD_SELECTION_MIN_YEARS`). A non-positive value disqualifies the
series outright only if it falls within the last 3 periods (`NEGATIVE_VALUE_RECENCY_YEARS`). An
older non-positive value doesn't disqualify on its own — the series falls through to the shared
trend classifier (see [Financials](financials.md)), and passes if that classifier reads a
recovery pattern.

`scoring/trend.py::RECOVERY_PATTERNS` is the single source of truth for "reads a recovery
pattern": `grows_every_year`, `small_dip_recovers`, `significant_dip_recovers`,
`multiple_dips_resolved` and `dip_durably_resolved`. The last was missing from the set until
2026-08-08 (it scored identically to `multiple_dips_resolved` in `classify_trend`, but the set
itself was never updated). Three call sites gate on it, so all of them treat an age-resolved dip
as a recovery: Step 1's FCF cash-burn-recovery check (`scoring/step1.py`), this method-selection
tree (`_positive_and_increasing` / `_fcf_positive_and_consistent`), and Step 4's ROE/ROIC
min-year-consistency gate and negative-equity Net Income substitute (`scoring/step4.py`).

**Method → calculation family:**

| Method | Engine | "Current value" represents |
|---|---|---|
| `DCF` | 20-year discounted model (§2) | Operating Cash Flow |
| `DFCF` | 20-year discounted model (§2) | Free Cash Flow (raw or normalized) |
| `DNI` | 20-year discounted model (§2) | Net Income |
| `DNI_NORMALIZED` | 20-year discounted model (§2) | 5-period-average (smoothed) Net Income |
| `CF_NORMALIZED`¹ | 20-year discounted model (§2) | 5-period-average (smoothed) Operating Cash Flow |
| `FCF_NORMALIZED`¹ | 20-year discounted model (§2) | 5-period-average (smoothed) Free Cash Flow |
| `PRICE_TO_BOOK_STANDARD` | Mean/SD Price-to-Book, standard basis (§3) | n/a |
| `PRICE_TO_BOOK` | Mean/SD Price-to-Book, tangible basis (§3), "(custom)" label | n/a |
| `PSG` | Price-to-Sales-Growth (§4) | n/a |
| `PASS` | none — no value computed | n/a |

¹ `CF_NORMALIZED`/`FCF_NORMALIZED` are **Manual Calculation / Custom Valuation-only** method
choices — the method-selection tree above never produces either. They exist for a case the tree
doesn't otherwise handle: CFO/FCF growing so fast in the last 2-3 years that the raw TTM figure
would overstate a sustainable run-rate. A mechanical auto-trigger (a CAGR or spike-ratio
threshold) was tested against the live universe and rejected — it couldn't distinguish a genuine
cyclical spike from a durable structural ramp using CFO/FCF figures alone, and risked
auto-suppressing exactly the highest-quality compounders in the tracked universe (FMP has no
industry-cyclicality signal that could tell them apart). Once picked, they behave identically to
`DNI_NORMALIZED`: the same 20-year engine, the same Custom Valuation pre-fill/freeze semantics,
and the same FX handling (figures are already in the quote currency by the time smoothing runs). They are
pre-filled from `cfo_smoothed`/`fcf_smoothed`, which `data/step3_data.py` computes
unconditionally — the same pattern as `net_income_smoothed` and `pb_mean_ratio` — and which reuse
the TTM-duplicate exclusion below.

### 2. The 20-Year Discounted Model

One calculation engine drives all six cash-flow/income-based methods. Only the meaning of the
"current value" input changes.

#### 2.1 Inputs

| Field | Description | How it's actually sourced |
|---|---|---|
| `current_value` | Operating CF, Net Income, or FCF, TTM (or smoothed) | per the method table above |
| `total_debt` | Short-term + long-term debt, latest balance sheet | the **gated** quarterly balance sheet (below) |
| `cash_and_st_investments` | Cash & equivalents + short-term investments, latest balance sheet | falls back to cash-only if unavailable; the **gated** quarterly balance sheet (below) |
| `growth_yr_1_5` | Annual growth rate, years 1–5 | the Growth Rate check's own projected growth CAGR, reused directly |
| `growth_yr_6_10` | Annual growth rate, years 6–10 | defaults to `growth_yr_1_5`, capped at **15%** |
| `growth_yr_11_20` | Annual growth rate, years 11–20 | fixed terminal default of **4%** |
| `shares_outstanding` | Diluted shares outstanding | |
| `discount_rate` | see §5 (CAPM) | |
| `fx_rate` | statement (`reportedCurrency`) → quote-currency (`/profile` `currency`) spot rate | **1.0 whenever reported currency = quote currency** (every USD reporter); resolved per-ticker for a US-listed ADR that reports in a non-USD currency, see §2.1b |
| `last_close` | current market price | |

**Cleaned statements (2026-10-06).** Every statement figure above is read through the shared loader
([Statement data quality](statement-data-quality.md), "The shared loader"), so Valuation sees the same rows as the Analysis
tab. Placeholder and scale-broken cash-flow rows are treated as missing. When FMP served the newest quarterly balance sheet
partly filled in (debt or current assets remapped into another line), the **prior quarter's balance sheet** supplies
`total_debt`, `cash_and_st_investments` and the latest-quarter tangible and standard book value, and the income and cash-flow
quarters are **aligned** to that balance sheet's period end, so the TTM figures (revenue, net income, CFO, capex, hence
`current_value`) cover the four quarters ending on it. The annual balance sheet behind the historical P/B series and the
10-year `ratios` rows (`ratios_annual_10y`) are not gated. Shares stay on the quote / newest income quarter. A
current-value decision can change when the window shifts back one quarter (it did for TWLO: DCF to DFCF).

All of `growth_yr_1_5`, `growth_yr_6_10`, `growth_yr_11_20`, and `discount_rate` are pre-filled
and then freely user-editable in Manual Calculation.

#### 2.1a Smoothed current-value averages (DNI_NORMALIZED / CF_NORMALIZED / FCF_NORMALIZED)

A trailing average of the last 5 periods of the underlying figure, each period's annual filing
plus TTM appended as the most current period.

**TTM-duplicate exclusion.** When a fiscal year has just closed and no newer quarter has been
reported since, TTM (the sum of the 4 most recent quarters) and the last annual figure describe
the *identical* underlying period. Appending TTM unconditionally would count that one period
twice (2/5 weight instead of 1/5). Detected via a period-identity check (comparing fiscal-year
labels, not values) — `helpers/ttm.py::is_ttm_period_duplicate_of_last_fy` compares the 4 most
recent quarters' own `fiscalYear`/`period` labels against the latest annual filing's. Period
identity is the structurally correct test: a coincidental value match isn't the same condition
(it would false-clear on genuinely distinct periods), and a genuine period match can differ
slightly in value after a restatement (it would false-miss under a value check). When detected,
TTM is **excluded** and the average is taken over the prior **5 distinct fiscal years** instead
of dropping to a 4-point average. `scoring/step3.py::trailing_smoothed_average` implements this
for all three normalized methods (Net Income uses the income-statement check, CFO/FCF the
cash-flow one) and falls back to including TTM if excluding it would leave fewer than 2 points to
average — the same "never make a metric less scoreable" guard as
`step4.py::recovery_excluded_prefix_length`; not currently reachable, since every ticker hitting
the duplicate condition has 5+ years of history.

Confirmed real case: a memory-pricing supercycle year's Net Income was being counted at 2/5
weight in `net_income_smoothed` instead of the intended 1/5, before this exclusion existed.

#### 2.1b Non-USD reported-currency conversion

- **Resolution**: `reportedCurrency` is read directly off the ticker's own income-statement
  filing; the target is the ticker's **quote currency** (`/profile` `currency`, USD for every
  tracked ticker), not a hardcoded USD. A reporter whose reported currency equals its quote
  currency short-circuits to `fx_rate = 1.0` with zero forex API calls. Otherwise
  `_resolve_fx_rate` resolves two `<CCY>USD` legs (`reported→USD` and `quote→USD`; the quote leg
  is 1.0 for a USD quote) and returns `fx_rate = reported_to_usd / quote_to_usd`, cached via the
  same `FundamentalsCache`/`get_or_fetch` machinery every other fetch uses, on the same `cache_staleness_days` window
  (default 7 days) as every other fetch — a deliberate choice to keep FX refresh aligned with
  fundamentals. There is no separate FX staleness setting: a `fx_rate_staleness_days` (1 day)
  setting once existed in `core/config.py` but was never actually wired in, and was deleted
  2026-08-08 rather than changing live refresh behavior from 7 days to 1.
- **Never a silent fallback to 1.0.** If a live forex fetch fails and no cached rate (fresh or
  stale) exists at all, the whole ticker reads `selected_method = "PASS"` / `insufficient_data =
  true`. A live fetch failure with a *stale* cached rate still available falls back to that stale
  rate rather than failing outright.
- **Applied once, upfront.** Every raw monetary figure is converted to the quote currency immediately after
  being pulled from FMP, before `select_method`'s tree runs and before any smoothing math.
  `select_method` itself is scale-invariant, so converting before or after method selection can
  never change which method gets picked.
- **Shown in the UI** as a caption under the Fair Value headline when reported currency ≠ quote
  currency only: "Converted from `<reported>` to `<quote>` @ `<rate>` (as of `<date>`)."
- **Scope.** Non-US markets are not supported (shelved 2026-09-26); this conversion is kept for
  US-listed ADRs that report in a non-USD currency.
- 14 US-listed ADRs report in a non-USD currency but quote in USD (ASML, BABA, CCEP, CCJ, CNI,
  EVVTY, FER, MFC, NVO, PDD, RY, SINGY, TME, TSM), so this conversion is genuinely exercised in
  the tracked universe, not a theoretical branch. Only Valuation converts: the Financials/Ratios
  tabs, the Summary tab's statement-derived figures (incl. Enterprise Value) and the Watchlist
  trend charts show the raw reported currency, labelled, never converted.

#### 2.2 Projection (years 1–20)

```
for t = 1..5:   value[t] = value[t-1] * (1 + growth_yr_1_5)     # value[0] = current_value
for t = 6..10:  value[t] = value[t-1] * (1 + growth_yr_6_10)
for t = 11..20: value[t] = value[t-1] * (1 + growth_yr_11_20)
```

#### 2.3 Discounting

```
discount_factor[t]  = 1 / (1 + discount_rate) ** t
discounted_value[t] = value[t] * discount_factor[t]
```

#### 2.4 Roll-up to intrinsic value

```
pv_sum                    = sum(discounted_value[t] for t = 1..20)
intrinsic_value_pre_adj   = pv_sum / shares_outstanding
less_debt_per_share       = total_debt / shares_outstanding
plus_cash_per_share       = cash_and_st_investments / shares_outstanding

intrinsic_value_per_share = intrinsic_value_pre_adj - less_debt_per_share + plus_cash_per_share
final_iv_per_share        = intrinsic_value_per_share * fx_rate

discount_premium_pct      = last_close / final_iv_per_share - 1
```

**Negative-result guard (2026-09-15).** `run_20yr_engine` returns `None` (no result, not a
negative "intrinsic value") when the *final* per-share value works out `<= 0` — a company can
have a genuinely positive, healthy `current_value` and growth rates, yet a large gross debt load
relative to shares outstanding can still swamp the pre-adjustment value into negative territory.
Confirmed real cases where this fired before the guard existed: heavy-infrastructure/regulated
utilities, a captive-finance-arm automaker, and a margin-lending broker, none of which are
genuinely undervalued at a negative dollar figure — an output check, since no single input is
invalid on its own, only the combination. Every Auto Calculation and Manual Calculation call
site was updated to treat this the same as any other "no result" case.

`discount_premium_pct < 0` → stock trades below intrinsic value. `discount_premium_pct > 0` →
stock trades above intrinsic value.

### 3. Price to Book (Bank, REIT/Property Developer)

Two variants exist, computed in parallel via one shared, fully generic engine
(`bands_from_mean_sd`/`run_price_to_book`) — only their book-value basis differs.

#### 3.1 Standard basis (`PRICE_TO_BOOK_STANDARD`) — the default since 2026-09-14

```
book_value_per_share_standard = (Total Assets - Total Liabilities) / Shares Outstanding
```

Plain book value, no intangibles/goodwill subtraction. This matches FMP's own
`priceToBookRatio`/`bookValuePerShare` fields exactly (both are computed off `totalEquity`,
which already includes minority/non-controlling interest) — confirmed empirically, so the
**historical series needs no rescale at all**: `historical_pb_ratios_standard` is FMP's own
`priceToBookRatio` series used directly.

No new engine type was needed: `bands_from_mean_sd`/`run_price_to_book` (`scoring/step3.py`) are
fully generic and are simply called a second time with the standard-basis inputs;
`Step3Inputs`/`Step3ManualParams` carry parallel `_standard`-suffixed fields (5 and 3
respectively) and no existing field was renamed. There is no DB migration —
`TickerCustomValuation.method`/`parameters_json` are plain `str` columns. A saved Custom
Valuation with `method="PRICE_TO_BOOK"` is unaffected by the 2026-09-14 default change, because
`get_active_valuation` resolves purely off the stored method string, independent of
`select_method`'s tree; only the *auto-selected* default changed.

#### 3.2 Tangible / "custom" basis (`PRICE_TO_BOOK`) — manual-only since 2026-09-14

```
book_value_per_share = (Total Assets - goodwillAndIntangibleAssets - Total Liabilities) / Shares Outstanding
```

computed from the **latest quarter's** balance sheet (2026-08-13 fix — previously sourced from
FMP's own annual `bookValuePerShare` ratio field, raw stockholders' equity per share, up to ~12
months stale versus the quarterly data this calculation already used for `total_debt`/
`cash_and_st_investments`).

**Historical series rebuilt onto the same tangible basis (2026-08-15 fix)**: each year's ratio is
rescaled algebraically from FMP's own `priceToBookRatio = price / bookValuePerShare` for that
year, multiplying by `(totalEquity / tangible_book_value)` for the same fiscal year (the
share-count term FMP's own `bookValuePerShare` embeds cancels out of the algebra, so no separate
historical price fetch or reconstructed share count is needed; the balance sheets come from
`balance_sheet_statement`/`annual` (10 years) — the same cache key Step 4/Step 5 already populate,
so a cache hit with zero new FMP calls for any ticker already scored elsewhere; fixed
2026-09-14 from an earlier, understating `totalStockholdersEquity`-based multiplier that ignored
minority interest — material for NCI-bearing companies, ~7.9% understatement on one real REIT
case). A year is dropped from the series (not fabricated as zero) if its balance sheet can't be
matched by fiscal year, a required field is missing, or the resulting tangible book value is
non-positive. `pb_lookback`'s 10-year/5-year threshold counts the years that clear these guards,
not the raw FMP series length (e.g. HOOD kept only 5 of its 7 raw years, and the 5-year fallback
engaged correctly). Where a year's tangible book value is close to zero the rescaled ratio can be
an extreme outlier (EQIX's tangible series had two ~600x years), one reason the standard basis is
the default.

This variant was the *only* Price-to-Book method before 2026-09-14, auto-selected for Bank/REIT/
Property Developer; it's now demoted to a manual-only choice, labeled "Price to Book (custom)"
in the UI.

**Negative book value guard (2026-09-15).** `bands_from_mean_sd` returns `None` (on either basis)
when `book_value_per_share <= 0`, instead of computing a negative/zero "intrinsic value" that
the caller's verdict logic would otherwise mislabel as confidently "undervalued." One shared
choke point covers every P/B call path — Auto Calculation (both bases) and Manual
Calculation/Custom Valuation (both bases, via an explicit null-check with a distinct error
message). The raw point figures (`book_value_per_share`/`book_value_per_share_standard`
themselves) are untouched — a real negative book value is still shown as-is; only the derived
P/B multiple is blocked. Confirmed real cases this fixed: several heavy-goodwill/negative-equity
REITs that had previously shown a fabricated negative-dollar "undervalued" verdict.

#### 3.3 Calculation (either basis)

```
window  = the most recent N entries of historical_pb_ratios, per lookback below
mean_pb = average(window)
sd_pb   = sample standard deviation of window   # n-1 denominator

pb_minus_2sd = mean_pb - 2 * sd_pb
pb_minus_1sd = mean_pb - 1 * sd_pb
pb_mean      = mean_pb
pb_plus_1sd  = mean_pb + 1 * sd_pb
pb_plus_2sd  = mean_pb + 2 * sd_pb

iv[band] = pb[band] * book_value_per_share(_standard) * fx_rate   for each of the 5 bands above

discount_premium_pct = last_close / iv["mean"] - 1
```

`lookback` is **auto-selected**, not user-chosen at the Auto Calculation stage: `"10 years"` if
at least 10 years of historical P/B data (that clear the guards above) exist, else `"5 years"`
if at least 5 exist, else no Price-to-Book result is produced at all. All five bands are shown as
the valuation range; the **mean** band is what `discount_premium_pct` and the verdict (§6) are
based on.

#### 3.4 Informational-only additions (never change the calculation above)

- **Historical P/B buy signal**: `last_close ≤ iv["minus_1sd"]`, on the standard basis (like
  `benchmark_pb_*`, which also reads off the standard basis since 2026-09-14) — never wired into
  the verdict logic.
- **Benchmark P/B ranges**: Bank **1.2× – 1.4×**; REIT/Property Developer **up to 1.2×** as
  "fair," with up to **1.5×** noted as acceptable given high double-digit DPU growth.
- **REIT dividend yield check** (REIT/Property Developer only): flags whether trailing dividend
  yield is ≥ the configured threshold (default **5%**, editable via `/settings`).
- **REIT DPU growth note** (REIT/Property Developer only): a simple last-vs-first comparison of
  the dividend-per-share series, not a full trend classification.

### 4. Price to Sales Growth (PSG) — unprofitable, fast-growing companies

#### 4.1 Inputs

| Field | Description |
|---|---|
| `sales_per_share` | current revenue per share |
| `projected_growth_rate` | forward revenue growth rate (decimal) — same figure as `growth_yr_1_5` |
| `fair_psg_ratio` | benchmark "fair" PSG ratio — default **0.2**, not automated |
| `last_close` | current market price |

#### 4.2 Calculation

```
current_psg_ratio        = last_close / sales_per_share / (projected_growth_rate * 100)
intrinsic_value_per_share = fair_psg_ratio * sales_per_share * projected_growth_rate * 100
final_iv_per_share        = intrinsic_value_per_share * fx_rate
discount_premium_pct      = last_close / final_iv_per_share - 1
```

Note the `* 100`: growth is expressed as a percentage number inside this specific formula, not a
decimal fraction — deliberate, matching the original workbook exactly.

**Negative-growth guard (2026-09-15).** `run_psg` returns `None` when `projected_growth_rate <
0` — the formula's sign is determined entirely by growth's sign, so a company that qualified for
PSG on a healthy historical revenue CAGR but currently has a *negative* forward analyst-estimated
growth rate would otherwise produce a large negative "fair value."

### 5. Discount Rate (CAPM) — feeds §2 only

```
discount_rate = risk_free_rate + beta * market_risk_premium
```

- `risk_free_rate` and `market_risk_premium` are **manually-maintained settings**, not
  auto-fetched — current defaults are 5-year trailing averages (~3.61% risk-free rate, ~2.73%
  market risk premium) sourced from market-risk-premia.com at the time they were entered, and
  drift out of date until manually refreshed.
- **CAPM itself is US-only in the live app** — this is about the risk-free-rate/market-risk-
  premium pair specifically, not currency conversion (§2.1b), which does handle non-USD
  reporters. Every valuation currently runs on the single US risk-free-rate/market-risk-premium
  pair regardless of the company's own listing or reporting currency.
- `beta` is the company's equity beta from FMP's company profile.
- CAPM is applied directly to the actual beta value — **not** bucketed to a 0.1-increment
  reference table.

### 6. Reading the result

```
verdict = "undervalued"  if discount_premium_pct <= -10%
          "overvalued"   if discount_premium_pct >= +10%
          "fair"          otherwise
```

Displayed as **Undervalued** / **Fair Valued** / **Overvalued** — unrelated to the Overall
Assessment's Fail/Pass/Strong Pass scale. `verdict` is `null` whenever no valuation method could
be applied (`PASS`) or a required input is missing.

### Data sourcing notes

1. **FCF and Operating CF are TTM**, computed as the sum of the 4 most recent reported quarters.
2. **Balance-sheet inputs (debt, cash, shares) use the single most recent reported quarter**, not
   fiscal year-end.
3. **"Cash and Short-Term Investments" is ambiguous** when a company splits marketable
   securities into debt vs. equity tranches — the combined figure is used, falling back to
   cash-only if unavailable.
4. **A company with near-zero or explicitly-stated-zero debt** reads as `total_debt = 0` rather
   than a missing/null value.
5. **Pending stock splits** are not specially handled — share count and price are taken as
   currently reported.
