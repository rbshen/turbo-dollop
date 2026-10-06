# Statement data quality (read-time guards)

FMP's quarterly and annual statements are sometimes wrong in recognisable ways: a partly filled
newest balance sheet, a placeholder cash-flow row, a row in the wrong scale, a "Q4" that is really
the annual total. Fathom guards against these **at read time**, in the data layer
(`data/step5_data.py`, `helpers/ttm.py`, `helpers/balance_sheet_gate.py`), never in the scorers:
the scoring rules of every step are unchanged, they just receive cleaner inputs.

**The cache and the earnings-aware staleness rule are unchanged.** A bad row stays cached exactly as FMP
served it (history protection still applies, see [FMP data and bar cache](fmp-data-and-bar-cache.md)); the
guards decide what to *use*. `get_or_fetch_earnings_aware` treats a cached statement row as fresh until a new
earnings date plus 2 days has passed, whatever its content, so a partial row fetched after an earnings date is
not refetched until the next earnings date or a manual Refresh. Two facts widen that gap: the **earnings row
itself is cached on a flat 7-day window** (`get_or_fetch(..., "earnings", "latest")`, deliberately not
earnings-aware, which would be circular), so the earnings-aware trigger can slip up to 7 days after the real
earnings date; and a fetch two days after earnings can still precede the quarter landing at FMP, freezing the
old quarter. A refreshed *complete* row replaces the partial one (the history merge overwrites the same
periods) and the guard then simply stops firing. **Section 5** adds a bounded, targeted recheck of the three
quarterly statements for flagged tickers; it does not change the staleness rule and does not shorten the window
for any other ticker.

## The shared loader (`helpers/statement_view.py`)

One module turns cached statements into what the scored path reads, so no consumer re-implements the rules. Two layers:
`build_statement_view(raw, company_type, use_balance_sheet=True)` is pure (testable with synthetic rows),
`load_statement_view(session, ticker, company_type, ...)` is the cache read (the same `get_or_fetch_earnings_aware` keys and
limits every step already uses: annual 10, quarterly `TOTAL_QUARTERS_NEEDED`; no new cache key, no extra FMP call on a warm
cache). Order, unchanged from what `get_step5_data` always did: clean the cash-flow rows (sections 3-4) -> gate the balance
sheet (section 1) -> on fallback cut the income **and** cash-flow quarters off at the balance sheet that is used. The helpers
are reused as they are; the loader only composes them.

`StatementView` carries: `income_annual`, `income_quarterly` (aligned), `cash_flow_annual` / `cash_flow_quarterly` (cleaned,
aligned), `balance_sheet_annual` / `balance_sheet_quarterly` (raw), `balance_sheet_row` (the gated row), `selection`,
`balance_sheet_fallback` (the same `BalanceSheetFallback` facts `Step5Out` carries), `used` (period ends of the balance
sheet and of the income and cash-flow TTM windows), `debt_metrics` (`compute_debt_metrics` on the gated row and aligned
income) and `ttm(statement, line)` (Defect-B-aware `sum_last_four_quarters` over the cleaned quarters).

**Definitions.** The debt basis the gate watches follows the company type (REIT/Property Developer: FMP's `totalDebt`, no
current-assets check; everything else: short + long term debt); what a consumer *shows* as debt stays its own definition.
Alignment only happens when the gate falls back, one step back, with the 10-day tolerance (section 1). A statement a consumer
does not need can be left out (Step 1 reads no balance sheet: no gate, no alignment).

**Consumers.** Step 1 (cash flow only), Step 5, the **ticker header's** debt and EBITDA tiles (with the annual income rows,
so the Defect-B correction applies there too; shares still come from the quote) and **Speculative Growth's** cash and
last-two-quarters CFO direction (its qualification gate reads only Step 1, Step 2 and Moat and is unchanged). Step 3
Step 3 Valuation's debt, cash, net debt, tangible and standard book value and its TTM income and cash-flow figures (the annual
balance sheet behind the historical P/B series and `ratios_annual_10y` stay raw), and **Step 4's** TTM-slot balance-sheet
inputs (receivables, inventory, payables, equity, debt series and the REIT note) with its income and cash-flow TTMs aligned. ROE
and ROIC stay FMP's key-metrics values and are never rescaled.

**The data-quality function.** `data_quality_flags(raw, earnings, company_type, today)` returns the rules that currently trip
as structured `DataQualityFlag`s (`core/schemas.py`): `rule` (`placeholder_cf`, `scale_break`, `partial_balance_sheet`,
`not_landed`), `statement`, `period` (annual / quarterly), `period_end`, a short factual `evidence` string and a `detail` dict
(placeholder: `net_income`; scale break: `lines`, `log10_ratio`, `derived_q4`; partial balance sheet: the gate `reason` and the
incomplete / used quarter dates; not landed: `reported_on`; every row flag: `in_ttm_window`, true when the row is one of the
four newest raw quarters the Financials TTM column sums, or, for the balance sheet, the row its TTM column reads). It reuses
`is_placeholder_cash_flow_row`, `ttm.scale_break_evidence` (the same decision as `is_scale_broken_row`, plus the line count and
magnitude), `select_complete_balance_sheet` and the recheck's `not_landed_flag`. It is pure: nothing is persisted, there is no UI
wording, and a healed row simply stops producing its flag. Watch and a stored per-ticker flag can reuse it as it is.

## 1. Newest-quarter completeness gate (Step 5 only)

`helpers/balance_sheet_gate.py::select_complete_balance_sheet`, wired in `get_step5_data`.

FMP sometimes serves the newest quarterly balance sheet partly filled in, with a line remapped
into another one: long-term debt reads ~0 while total non-current liabilities stay flat (ZTS
9,045M → 190M with other non-current liabilities 500M → 9,556M; also CIEN, LHX, GILD, TWLO, GEV,
DOC, O, NEE), or current assets collapse while totals stay flat (ADP). Debt/EBITDA then reads ~0
and scores "excellent".

**Debt rule.** The newest quarter is treated as incomplete when total debt fell **65% or more**
versus the prior quarter **and** total liabilities fell by **less than half** of the absolute debt
decline (a genuine paydown takes total liabilities down with it: FSLR 426 → 38 with liabilities
−405 does not trigger) **and** the decline is at least **2% of the prior quarter's total assets**.
"Total debt" is the definition the scored path reads: short + long term debt on the Standard path,
FMP's `totalDebt` field on the REIT/Property Developer path (gearing), so the REIT path is covered
(DOC, O). The 2% materiality floor is not in the original brief: without it the rule also fired on
debt that genuinely went to zero but was immaterial (SHOP 16M, IONQ, ALAB, FFIV, CRDO, PDD, all
≤ 0.9% of assets; SHOP flipped Fail → Strong Pass from the window shift alone). Real remaps found
sit at ≥ 3.4%.

**Current-assets rule (Standard path only).** Current assets fell **more than 60%** while total
assets, total liabilities **and current liabilities** each moved within **±5%** ("roughly flat").
Current liabilities are also required flat (a pure remap of current into non-current assets leaves
them alone; NDAQ's rose 8× in the same quarter, a real restructuring).

**What happens.** The prior quarter's balance sheet is used for every balance-sheet figure
(debt, current ratio, deferred revenue, cash, net debt, total assets). **Period alignment:** the
income-statement and cash-flow quarters are cut off at the period end of the balance sheet that
is used: every leading quarter ending more than 10 days after it is dropped, so the TTM windows
(EBITDA, EBIT, interest, CFO, FCF) cover the four quarters ending on the same date as the balance
sheet. One step back only; the prior quarter is not itself re-checked. The fact is recorded on
`Step5Out.balance_sheet_fallback` (`reason`, `incomplete_quarter_date`, `used_quarter_date`,
`detail`) for a later Watch state; there is no UI for it yet.

**Other readers of the same rows.** Every consumer that does arithmetic on the balance sheet reads it through the shared
loader (see "The shared loader"), so the gate applies to the ticker header's debt tiles, Speculative Growth's cash, Valuation and Step 4's
balance-sheet series. Not routed, by design: the Financials and Ratios tabs keep
showing the raw rows, and FMP's own derived rows (key-metrics, ratios, enterprise values, which carry ROIC/ROE, P/B, EV) cannot
be cleaned here.

## 2. Plausibility check on the duplicate-annual-quarter correction ("Defect B")

`helpers/ttm.py::is_plausible_isolated_quarter`, used by `_corrected_recent_values`.

When FMP serves the just-closed fiscal year's annual total as the "Q4" quarterly row
(`is_quarter_content_duplicate_of_annual`, TEAM's case), `sum_last_four_quarters` derives the true
Q4 as `annual − (the other three quarters)`. That derivation assumed the annual row is real. It is
not when the annual row is a stub or all zeros: FERG's stub annual row made TTM EBITDA 898M instead
of about 3,129M; AZO's all-zero FY2026 cash-flow row made Q4 CFO −2.12B and TTM CFO exactly 0.

**The check.** The derived Q4 is used only if it is plausible next to the other three quarters of
that fiscal year, whose mean is *m*:

- it does **not flip sign** relative to *m*, and
- its magnitude is within **[¼, 4] × |m|**, both ends inclusive ("more than 4×" or "less than a
  quarter" is rejected; exactly 4× and exactly ¼ pass).

A zero mean has no scale and is never "plausible", which changes nothing (the other three quarters
sum to 0, so corrected and uncorrected Q4 are equal). When rejected, the **uncorrected quarters**
(as FMP reported them) are used for that line.

**Per line item.** The test runs for each field separately, so one harmless line cannot block a good
correction on another. BR, FDS, FN, INTU, LRCX, MU, NKE, PH and WDC trip only interest lines
(interest income/expense/net interest, an annual row carrying 0 for a line the quarters populate);
their revenue/EBITDA/net income/CFO corrections are unaffected.

**Known cost.** A genuine loss-to-profit (or reverse) Q4 is indistinguishable from a stub: TEAM's
isolated Q4 net income is +139.1M against three loss quarters, so TEAM's net income TTM is now the
raw sum (−246.7M) instead of the annual −53.8M (TEAM revenue and CFO are still corrected; Step 1
72 → 71). Distinguishing the two would need cross-line evidence, which is out of scope.

## 3. Placeholder cash-flow rows (the "P4" variant)

`helpers/ttm.py::is_placeholder_cash_flow_row` / `drop_placeholder_cash_flow_rows`, applied (with
section 4, through the single entry point `clean_cash_flow_statements`) in `get_step1_data`,
`get_step3_data`, `get_step4_data` and `get_step5_data` right after the statements are loaded.

FMP sometimes serves a period's cash-flow row as an empty skeleton beside a real income statement:
AZO's FY2026 annual row has 39 of 39 numeric lines 0 and its Q4 row 38 of 39 (one stray inventory
line); ITW, BX, LEN and ECL's newest quarter has only `netIncome` and an offsetting
`otherNonCashItems` plug non-zero. 16 tickers had a newest-quarter CFO of exactly 0 beside non-zero
net income. That is "not reported yet", not a real zero.

**The test (deliberately conservative).** A cash-flow row is a placeholder only when **all** of
these hold: CFO, free cash flow, capital expenditure, net investing and net financing cash flow are
each **present and exactly 0**, **and** the same period's income-statement net income (matched on
period-end date, else fiscal year + period) is **non-zero**. Nothing else is inspected, so a row with
a real CFO and a legitimately zero capex, buyback or debt line never matches, nor does any bank,
insurer or REIT row that reports activity; a period with no income row or a zero net income is never
a placeholder (it cannot be proven). There is **no** blanket "exact 0.0 means missing" rule for
revenue, net income, operating income, debt or capex: debt-free companies and pre-revenue names have
genuine zeros.

**Quarterly lists (most-recent-first).** The contiguous run of placeholders at the **newest end is
removed**, so the TTM window slides back to the **last four valid quarters**: AZO's Q4 FY2026 is a
placeholder, so TTM CFO covers Q4 FY2025 to Q3 FY2026. Only cash-flow rows move; the income
statement's window keeps its real newest quarter, so a ratio mixing the two (e.g. Step 5's Debt
Servicing Ratio) compares an income TTM with a cash-flow TTM one quarter older. A placeholder
**not** at the newest end is kept but blanked (numeric fields `None`, identity fields kept), so a TTM
window containing it reads **missing**: skipping an interior quarter would stretch the window beyond
12 months. With fewer than four valid quarters the TTM is **missing, never partial**.

**Annual lists.** Placeholders are blanked in place and never removed: the annual series are read
positionally and by fiscal year beside the income and balance-sheet series, so removing the newest
year would shift every year's CFO onto the wrong fiscal year. The blanked row is also no longer a
source for the Defect-B correction (section 2).

**Not covered.** The Financials tab keeps showing the raw rows exactly as FMP reported them (its TTM
column is the raw sum). Speculative Growth's last-two-quarters CFO direction reads the cleaned quarters (a placeholder newest
quarter is skipped), since the loader landed.

## 4. Scale breaks (whole-row unit errors)

`helpers/ttm.py::is_scale_broken_row`, applied to cash-flow rows by `clean_cash_flow_statements`.

AMCR's FY2026 annual cash-flow row is in unscaled **millions** (CFO 2,151; net income 1,106) while
every other row is in dollars (CFO 1,390,000,000 the year before). FMP derives every fiscal-year Q4
as annual minus the other three quarters, so the mis-scaled annual also poisoned the Q4 FY2026 row
(net income −716,998,894 = 1,106 − 717,000,000, against +389M on the income statement) and TTM CFO
came out as 22.7M instead of about 2.15B.

**The test.** A row is a scale break when, against the median of its **nearest four other rows** in
the same series (a line needs two non-zero neighbours), **at least 8** monetary lines are
comparable and **at least 80%** of them sit **at least 10^2.5 ≈ 316× away in the same direction**
(the midpoint between a 100× and a 1,000× shift; 100× is not flagged, 1,000× is) **and** the
log₁₀ ratios of those lines **cluster** (interquartile range ≤ 0.5 decades): one common unit factor,
not a young company that is simply much smaller than its later years. One tiny line can never
trigger it, so EME, MCHP, POOL and SYM are not flagged.

**Universe check before keeping the rule (2026-10-05).** All 38,131 cached statement rows (every
cached ticker × income, balance sheet and cash flow × annual and quarterly) were scanned: **exactly
one row is flagged, AMCR's FY2026 annual cash-flow row**, a genuine scale break. The closest
non-flag is VRT's pre-merger FY2016 balance sheet (89% of lines far off) which is a different
(shell) entity, spread over 1.2 decades, and is correctly not a unit shift.

**What happens.** The flagged annual row is blanked in place (as for placeholders), and the **Q4
quarterly row of the same fiscal year is treated as missing as well** (a derived row, see above):
being the newest quarter it is dropped, so AMCR's TTM CFO covers Q4 FY2025 to Q3 FY2026
(≈1.69B). This is *not* a rescale: the annual row is not multiplied back up, because that would
invent a figure; the cost is a TTM that is one quarter old and understated against the true
≈2.15B. A scale-broken quarterly row is handled the same way as a placeholder row.
Income-statement and balance-sheet rows are never touched by this rule (none is flagged today).

## 5. Recheck of flagged statements (targeted refetch)

`helpers/statement_recheck.py` (detection, state machine, cadence), table `RecheckState` (`core/models.py`, created
by `init_db`, one row per ticker). Evidence behind it: banks and many others heal when the 10-Q lands (about 22 to
45 days after quarter end, the row's `filingDate` moving to the 10-Q date), debt and current-assets remaps heal on
no fixed schedule, COF, ADP, O, GEV and CIEN were still unhealed at 60-75 days, HSBC (about 11 of 12 quarters
placeholder) never heals, and some tickers are frozen because the newest quarter had not reached FMP when fetched.

**Triggers** (read from the cache, no network; the first one tripped is `trigger`, all are in `rules_tripped`).
The first four reuse the existing helpers unchanged:

| Trigger | Fires when | Anchor |
|---|---|---|
| `placeholder_cf` | the newest quarterly cash-flow row is a placeholder (section 3) | that row's `filingDate` (else `acceptedDate`, else period end) |
| `debt_remap`, `current_assets_remap` | `select_complete_balance_sheet` falls back (section 1; REIT/Property Developer path uses `totalDebt` and skips the current-assets rule, as Step 5 does) | newest balance-sheet row's `filingDate` |
| `scale_break` | `is_scale_broken_row` is true for the newest quarterly **or** newest annual cash-flow row (section 4) | that row's `filingDate` |
| `not_landed` | R = last reported earnings date (`most_recent_reported_earnings_date`: a past date with a real actual) is **more than 3 days old** AND (**A**: the newest quarterly income period ends **more than 100 days** before R, OR **B**: the income statement's newest period ends **more than 10 days** after the balance sheet's or the cash-flow statement's) | R |

Thresholds: a landed quarter ends about 20-75 days before its earnings date, a not-landed one about 110-165 (the
prior quarter), so 100 days separates them; 10 days is `ALIGN_TOLERANCE_DAYS`, absorbing the day or two filers
differ between statements; 3 days is FMP's lag after an earnings date (the staleness buffer is 2). No cached
earnings or income rows: never fires. A not-yet-reported quarter (future earnings date) never fires. Universe: the
same one the nightly job fetches (`load_fundamentals_fetch_universe`: tracked universe, ETFs excluded).

**Status.** `active` (inside the window), `healed` (no rule trips on the cached rows any more; `healed_at`,
`days_to_heal_from_anchor`), `gave_up` (more than **60 days** after the anchor; a flag already past the window when
first seen is recorded as `gave_up` with `last_result = seeded_expired` and never retried), `chronic` (more than
half, i.e. at least 3, of the last four quarterly cash-flow rows are placeholders; checked before the window rule).
The **anchor is fixed for the episode**: a filingDate that later moves while the row is still flagged cannot extend
the window. Only a healed row, or an anchor more than 60 days later than the stored one, starts a new episode
(same row, `episodes + 1`, attempts reset).

**Cadence** (`is_due`). Active: **every night for the first 7 counted attempts, then every third night** (at least
3 days after the last attempt), until the window ends; after give-up the normal earnings-aware refetch is all that
is left. A ticker is not rechecked on the night the normal pass has just refetched its quarterly rows (it would
only re-read what it just got): a ticker seeded from a cache fetched on an earlier day is due the same night.
Chronic: one recheck, then **at most once every 365 days**.

**The nightly step** (`data/statement_recheck_data.py`, called by `pipeline/nightly_fundamentals_fetch.py` after its
per-ticker pass, only on the non-skipped path: after `job_skip_reason("fundamentals")`, so the FMP master switch and
the `fundamentals` group gate it). Per night: scan the run's tickers (cache only) and move their `RecheckState`;
take the due rows, **oldest attempt first** (never-attempted first, then oldest anchor); **cap 60 calls = 20
tickers** (deferrals are logged at info, and counted); per ticker refetch the **three quarterly statements only**
(income, balance sheet, cash flow, `TOTAL_QUARTERS_NEEDED`) through the production `core.cache.force_fetch`, so the
history merge and the `fetched_at` stamp are production's. Then re-evaluate the rules on the cached rows:

- no rule trips -> `healed` (`healed_at`, `days_to_heal_from_anchor` = days from the anchor to tonight);
- still flagged -> `attempts + 1`, state kept, no retry the same night ("a recheck that finds the same bad row" is a
  normal outcome, never a loop); past the window -> `gave_up`; chronic -> `chronic`;
- a refreshed ticker's Screener row is recomputed from the cache (`compute_ticker_score(cache_only=True)`, no FMP call).

**What is not an attempt.** A call blocked by a group toggle, the master switch, a restricted request variant or a
402/plan error makes no network call (or fails), writes nothing and records no attempt (`last_result = blocked`); a
timeout, 429 or 5xx is the same (`error`), as is an empty or non-list answer (`empty`, not written: stricter than
production, which would stamp `fetched_at` on it). An attempt counts only when all three statements got a live answer.
Whatever did succeed before a later failure stays written (production semantics), and a row cleared by it is `healed`.
A failed fetch raises out of `force_fetch` before any write, so cached rows are never wiped or re-stamped.

**Regression guard (the only guard).** A live payload is not written when its newest row trips a rule of that
statement - balance sheet: `debt_remap` / `current_assets_remap`; cash flow: `placeholder_cf` (against the live income
statement) / `scale_break` - that the cached newest row does not. It is logged as a warning, counted (`guard hits`), and
the attempt still counts (`last_result = regression_guard`). There is no plug-line allowlist: the manual catch-up's is
not part of this feature.

**Per-recheck log (info):** `Statement recheck TICKER: trigger T, attempt N, rules before -> after, filingDate
(income / balance / cash flow) before -> after, result R`. This is the heal-time evidence the repo lacked.

**Summary.** The job result carries `recheck` (`selected, healed, healed_by_cache, still_flagged, gave_up, deferred,
guard_hits, not_counted, errors, calls, scanned_flagged`); the `CronRunLog` message appends `, recheck: S selected, H
healed, F still flagged, G gave up, D deferred` (+ `, N guard hit(s)`) only when something happened. Informational: it
never enters `check_failure_threshold`; a gated no-op is still a success. A recheck failure is logged and swallowed.

**The earnings-aware path is untouched.** The recheck only moves the three quarterly rows' `fetched_at` forward after
the normal pass has run, like any fetch of those rows; a row stamped before a new earnings cutoff still reads stale once
the cutoff arrives (`tests/test_nightly_recheck.py`). It never refetches annual statements, ratios or any other key.

**Cost.** At most 60 calls a night (about 1 minute at the 220/min pacing). A ticker unhealed through its whole window
costs 25 attempts = 75 calls (7 daily, then every third night); a healed one far fewer.

## 6. Refresh fallback (ticker-page Refresh, 2026-10-05)

`POST /api/tickers/{t}/refresh` keeps every history row (statements, ratios, ...) but marks it stale (`INVALIDATED_AT`),
deletes the rest, then re-fetches live through `compute_ticker_score(cache_only=False)`. Before this fix, a live fetch that
failed (error, timeout, rate limit) went `get_or_fetch_earnings_aware` -> `safe_fetch` -> `{}`: the kept row was bypassed,
the steps read it as "no data", and `compute_ticker_score` **upserted a degraded TickerScore** over the last good one
(reproduced with the real step chain and mocked FMP: a good score of 88 became `overall_score = NULL`, `step4_verdict =
insufficient_data`, with the cached statements sitting in the table).

**Now**, only inside the Refresh (`core/cache.py::track_fetch_failures`, a per-task `ContextVar`; opted into by
`ticker_refresh` alone):

- a failed live fetch that has a cached row **serves that row** (no write, no re-stamp: the row keeps its stale marker,
  so the next normal fetch retries), so the steps score from the last real statements instead of from nothing;
- a failed fetch with **nothing cached** to fall back on is recorded, and `compute_ticker_score` then **does not persist**
  the row (a warning names the failed fetches): the previous TickerScore stays until the next successful refresh or the
  nightly recompute. This is deliberately conservative: any unrecovered failure, not only a statement one, blocks the write
  (a missed price-history fetch would otherwise null `perf_5y_vs_spy_pct`);
- every other caller (page loads, nightly jobs, `get_or_fetch` anywhere else) behaves exactly as before.

**Not changed:** the tabs the frontend re-requests after a Refresh are ordinary requests, outside the tracker: if FMP is
still down they still read empty (their stale rows are bypassed by `safe_fetch`'s `{}`). Serving the stale row on failure for
every caller is a wider behaviour change and is not part of this fix. The endpoint's response is unchanged (no "degraded" flag).
