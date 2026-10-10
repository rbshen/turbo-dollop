# Data quality flags (cache-only checks)

Informational flags about FMP statement rows that look wrong. **Feeds nothing**: not Overall, not any step or verdict, not `TickerScore`, not the Screener. Amber
(`warn`) only, never red, no verdict wording. Cache only: no FMP call, no SEC call, nothing fetched. Background:
`docs/sec-vs-fmp-data-quality-investigation-2026-10-09.md` (commit 84d6aef).

## Refresh test (2026-10-10), recorded before the build

The investigation could not say whether the ticker-page **Refresh** heals a wrong annual row. It was run once on the four known cases, in process, with exactly the
endpoint's logic (`groups_blocking_refresh`, `clear_ticker_cache`, `compute_ticker_score(cache_only=False)` inside `track_fetch_failures`), after a backup
(`backend/backups/pre_refresh_test_20261010.db.gz`, 204 MB). FMP master switch on, plan Ultimate, `fundamentals` and `profile_quote` live.

**Mechanism and failure behaviour.** Refresh does not wipe a ticker. Statement rows (income, balance sheet, cash flow, annual and quarterly) are history keys: they keep
their rows and get `fetched_at = INVALIDATED_AT`, and the refetch is merged into them, so a failed or shorter FMP answer leaves the old rows in place. Only snapshot rows
(profile, quote, price change, earnings, consensus, segmentation) are deleted, and `compute_ticker_score` refetches those it reads; the rest come back on the next tab view.
With `track_fetch_failures` a failed fetch serves the retained row and does not overwrite the last good `TickerScore`. It cannot leave a ticker without statements, so
the full Refresh was used, not a narrower refetch. Cost per ticker: **19 FMP calls** (`/profile`, `/quote`, `/stock-price-change`, `/earnings`, `/analyst-estimates`,
`/key-metrics`, `/key-metrics-ttm`, `/ratios` x2, `/ratios-ttm`, `/enterprise-values`, `/financial-growth`, `/historical-price-eod/full`, and the three statements x
annual and quarterly), against 22-27 cached rows cleared; **76 calls in total** for four tickers. 3-4 cleared snapshot rows per ticker (consensus, segmentation) were
not refetched and repopulate lazily.

| Ticker | Defect | Before | After | Result | Step 1 / Overall before | after |
|---|---|---|---|---|---|---|
| STX | FY2026 capex 0 | capex 0, FCF 3,674 | capex -569, FCF 3,105 (= SEC 569) | **healed** | 42 / 48 Fail | 42 / 48 Fail |
| CAT | FY2025 capex missing PP&E | capex -1,465, FCF 10,274 | capex -4,286 (= PP&E 2,821 + lease 1,465), FCF 7,453 | **healed** | 90 / 84 Pass | 88 / 85 Pass |
| GM | FY2025 capex missing PP&E | capex -15,793, FCF 11,074 | identical | **changed nothing** (FMP still serves the same row) | 60 / 39 Fail | 60 / 40 Fail |
| KKR | FY2025 CFO 9,684 vs SEC 478 | CFO 9,684, SBC 617 | CFO 478 (= SEC), FCF 317, SBC 722 (= SEC) | **healed** for CFO and SBC; FY2025 balance-sheet cash still 6.2M (SEC 17,152): **partly** | 70 / 45 Fail | 42 / 36 Fail |

Notes. The Overall movement of one point for CAT and GM comes from other refetched inputs (prices, estimates), not only from the repaired row. KKR's Step 1 fell from a
Pass to a Fail because the 9.7B CFO spike was the overstated value. Nothing ended worse than before, so no restore was done. No score was recomputed for any other
ticker. Lesson for the checks below: a flagged annual row is worth one manual Refresh (19 calls), which healed 3 of 4 here; the defects are in FMP's served row, not
frozen cache, but an old cached row is not refreshed until the next earnings date plus 2 days.

## The checks (`scoring/data_quality.py`, pure)

Pure functions over cached annual and quarterly rows, same split as the stuck-check module (the data layer reads and cleans, this module decides). The cash-flow rows arrive
cleaned (`clean_cash_flow_statements`): a placeholder or scale-broken row is blanked (CFO None) and every check skips it, because those rows already have their own markers
(`docs/specs/statement-data-quality.md`). A flag is `QualityFlag(ticker, check, field, fiscal_year, fmp_value, comparison_value, kind, detail)`.

| Check | Fires when | Kinds | Skipped for |
|---|---|---|---|
| `zero_newest_capex` | the newest usable annual row has capex 0 or missing and CFO non-zero, at least 2 of the prior 3 fiscal years carry capex (and more than half), the prior median capex is at least 0.5% of the newest revenue, and the quarterly rows of that fiscal year (dated after the prior year end, up to the newest year end, +/-10 days), where cached, report capex | `zero_line` | Bank, Insurance, REIT / Property Developer (Step 1 does not score their FCF) |
| `sbc_gap` | SBC is 0 or missing in a fiscal year between non-zero years, or in the newest year after non-zero years (last five years) | `zero_between`, `zero_newest` | an all-zero history and zeros before the first non-zero year (the stuck card's own "Not reported" rule; `sbc_zero_years` returns the count for that card) |
| `net_income_disagreement` | income-statement and cash-flow-statement net income for the same fiscal year differ by more than 25% of the larger figure **and** by at least 1% of revenue, or have opposite signs with a gap of at least 1% of revenue | `sign_differs`, `large_gap` (probable data error, newest three years); `definition` | -- |

`definition` (one flag per ticker, the newest such year) is raised instead of an error when the cash-flow figure equals the income statement's own
`netIncomeFromContinuingOperations` (within 2%), or is the larger figure in 3 or more of the last five years. FMP's cash-flow statement starts from consolidated
income from continuing operations and its income statement carries the parent's bottom line, so NCI (IBKR, KKR, BX, ARES, TKO) and discontinued operations (JNJ FY2023,
EMR, CARR, DLTR) disagree by construction. It is a different statement of the same number, not an error, and has its own kind.

## Tuning (run over the 582 tracked stocks, read-only, 2026-10-10)

- **Flags found:** 163 on 144 tickers: `zero_newest_capex` 3 (MU, CSCO, SYY), `sbc_gap` 103 (89 `zero_newest`, 14 `zero_between`, 93 tickers), `net_income_disagreement`
  57 (41 `definition`, 13 `large_gap`, 3 `sign_differs`). Pass-family hit: capex none; SBC 26 (AON, APH, BNY, CINF, CL, CTVA, IDXX, LIN, MAS, MCD, MCK, MO, MRK, NVO, NXPI, PM, RSG, SNA, STT, TDY,
  TME, TSM, TT, UNP, WM, WRB); net income 6 (A, AMP, HSBC, IBKR, JNJ, WTW). Watchlisted: capex MU; SBC APH, BE, BNY, IDXX, MCD, MRK, PM, STT, TSM; net income A, HSBC, HUT, IBKR, JNJ.
- **Known cases:** IBKR `definition` FY2025, WTW `sign_differs` FY2024, MU, CSCO, SYY `zero_line` FY2026 are caught on today's cache. STX is no longer flagged on today's cache
  because the 2026-10-10 Refresh healed its row; on the pre-Refresh rows (restored from the backup into a scratch copy) it is caught with the same rule (`zero_line`, FY2026).
- **False-positive rate, against the cached SEC facts (214 tickers; no SEC call):** `sbc_gap` 20 flags with an SEC figure, **20 have SEC SBC above 0, none is a true zero** (8 more have
  no SEC figure for the year, 75 no SEC row); the check finds 20 of the 92 last-five-year cells where FMP reads 0 and SEC is positive (32 are all-zero histories and 40 sit at the old end
  of the window, both left to the stuck card's count by design). `net_income_disagreement` data-error kinds (16 flags): **2 verified wrong cash-flow figures** (APO FY2024
  1,662 vs SEC `ProfitLoss` 6,373; WTW FY2024), 3 on tickers whose SEC row has no net income for that year (FERG, HUT, IREN: IREN's cash-flow figure is 0 against -703), 11 with no SEC row; the `definition` kind agreed with SEC on 8 of 14 checkable flags (cash flow = `ProfitLoss`, income =
  `NetIncomeLoss`) and the other 6 are filers whose tags differ (HSBC 20-F, DVA, FIS ...). `zero_newest_capex` has no SEC figure for MU, CSCO or SYY (newest year not cached);
  their quarterly rows carry capex, which is the corroboration the rule requires.
- **Thresholds chosen:** net income relative gap 25% and 1% of revenue. Sweep of (relative gap 10/25/50%) x (materiality 0.5/1/2/5% of revenue): data-error flags 26/22/22/15 at 10%,
  **16/16/17/11 at 25%**, 12/12/12/10 at 50%; 25% / 1% sits on the flat part of the curve and keeps WTW, APO and the others. Capex: prior years with capex 2 of 3, materiality 0.5% of
  revenue (0.2% and 0.5% give the same three tickers; 1% drops SYY, 2% leaves MU); the prior-year count (1, 2 or 3) changes nothing.
- **Noise to know about:** the SBC check fires on 15% of the universe (FMP reads the newest year's SBC as 0 for many tickers; the Refresh healed KKR's). It is accurate, not a false
  positive, but it is the bulk of any list. `definition` net income flags are 41 more rows that need no action.
