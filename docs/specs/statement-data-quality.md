# Statement data quality (read-time guards)

FMP's quarterly and annual statements are sometimes wrong in recognisable ways: a partly filled
newest balance sheet, a placeholder cash-flow row, a row in the wrong scale, a "Q4" that is really
the annual total. Fathom guards against these **at read time**, in the data layer
(`data/step5_data.py`, `helpers/ttm.py`, `helpers/balance_sheet_gate.py`), never in the scorers:
the scoring rules of every step are unchanged, they just receive cleaner inputs.

**The cache and refetch policy is unchanged.** A bad row stays cached exactly as FMP served it
(history protection still applies, see [FMP data and bar cache](fmp-data-and-bar-cache.md)); the
guards decide what to *use*. `get_or_fetch_earnings_aware` treats a cached statement row as fresh
until a new earnings date plus 2 days has passed, whatever its content, so a partial row fetched
after an earnings date is not refetched until the next one, a manual Refresh, or the next
earnings date. A refreshed *complete* row replaces the partial one (same periods are overwritten
by the history merge) and the guard then simply stops firing. Whether to also refetch suspect rows
early is a separate, undecided change.

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

**Other readers of the same rows.** Only Step 5 inherits the gate. The ticker header's debt tiles
(`ticker_summary.py`), Valuation (`step3_data.py`, net debt / `compute_debt_metrics`), Step 4's
invested capital, the Ratios tab and Speculative Growth still read the raw newest quarter and show
the bad row; this is reported, not changed.
