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
