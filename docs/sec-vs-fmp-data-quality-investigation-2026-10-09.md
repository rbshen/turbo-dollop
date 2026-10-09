# Cached FMP vs SEC data-quality check: investigation, 2026-10-09

Report only. No code, spec, score or database change; cache only, **no SEC or FMP network call** (the SQLite file was opened `mode=ro`, the scratch scripts and their
extracts are deleted). Follow-up to item 9 of `docs/step1-cash-flow-distortion-investigation-2026-10-09.md`. Weights in force: `weights_version` 8 (Overall
35/20/20/25, Step 1 30/20/25/10/15, Narrow 0.85). Comparison basis: the 214 cached `sec_company_facts` rows against the 5 newest annual rows of FMP's income, balance
sheet and cash-flow statements (raw cached rows, before the read-time cleaner), 209 USD reporters, 23 fields, **20,376 comparable ticker-year-field cells**.
"Match" means within 1% (or $0.1M) of any candidate tag, either the latest-filed or the first-filed value.

## 1. Inventory

- **Rows.** `sec_company_facts`: 214 rows, one per ticker, 212 of them in the 582-ticker stock universe (EA, TWTR outside). Whole `companyfacts` JSON per row: median
  4.0 MB, max 6.8 MB, **798 MB in total = 57% of the 1.39 GB database file**, and every backup (five of about 150 MB gz, 723 MB in `backups/`) carries it. As-reported
  (`financial_statement_full_as_reported`): 37 tickers, annual and quarterly, **one fiscal year each** (36) or none (1); 6 of the 37 also have SEC facts.
- **How fetched.** Only on demand, through `get_or_fetch` (7-day staleness checked at read time): (a) Step 5's cross-check for an outlier-flagged quarter (interest
  expense, CFO), reached from `GET /api/tickers/{t}/step5`, (b) the Financials tab click on a zero Income Taxes Paid / Interest Paid cell. No cron job fetches it:
  `nightly_fundamentals_fetch` passes `allow_sec_cross_check=False` since `2461d7e` (2026-08-16), after 134 calls landed in one night (2026-08-14). The CIK comes
  from the FMP profile cache (`www.sec.gov` is blocked for this VPS, `3afb605`).
- **Pacing and lockout history.** `_fetch_company_facts` is a bare `httpx` GET: no limiter, no retry, no backoff, no `Retry-After` handling. The cron log holds 199
  `data.sec.gov` requests (2026-08-06 to 08-16, 131 on 08-14, about one a minute), **all HTTP 200; no 429/403 anywhere**. The app server's log is not in
  `backend/logs/`, so the roughly 10 a day since 2026-10-05 (48 `fetched_at` stamps, consistent with page views of flagged tickers, not verified) cannot be audited. The
  10-minute lockout is SEC's fair-use policy as quoted in the code, not an observed event; the only observed block is `www.sec.gov` at the Akamai edge.
- **Freshness.** Median age 56 days, 147 of 214 older than 30 days, 34 older than 60, max 80: nothing refreshes a row except a view. Effect: the newest fiscal year
  has no SEC figure for 9 of 209 tickers (ACN, LHX, MU, NWS, SMCI, SYY, XEL, IREN, FERG); older years are covered (revenue: 1-3 gaps per year).
- **Coverage of the 582 tracked stocks.** 212 (36%). Pass-family (Overall 70+, 198 tickers): **81 (41%)** (Strong Pass 7 of 19, Pass 46 of 100, Pass with caution 28
  of 79); Fail 127 of 376. Watchlisted stocks: 58 of 119 (49%). Pass-family or watchlisted and uncovered: **127 of 229**.
- **Structurally uncovered.** 16 universe tickers are not domestic 10-K filers (20-F/40-F/ADR or non-USD): ARM, ASML, BABA, CCEP, CCJ, CNI, EVVTY, FER, HSBC, MFC, NVO,
  PDD, RY, SINGY, TME, TSM. Five of them are cached (CCJ, PDD, BABA, ASML, TME), but 5 cached non-USD reporters (CNY x3, EUR, CAD) cannot be diffed against SEC's USD
  facts, and 3 profiles carry no CIK (CNSWF, SINGY, EVVTY). There is no HK or FR name in the tracked universe by profile country. About 26 uncovered US-listed companies
  domiciled in IE/CH/GB/CA/NL/BM file 10-Ks with us-gaap tags and are coverable. IFRS filers have `ifrs-full` facts, which this module does not read.

## 2. What to compare

Fields in priority order by score impact (weights: Step 1 CFO 25 and FCF 15 are 14 points of Overall; Revenue 30 is 10.5; Debt/EBITDA 45 of Step 5 is 11.25).
"Variant" is the share of matched cells that needed a tag other than the first-listed one.

| Pri | FMP field | Feeds | SEC tag(s) | Definition traps (observed) |
|---|---|---|---|---|
| 1 | `netCashProvidedByOperatingActivities` | Step 1 CFO + FCF, Step 5 servicing, Valuation DCF, Spec Growth, stuck row 1/3 | `NetCashProvidedByUsedInOperatingActivities`, `...ContinuingOperations` (1% of matches) | continuing vs total when a discontinued-ops line exists (DD, EBAY) |
| 1 | `capitalExpenditure` (so FCF) | Step 1 FCF, Valuation, stuck 1/3 | `PaymentsToAcquirePropertyPlantAndEquipment` (66%), `...ProductiveAssets` (16%), `...CapitalImprovements`; plus up to 3 extra lines | FMP adds software, intangibles, equipment on lease, leases held for investment (GM, CAT, INTU, DOCN: 100 of 970 cells need a 2-4 tag sum). A single-component match must be refused (GM FY2025 equals the lease line alone) |
| 1 | `revenue` | Step 1, margins, stuck 9/10 | `RevenueFromContractWithCustomerExcludingAssessedTax` (488 matches), `Revenues` (437), `...IncludingAssessedTax` (30) | **About half (519 of 1,020 cells) need a tag other than `Revenues`.** Banks/brokers: FMP is gross, SEC `RevenuesNetOfInterestExpense` is net (GS 125B vs 58B). MO: FMP net of excise taxes (-13% to -19% every year). Crypto miners: FMP includes digital-asset fair-value result (HUT 15 vs 235) |
| 1 | `netIncome` (income statement) | Step 1 NI, Valuation, stuck 1/3/6 | `NetIncomeLoss` (93%), `NetIncomeLossAvailableToCommonStockholdersBasic`, `ProfitLoss` | attributable vs consolidated: IS matches `NetIncomeLoss`, the cash-flow statement matches `ProfitLoss` (259 of 1,030 CF cells), so IBKR's gap is **inside FMP**, not FMP vs SEC |
| 2 | `shortTermDebt + longTermDebt` | Step 5 Debt/EBITDA (45 of Debt), header, Valuation net debt | `LongTermDebt`, `...Noncurrent` + `DebtCurrent`/`ShortTermBorrowings`/`CommercialPaper`, lease liabilities | **58% of cells need a non-first tag or a sum (42% a sum of 2-3 tags)**; FMP often includes operating and finance leases (13+ combos). A single `LongTermDebt` tag is wrong for PHM (44M vs 2,297M, senior notes under another tag) |
| 2 | `interestExpense`, `netInterestIncome` | Step 5 servicing (reads the **net** figure) | `InterestExpense` (398), `...Nonoperating` (168), `InterestAndDebtExpense`, `InterestExpenseDebt` | 39% of matches need a non-first tag; gross vs net (TPR 85 vs 271, SCHW 3,754 vs 836) |
| 2 | `operatingIncome` | Step 1 margins (10), EBIT tiebreaker | `OperatingIncomeLoss` | FMP's is a normalised build that excludes unusual items: 73 cells explained by impairment/restructuring/gain tags, 98 more differ (MO +22%, PEP +17%) |
| 2 | `depreciationAndAmortization`, `ebitda` | EBITDA (Step 5) | `DepreciationDepletionAndAmortization`, `...AndAmortization`, `...AndAccretionNet` | content amortization sits in FMP's D&A (NFLX 16.8B vs 0.33B, WBD). `ebitda` has no SEC tag (derived) |
| 3 | `cashAndCashEquivalents`, `totalStockholdersEquity`, current assets/liabilities | Valuation, Spec Growth, current ratio | `CashAndCashEquivalentsAtCarryingValue` / `...RestrictedCash...`, `StockholdersEquity` / `...IncludingPortion...`, `AssetsCurrent`, `LiabilitiesCurrent` | preferred stock in equity (CELH, RDDT), clearing balances (CME), insurers' investments (ELV), custody cash (NTRS 61B vs 5.9B) |
| 3 | `weightedAverageShsOutDil` | Valuation per-share, stuck 5 | `WeightedAverageNumberOfDilutedSharesOutstanding` (unit `shares`) | splits: 42 cells are split-adjusted in FMP and not in old filings (CMG 50:1) |
| 3 | `stockBasedCompensation`, buybacks, dividends | stuck 2-6 only | `ShareBasedCompensation`, `PaymentsForRepurchaseOfCommonStock`, `PaymentsOfDividends(CommonStock)` | **FMP reads SBC as 0** (section 3) |
| skip | receivables, payables, inventory, gross profit | Step 4 inputs | `AccountsReceivableNetCurrent`, `AccountsPayableCurrent`... | 13%, 8%, 3% material mismatch rates from definition alone; 51% of tickers have no `GrossProfit` tag |
| none | ROE, ROIC, ratios, key metrics, estimates, price | **Step 4 ROE+ROIC are 77 of Profitability**, Step 2, Valuation | no tag; FMP-derived | not checkable by a field diff (a recompute from SEC NI/equity would be a separate feature) |

## 3. One-off comparison (latest FY plus 4 prior)

| Class | Cells | Share |
|---|---|---|
| Match on the first-listed tag | 16,058 | 78.8% |
| Match on another tag of the same concept | 2,267 | 11.1% |
| Match on a multi-tag sum (capex, debt, D&A) | 540 | 2.7% |
| Split-adjusted shares | 42 | 0.2% |
| Operating income explained by unusual-item tags / discontinued-ops CFO | 73 / 5 | 0.4% |
| **Definition difference, explained** | **2,927** | **14.4%** |
| Mismatch, immaterial (under 10%, or under 1% of revenue) | 811 | 4.0% |
| **Mismatch, material (over 10% and over 1% of revenue)** | **580** (130 tickers) | **2.8%** |

- **False-positive rate from tag naming.** A naive diff against one conventional tag per field raises 4,318 alarms; **2,927 (68%) are explained by tag variants and
  definitions alone**: revenue 89%, net income 80%, debt 93%, capex 79%, cash 73%, interest 64%, D&A 67%, CFO 36% (CFO is the cleanest field: 997 of 1,030 match the
  first tag). Allowing one-tag variants alone removes 52% of alarms. The earlier HSBC and MTB examples cannot be replayed: neither has a cached SEC row (HSBC is a 20-F
  filer); the pattern fits the interest-expense variants (four tags in use, 39% of matched cells off the first).
- **Of the 580 material mismatches,** 337 drop out as not score-feeding (receivables 105, payables 69, SBC 37, buybacks 31, inventory 20 ...), bank/insurance/REIT
  structure (revenue, debt, cash, current items for lenders and insurers; REIT capex) or an entity discontinuity (PARA 2021). **243 remain** (66 on the latest FY);
  **84 are "breaks"** (the field matches in 2 or more other years and breaks in this one, a better defect signal than the size), 159 are persistent definition
  differences nobody decoded.
- **Pattern worth building on: the break test.** GM FY2021-24 capex equals PP&E + `PaymentsToAcquireLeasesHeldForInvestment` to the dollar, FY2025 does not; CAT the same
  with `PaymentsToAcquireEquipmentOnLease`; STX matched `PaymentsToAcquirePropertyPlantAndEquipment` four years and FY2026 is 0. A per-ticker "decomposition that held in
  prior years, fails now" test needs no definition table.
- **FMP zero gaps** (FMP value exactly 0, SEC non-zero): 160 cells: SBC 97, interest expense 15, D&A 13, inventory 10, payables 9, receivables 8, capex 7. SBC alone:
  **34 of 209 tickers, 25 of them in the newest FY, 7 Pass-family at the newest FY** (CBOE, MAS, MRK, SNA, TER, NTRS, MCK); GM, MPC, ED, PSX, TER, NTRS, CBOE are zero in
  all 5 years (the stuck card says "Not reported" for 3+ zero years) but GE, MRK, EBAY, KTOS, TRGP, PPG, WBD and others are zero in 1-2 years and understate the
  5-year SBC total, so rows 2-3 read OK on a partial sum.

### Known cases ($M)

| Case | Field | FMP | SEC | Caught? |
|---|---|---|---|---|
| GM FY2025 | capex | 15,793 | PP&E 9,303 (+ lease line 15,793; FY2021-24 = PP&E + lease exactly) | **Yes**, as a break. FY2021-24 classify as "definition" (PP&E + leases held for investment), not as alerts |
| CAT FY2025 | capex | 1,465 | PP&E 2,821 (FY2021-24 = PP&E + equipment on lease exactly) | **Yes**, break |
| KKR FY2025 | CFO | 9,684 | 478 | **Yes** (+19x). Same row also: cash 6 vs 17,152, D&A 0 vs -163, buybacks 123 vs 3 |
| BX FY2025 | CFO | 1,861 | 4,663 | **Yes** (-60%) |
| IBKR | net income (IS) | 984 (CF statement 4,357) | no cached SEC row | **No**: not covered; and with SEC cached it would **match** (`NetIncomeLoss` is also attributable). Only the cache-only IS vs CF net income test flags it |
| CSGP | capex | 389 (FY2025) | 307 | persistent, unexplained: all 5 years differ (FMP FY2023 capex 25 against its own PP&E line 143) |
| DOCN FY2025 | capex | 269 | 129 PP&E + 127 lease + 11 software + 2 intangibles = 269 | explained (4-tag sum), not an alert |
| INTU, SOUN, SEZL | capex | = PP&E + software | | explained; SEZL FY2025 2 vs 1 is rounding |
| STX FY2026 | capex | 0 | 569 | **Yes, new defect** (prior four years match the PP&E tag) |

Of the earlier "8 tickers over 25% off the PP&E tag": 3 defects (CAT, GM, STX), 1 persistent unexplained (CSGP), 4 explained (DOCN, INTU, SOUN, SEZL).

### Top new mismatches (not in the known list)

Score-feeding fields; "P" = Overall 70+. Direction: F = flatters the score, H = hurts.

| # | Ticker / period | Field | FMP | SEC | Pattern | Feeds | Dir | Overall |
|---|---|---|---|---|---|---|---|---|
| 1 | MU FY2026, CSCO FY2026, SYY FY2026 (not SEC-checked; cache evidence) | capex | 0 | prior FY 15,857 / 905 / 906; quarterly capex sums to about -36.8B (MU) | newest annual row loses the capex line; FCF = CFO. MU FCF 89.7B vs about 52.9B; CSCO about +0.7-0.9B (6%); SYY about +0.6-0.9B (25-33%) | Step 1 FCF, Valuation, stuck 1/3 | F | 47 / 69 / 67 Fail |
| 2 | STX FY2026 | capex | 0 | 569 | same; FCF 3,674 vs about 3,105 (+18%); quarterly capex +105 in the quarter ended 2026-01-02 (derived from the 0) | same | F | 48 Fail |
| 3 | PPG FY2025 (annual and the 2025-12-31 quarterly row) | total assets, equity | 7,959; -3,543 | 22,098; 7,941 | break; later quarters (2026-03, 2026-06) are right (22,150; 22,534), the annual row stays | Valuation P/B history, annual equity series | H | 61 Fail |
| 4 | FMP SBC = 0 | SBC | 0 | e.g. EBAY 607, MPC 160, CBOE 50 | 97 cells, 34 tickers, 25 at newest FY | stuck rows 2-3 only | F | 7 Pass-family |
| 5 | EBAY FY2025 | CFO | 2,186 | 1,959 total / 2,009 continuing | +9-12%, matches neither tag | Step 1, 5 | F | 57 Fail |
| 6 | CBOE FY2025, 2023, 2022 | CFO | 1,224 / 793 / 869 | 1,753 / 1,076 / 651 | 3 of 5 years, both signs | Step 1, 5 | H and F | 73 P |
| 7 | WTW FY2024 | net income (CF statement) | 1,248 | -98 (FMP's own IS shows -98) | FMP internally inconsistent; Step 1 reads the IS | stuck rows | F | 71 P |
| 8 | LLY FY2021-24 | capex | 8,404 (FY2024) | PP&E 5,058 | FMP 1.2-1.7x the tag, 4 of 5 years; FY2025 matches | FCF understated | H | 85 P |
| 9 | NFLX FY2024-25, WBD | D&A | 16,756 | 333 | content amortization in D&A; EBITDA 30.3B against operating income 13.3B | Step 5 Debt/EBITDA | F | 81 P |
| 10 | MO, PEP, BLK, CDNS, ADSK FY2025 | operating income | 12,035; 13,491; 7,909; 1,650; 1,794 | 9,899; 11,498; 7,045; 1,492; 1,578 | FMP excludes unusual items (+11% to +22%) | Step 1 margins (10 of Step 1) | F | 73-89 P |
| 11 | HUT FY2025 | revenue, capex | 15.1; 648 | 235; 203 | digital-asset fair value in FMP revenue; Q4 revenue -313M | Step 1 | H | 21 Fail |
| 12 | ELV, CME, NDAQ | current assets, gross profit | 24,726; 5,188; 3,939 | 63,001; 165,359; 5,249 | structural definitions (investments, clearing) | current ratio, margins | H | 66 / 83 / 68 |

## 4. Impact

Arithmetic only. Each field's maximum swing in Overall points is its weight product (Revenue 10.5, CFO 8.75, NI 7.0, FCF 5.25, Margins 3.5, Debt/EBITDA 11.25, servicing 7.5,
current ratio 6.25) times the Moat multiplier, compared with the distance to 70.

- **No Pass-family verdict plausibly flips from a confirmed defect.** GM, CAT (84, bound 5.25 against 14 of headroom), KKR (already 45), STX, MU, CSCO, SYY all
  flatter tickers already below 70, so correcting them moves them away from Pass; BX is not scored. CSCO (69) and SYY (67) are the only near-70 names and the
  correction lowers them.
- **Flips possible only by the maximum bound, all from definition differences:** ELV (66, current assets, bound 5.3 against 4), NDAQ (68, gross profit, 3.0 against 2),
  TPR (72, gross interest where Step 5 reads net, 6.4 against 2), PHM (64, SEC tag incomplete: FMP's 2,297 is the right number). None is a data defect.
- **Step 1 (not Overall) could move** for KKR (CFO 9,206 too high, Step 1 70 Pass could fall below 70, Overall 45 unchanged) and BX (CFO 2,802 too low).
- **Valuation:** CAT, GM, STX, MU, CSCO, SYY use the overstated FCF in the DCF; KKR's cash is 6 against about 17,000 (net debt); PPG's equity is negative in the annual P/B
  series. **Speculative Growth:** cash and CFO direction for the same names. **Stuck-check:** SBC zeros (rows 2-3), capex zeros (rows 1 and 3), CF-statement net income
  (WTW, IBKR).
- **Not covered by any field diff:** Step 4's ROE and ROIC (77 of Profitability) are FMP-derived ratios built from the same statements; PPG's bad balance sheet flows into
  them only through FMP.

## 5. Design options

Cache-only prefilters that need **no SEC call** and run on all 595 cached tickers: net income IS vs CF statement differs by more than 25% (122 hits, 67 tickers, 25 at
the newest FY: IBKR, HSBC, ARES, AZO, AMCR ...; WTW at the prior FY), newest annual capex 0 after non-zero years (12 tickers: STX, MU, CSCO, SYY, DLR, O ...), SBC 0 amid non-zero years (145 hits,
89 tickers). They catch IBKR, WTW, STX, MU, CSCO, SYY; only the SEC comparison catches GM, CAT, KKR, BX, PPG, EBAY, CBOE.

| | (a) standing weekly job | (b) per-ticker on the Analysis tab | (c) one-off audit | (d) nothing, fix by hand |
|---|---|---|---|---|
| Work | compact-projection table (read-model, registered in `ticker_data_registry`), pure compare module, `pipeline/` job with `cron_heartbeat`, `CRON_JOB_NAMES` + `_EXPECTED_CADENCE_HOURS` + `JOB_METADATA` + `crontab.txt` reinstall, tests (`test_cron_wiring`), Settings > Scheduled Jobs row comes from `JOB_METADATA` | one endpoint reusing `get_company_facts`, one card in the stuck-check style | this report extended to the uncovered set | no mechanism exists to correct a cell: only the Refresh button and the exempt lists |
| SEC budget | full sweep 582 requests once (about 2.3 GB at 4 MB each); steady state **only when a ticker's newest annual `filingDate` changes: about 582 a year**, peak Feb-Mar about 300 over 8 weeks; stored compact (154 KB per ticker measured, about 90 MB for 582) instead of 4 MB blobs | one request per cold view, about the 10 a day seen now | 359 uncovered 10-K filers once | 0 |
| Risk | lockout if unpaced (no limiter today); a standing bulk caller breaks the written "on-demand only, never in bulk" invariant in three docstrings and the 2026-08-14 incident; `sec_company_facts` is mapped to the `fundamentals` group, so FMP switches would pause it | invisible until someone looks; a 4 MB download inside a request | decays: this FY already added MU, CSCO, SYY, STX | defects persist until the next earnings refetch, and FMP may not heal them |
| Maintenance | tag-variant tables (revenue, debt, capex are not stable), a growing list of explained definitions | same tables | none | none |

**On a mismatch.** *Surface only* (a table and a Scheduled Jobs message, optionally one informational line in the stuck-check style): no score risk, consistent with that
card's "feeds nothing". *Auto-prefer SEC*: unsafe as a rule, since 68% of naive alarms are SEC-side tag problems (PHM, MO, ELV, GS) and CLAUDE.md names FMP the sole
fundamentals source; it could only ever be a whitelist of verified (field, break) pairs. *Override table*: fits the read-time guard layer (`helpers/statement_view.py`) but
needs a per-ticker table registered as PROTECTING or WIPE (a `MANUAL_DATA_MODELS` entry would also make its tickers "manual" universe members), a precedence rule, a retire-when-FMP-heals
rule, a recompute or `SCORE_FORMULA_VERSION` bump, and holds 5-9 real entries today.

**Recommendation (yours to confirm): (a) in a reduced form, surface only.** Weekly Sunday slot (like `stale_data_health_check`, 00:30), refresh gated on a new 10-K filing, a
compact projection, about 8 fields (CFO, capex, revenue, net income, debt, cash, SBC zero, operating income as informational), alerts only for breaks and zero gaps, never for
persistent definition differences; plus the three cache-only prefilters as a separate small step first. Overlaps: the **recheck** triggers on structure (placeholder, remap,
scale break, not landed) and refetches quarterlies only, so none of GM/CAT/STX/KKR/BX/PPG trips it (the placeholder test needs CFO, FCF, capex, investing and financing all
0); a SEC or prefilter break could become a recheck trigger for the annual cash-flow row. The **scale-break** test finds only unit errors (AMCR). The `_cross_check` module is the
natural base (`find_annual_value`, `get_company_facts`), but its single-tag 10% tolerance misses EBAY (+9%) and cannot tell GM's definition from a defect.

## 6. Coverage gap

| Step | Tickers | Requests | At 1 request / 5 s | Notes |
|---|---|---|---|---|
| Pass-family or watchlisted, uncovered, 10-K filers | 119 | 119 | 10 min, about 0.5 GB | 8 more are 20-F/ADR |
| All other uncovered 10-K filers | 240 | 240 | 20 min | |
| Refresh the stale cached rows (over 30 days) | 147 | 147 | 12 min | needed once per 10-K season |
| Everything | 359 + 212 | 571 | about 48 min, about 2.3 GB | store compact only |

Staying clear of the lockout: one sequential process, at most 1 request every 2-5 s (SEC's limit is 10 a second), the contact User-Agent already in `.env`, stop on the first
429/403 and write a persistent "paused until" stamp (back off at least 15 minutes), a per-night cap (about 40 tickers: tier 1 in 3 nights), no concurrency with page-view fetches
(they share the IP). **Cheaper alternative, untested:** SEC's `frames` API returns one concept for **all** filers for one period, so about 15 tags x 5 years of annual frames
plus instants is roughly 100-150 requests for the whole universe, versus 582 whole-company downloads. Caveats: calendar alignment of non-December fiscal years (the response
carries `end` dates, so alignment is checkable), one value per CIK, and no trial has been made (no network this round). The bulk `companyfacts.zip` lives on `www.sec.gov`, which is
blocked for this IP.

## 7. Risks, spec conflicts, open decisions

**Conflicts and inconsistencies.**
1. The SEC path is documented as "on-demand only, never in bulk" (`step5_data.py`, `financials_data.py`, OPS_RUNBOOK 2026-08-16); a standing job needs an explicit carve-out
   and its own limiter, and `tests/test_nightly_fundamentals_fetch.py` pins `allow_sec_cross_check=False` for the nightly job.
2. OPS_RUNBOOK says a generic any-cell SEC lookup was not built because the tag research does not generalise. This study supports that: about half of revenue cells, 58% of debt
   cells and 39% of matched interest cells need more than the first tag.
3. `sec_company_facts` is mapped to the `fundamentals` data group (`core/data_groups.py:370`): the FMP master switch would pause an SEC job, and a restricted request variant
   is irrelevant to it.
4. CLAUDE.md: FMP is the sole fundamentals source, SEC only a cross-check; "auto-prefer SEC" contradicts it.
5. `docs/specs/stuck-check.md` still describes GM as financing receivables in operating cash flow (already reported); the exemption list there is for a different job than
   data defects.
6. 798 MB of whole-company JSON is 57% of the database and of every backup; storing a projection instead is a storage decision the current design never made.
7. A defect can survive a refetch: the annual row is fresh until the next earnings date plus 2 days, and whether FMP corrects the capex line on a Refresh is unknown (not tested; it needs FMP calls).
8. The statement cleaner and recheck cover structure, not content; a plausible-looking row with a missing line (capex 0 beside quarterly capex, SBC 0) passes both.

**Decisions for you.**
1. Build (a), (b), (c) or (d)? If (a), the reduced form above?
2. Alert only on breaks and zero gaps, or also on persistent definition differences (159 undecoded cells)?
3. Mismatch policy: surface only, an override table, or a verified whitelist for SEC-preferred values?
4. Ship the three cache-only prefilters first (no SEC budget)?
5. Store a compact projection and stop keeping the 4 MB blobs (and prune the existing 798 MB)?
6. SEC budget: approve tier 1 (119 requests) now? Pace and per-night cap? Trial the `frames` API (about 10 requests) before any per-company sweep?
7. A separate data group or switch for SEC, instead of riding on `fundamentals`?
8. Test whether a manual Refresh heals STX, CAT, GM, KKR (about 8 FMP calls)?
9. Extend the placeholder guard (or add one) for a newest annual row with capex 0 beside non-zero quarterly capex? That changes scores (MU, CSCO, SYY, STX) and needs a recompute.
10. The stuck-check SBC rule for 1-2 zero years in the 5-year window (now OK on a partial sum): treat as Not reported?
11. Non-10-K filers (16 tickers; 52 of the 582 are non-US or non-USD by profile, 25 of them Pass-family, most of those still 10-K filers): accept "not covered", or use FMP's as-reported rows (one FMP call each)?
