# FMP Starter downgrade: impact investigation (2026-10-02)

Report only. No code, DB, cron or setting was changed, and **no FMP call was made** (nothing essential could be settled by a live call
on an Ultimate key). Sources: `CLAUDE.md`, `docs/specs/*`, `docs/fmp-pacing-300pm-investigation-2026-10-02.md`, `docs/decisions.md`,
the code, read-only queries against `backend/fathom.db`, `backend/logs/*` (including rotated `.gz`), and `git log`/`git show`.

**Plan facts used as given (not verified by the app):** Starter = 300 calls/min, 20 GB bandwidth per rolling 30 days, **no quarterly
financial statements**, annual statements "up to 5 years" on FMP's site, all intraday intervals except 1-minute with 5 years of history,
earnings/dividend/split **calendars** 1 year of history, S&P 500 / Nasdaq / Dow constituents need Premium. Premium = 750/min, 50 GB,
all intraday, 30 years of history, 5-year calendars. Anything else about tiers is marked **unverified**.

## Summary

1. **As the code stands, Fathom does not work acceptably on Starter if `period=quarter` is refused.** Three separate things break, in this order of seriousness:
   - **Step 5 (Debt) returns `insufficient_data` for every Standard and REIT stock**, because its whole input is the latest quarterly
     balance sheet with no annual fallback. `compute_overall_assessment` treats a step with no score as *incomplete*, so the **Overall
     Assessment score becomes empty for essentially every stock** (Screener, Watchlist, header chip). This is a break, not a degradation.
   - **A 402 on `period=quarter` switches off the whole `fundamentals` group automatically** (no manual toggle), including annual refreshes,
     `/earnings`, the forex rate and the nightly fundamentals fetch. The weekly re-probe clears it (it probes annual, which works) and the next
     quarterly call re-marks it, so it **flaps weekly**. The nightly job keeps reporting success while it refreshes nothing.
   - **Steps 1, 4, 3 and the header lose their TTM columns/values** and fall back to annual-only; Step 1 and Step 4 degrade without erroring.
2. **Cache safety is weak.** Statement cache rows are overwritten wholesale on every refresh (`core/cache.py:33`). If Starter *clamps* `limit=10` to 5 rows
   instead of refusing, every ticker's 10-year annual history (542 of 592 tickers hold 10 rows today) is silently replaced with 5 within about one earnings cycle.
   Nothing merges, nothing refuses a shorter answer. A *refusal* (402) is cache-safe (no write on an exception). Corporate events are upsert-only and safe.
3. **Constituent lists freeze, 10-year price history freezes**, and the group tiers that are recorded above Starter (`index_membership` Premium,
   `daily_prices_long` Premium, `institutional_ownership` Ultimate) go "Not on plan" the moment the plan setting is changed. There is no code fallback for the constituents
   (the Wikipedia scrapers were deleted 2026-09-15).
4. **What survives untouched:** daily bars (the nightly window is exactly 5 years), Weinstein, Liquidity Zones, Heatmap, Breadth, Momentum, Warren/BB+RSI
   (1-hour bars only, 730-day window), profile/quote, Step 2 (analyst estimates, annual), segmentation (already annual-only), the Chart tab's daily ranges.
5. **Bandwidth is not the problem.** Estimated 0.8-1.1 GB per 30 days (1.3-2.1 GB with corporate events re-enabled) against 20 GB: comfortable, medium-low confidence
   (nothing in the app measures bytes).
6. **The repo's own history does not settle which plan Fathom started on, and it contradicts today's Starter description** (section 3): the key served quarterly statements,
   10 years of annual statements and 28 years of daily bars from 2026-07-18, but returned 402 on constituents, all intraday intervals, and (per a code comment) quarterly
   key-metrics, quarterly ratios and quarterly segmentation until mid-September. Do not read that history as a prediction of what Starter will serve.

The smallest changes that make Starter workable are listed in section 8 (about 3-5 days total for a feature-complete Starter, most of it the Step 5 fallback).
Nothing here recommends a plan.

## 0. What the pacing report already settled (not repeated)

`docs/fmp-pacing-300pm-investigation-2026-10-02.md` covers call rates: flipping the plan setting alone drops the four `_Pacer` users to 150/min, the
sequential jobs run at about 60/min, interactive traffic is unpaced, and a cross-process limiter is proposed (not built). Its Section 4 already flagged the quarterly-statement
risk and the group tiers; this report adds the code-level trace, the cache evidence and the bandwidth estimate.

## 1. Quarterly data usage

All quarterly requests go through `fmp_client.get_income_statement / get_cash_flow_statement / get_balance_sheet_statement(ticker, "quarter", 12)`
(`TOTAL_QUARTERS_NEEDED = 4 + 8`, `helpers/ttm.py:19`), plus `get_enterprise_values(..., "quarter", 1)` and
`get_financial_statement_full_as_reported(..., "quarter", 1)`. Cache keys: `income_statement`/`quarterly`, `cash_flow_statement`/`quarterly`,
`balance_sheet_statement`/`quarterly`, `enterprise_values`/`quarter`, `financial_statement_full_as_reported`/`quarterly`. All map to group `fundamentals`.
The TTM endpoints (`/key-metrics-ttm`, `/ratios-ttm`) are **not** `period=quarter` calls and are listed separately.

### 1a. Every call site

| Where | Request | Used for |
|---|---|---|
| `data/step1_data.py:114,140` | income Q, cash flow Q (limit 12) | TTM revenue, net interest income, gross profit, operating income, net income, CFO, capex (Step 1 TTM point) |
| `data/step4_data.py:569,601,660` | income Q, balance sheet Q, cash flow Q | TTM revenue/NI/COGS/OCF/buybacks; **latest-quarter balance snapshot** as the "TTM" equity, AR, inventory, AP, debt, assets |
| `data/step5_data.py:201,382,395` | balance sheet Q, income Q, cash flow Q | **Step 5's entire input**: latest-quarter balance sheet row; TTM EBITDA, interest, EBIT, CFO, FCF |
| `data/step5_data.py:223-252` | as-reported Q + annual (Banks only, 37 cached tickers) | NPL ratio (annual fallback already exists inside) |
| `data/step3_data.py:248,274,291` | income Q, cash flow Q, balance sheet Q | Valuation: TTM CFO/NI/FCF/capex (current value), net debt, cash, shares, TTM-duplicates-last-FY check |
| `data/ticker_summary.py:204,216,235` | balance sheet Q, income Q, enterprise values Q (limit 1) | header: debt, EBITDA TTM, interest TTM, shares fallback, reported currency (for P/E), enterprise value, outlier flags |
| `data/ratios_data.py:263` | balance sheet Q | only the date in the "TTM (date)" column label |
| `data/financials_data.py:434,460,498` | income Q, cash flow Q, balance sheet Q | Financials tab: 12-quarter tables and the TTM column |
| `data/speculative_growth_data.py:79,94` | cash flow Q, balance sheet Q | last-2-quarter CFO direction, cash for runway |
| `pipeline/nightly_fundamentals_fetch.py` | calls get_step1/2/4/5, segmentation, summary, score | the nightly refresh of all of the above |
| `pipeline/nightly_score_recompute.py` | `cache_only=True` everywhere | reads whatever quarterly rows are cached; zero FMP calls |

Quarterly payloads are loaded together with annual in the same functions through `safe_fetch`, so a refusal (402/HTTP error) becomes `{}`, then `[]`, with only a log warning.

### 1b. What each dependent output shows with annual data only

(Read from code; none of this was run with quarterly data removed.)

| Output | Quarterly input | With annual only | Substitute in code / possible |
|---|---|---|---|
| **Step 1** series and score | TTM column via `sum_last_four_quarters` | The TTM point is `None` and is filtered out before scoring (`[v for v in ... if v is not None]`); the table shows an empty "TTM" column. Score is on annual points only, up to 12 months staler than today | Annual series is already the base. A "latest FY" TTM stand-in is a few lines in `helpers/ttm.py` |
| **Step 2** (growth) | none | **Unchanged.** `/analyst-estimates` annual limit 10; tier of that endpoint unrecorded | n/a |
| **Step 4** ROE/ROIC | TTM from `/key-metrics-ttm` (not quarterly) | Survives **if `/key-metrics-ttm` is on plan** (tier not recorded anywhere) | already used |
| **Step 4** revenue, NI, COGS, OCF, buybacks TTM; equity, AR, inventory, AP, debt snapshots | quarterly | `None`; `_clean_aligned` drops those points; CCC, AR-vs-revenue and ROE score on 10 annual years. `len(roe_clean) < 2` still passes | `key-metrics-ttm` also carries `cashConversionCycleTTM`, `daysOfSalesOutstandingTTM`, `workingCapitalTTM` (fields confirmed in the cache; tier unknown) |
| **Step 5** Standard and REIT | latest quarterly balance sheet row; TTM EBITDA/interest/CFO/FCF | `balance_sheet_row = {}`, so `current_ratio is None` and `debt_to_ebitda_data_missing` -> **`verdict="insufficient_data"`, `score=None`** (`step5_data.py:548`; REIT branch `total_debt is None` -> same, `:476`). Overall Assessment `incomplete` | **None in the Step 5 path.** The annual balance sheet and annual income (EBITDA) are already fetched *after* the bail-out for trend inputs, so an annual fallback is a contained change. `ratios-ttm` has `currentRatioTTM`, `interestCoverageRatioTTM`, `debtServiceCoverageRatioTTM`; `key-metrics-ttm` has `currentRatioTTM`, `netDebtToEBITDATTM` (net, not gross, debt: a methodology change) |
| **Step 5** Bank | same + as-reported quarterly | Same dependency on the quarterly balance sheet for the headline ratio; NPL has an annual fallback. Not traced to the final verdict | partial |
| **Step 5** Insurance, ETF | none | `not_supported`, unaffected | n/a |
| **Overall Assessment** | Step 5 | `can_compute = len(incomplete) == 0` (`scoring/overall.py:129`): **no score** for any ticker whose Step 5 is `insufficient_data`. A present Moat does not rescue it (documented in the function) | needs the Step 5 fallback |
| **Step 3 Valuation** | TTM CFO/NI/FCF/capex; latest balance sheet (debt, cash); shares | Current value inputs `None`; net debt/cash `None`. `select_method` and the equity bridge were **not traced to a final verdict**; expect `insufficient_data`/PASS for most tickers. Smoothed annual variants exist (`net_income_smoothed`, `cfo_smoothed`) but the auto tree picks the TTM sources | `trailing_smoothed_average` on annual data |
| **Header tiles** | debt, EBITDA TTM, interest TTM, EV | Blank. P/E is unaffected (`/ratios-ttm` + last close). Market cap is from the quote. EV needs `/enterprise-values` (quarter, tier unknown) | `ratios-ttm.enterpriseValueTTM`, `key-metrics-ttm.enterpriseValueTTM` exist |
| **Financials tab** | 12-quarter tables, TTM column | Quarterly tables padded with "—", TTM column blank; annual tables unaffected (`_trim_and_pad`) | none |
| **Ratios tab** | TTM column from `/key-metrics-ttm` + `/ratios-ttm`; quarterly BS only for the date label | TTM values survive if those endpoints are on plan; label reads "TTM" without a date | already TTM endpoints |
| **Speculative Growth** | last-2-quarter CFO direction, latest cash | `cfo_recent_direction=None`, `cash_runway_years=None`, trailing growth `None` (TTM revenue is the missing term) | annual only |
| **Screener / Watchlist fields** | from the above through `compute_ticker_score` | overall score/verdict, Step 5 score, step-4/1 values shift as above; stage/signals unaffected | n/a |
| **Nightly fundamentals fetch** | all of the above | see section 2: the group is marked restricted on the first ticker | n/a |
| **Score recompute** (3:25) | cache only | keeps scoring from the cached quarterly rows; they simply stop updating | n/a |

**Tier of the possible substitutes:** `/key-metrics-ttm` and `/ratios-ttm` are in group `fundamentals` (recorded Starter for the whole group, see section 6). No per-endpoint tier is recorded
or verified, and no log shows either returning 402 for a normal symbol. They are already fetched for 587-592 tickers and drive the P/E, ROE/ROIC TTM and the Ratios TTM column,
so **if they are not on Starter, those outputs go blank too** (and, by the canary rule below, kill the group).

## 2. 402 and canary behavior

### 2a. The mechanism (code: `clients/fmp_client.py`, `core/data_groups.py`)

1. `FMPClient.get` (`fmp_client.py:132`): maps endpoint -> group, refuses with `FMPGroupDisabledError` **before any network call** if `effective_state(group)` is not live.
2. Live -> `_send`. On HTTP 402 it calls `_handle_plan_restriction` (`:191`), then `raise_for_status()`.
3. `_handle_plan_restriction`: builds a canary with `_canary_params` (`:61`) = **the same params with only the symbol swapped for AAPL** (SPY for `/etf/info`), sends it, and if that **also returns 402**
   calls `mark_restricted(group, ...)`. If the failing symbol is AAPL itself, the failing call is its own canary.
4. `effective_state_from` (`data_groups.py:384`): live only if master on AND group enabled AND `required_tier <= fmp_plan` AND `status != plan_restricted`.
5. Cache layer (`core/cache.py`): `get_or_fetch`, `get_or_fetch_earnings_aware`, `force_fetch` check `statement_type_live` and serve the stale row cache-only when the group is not live.
6. Clearing: weekly `stale_data_health_check` (Sunday 12:30) and any Settings plan edit call `reprobe_restricted_groups`, which sends **`PROBE_ENDPOINTS[group]`**; for `fundamentals` that is
   `/income-statement?symbol=AAPL&period=annual&limit=1` (`data_groups.py:209`). A 200 clears the restriction. There is **no manual toggle**: `can_toggle` is false while restricted or above plan.

### 2b. Answers

- **Would a 402 on `period=quarter` disable the whole fundamentals group?** Yes, automatically. The canary replays `period=quarter&limit=12` for AAPL, which also 402s, so
  `mark_restricted("fundamentals")` is written. The group is the unit: annual statements, ratios, key-metrics, growth, EV, as-reported, analyst-estimates, `/earnings`
  (the staleness lookups) and the forex `/quote` (via the explicit `group="fundamentals"`) all go cache-only. Cost of the discovery: 2 calls.
- **Design gap that makes this worse:** the canary cannot tell a symbol-scoped 402 from a *parameter-scoped* one (`period=quarter`, or `limit=10` if Starter refuses it), because it replays the failing
  call's parameters. Any parameter-scoped refusal therefore reads as "the whole group is restricted".
- **Flapping.** Restricted Sunday-to-Sunday except that the weekly probe (annual, limit 1) succeeds and clears it. Next quarterly call (a page view or the 2:00 AM job's first ticker) re-marks it. Net: the
  group is mostly restricted, never reliably live.
- **The nightly job hides it.** `job_skip_reason("fundamentals")` is checked once, at start (`nightly_fundamentals_fetch.py:150`). If the group is live at 2:00 AM, the first ticker's
  quarterly call marks it restricted and every later ticker is served from cache with **no exception** (`safe_fetch` swallows). The run records `N refreshed, 0 failed, ~6 FMP calls` and status **success**.
  Only the *next* night is recorded as `skipped`, if the group is still restricted then (it is cleared every Sunday).
- **Param variant:** if Starter instead *clamps* `limit` silently, there is no 402 at all and the risk moves to cache safety (section 3). If it returns 402 for `limit` above its cap, the same
  group-wide marking happens on the first annual call.
- **Observed history:** no log or doc shows a group-wide 402 on this key. Every 402 in the retained logs (about 2,600 lines; the rotated archives overlap) is symbol-scoped (`BRK.B`, `BF.B`, `0941.HK`; the two classes of dotted symbol fail on every
  statement endpoint, annual and quarterly). The 402 path is only tested against simulated responses (`tests/test_fmp_plan_detection.py`, `OPS_RUNBOOK.md:66`).

### 2c. How it shows up

| Surface | What the owner sees |
|---|---|
| Settings > FMP data groups | chip **"Restricted by FMP"** (restricted) or **"Not on plan"** (above plan) with `reasonText`; the Switch is disabled (`can_toggle=false`) |
| Ticker tabs | `GroupOffBadge`: "Fundamentals: not refreshing, as of <last_success_at>" on Summary, Financials, Ratios, Analysis, Valuation (`frontend/lib/dataGroups.ts` `TAB_GROUPS`) |
| Scheduled Jobs | a job whose group is off *at start* records a real `skipped` status (neutral "Skipped" pill, `skipped_since`); a job that loses the group *mid-run* (fundamentals, above) stays green. Jobs that use `job_skip_reason`: trend, LZ, heatmap, breadth, last-close (`daily_prices`); BB+RSI, Warren (`intraday_bars`); fundamentals; price-target (`analyst_ratings`); corporate events; the index list refreshes (`index_membership`) |
| `POST /refresh` | 503 if any group it would clear or re-fetch through is not live (`pipeline/refresh.py:15`) |
| Header/tiles | quote and profile unaffected (`profile_quote`); fundamentals-derived tiles keep their last cached values |

### 2d. The recorded tier: gate, not display

`DataGroupSetting.required_tier` **gates calls**: `effective_state_from` returns `above_plan` when `required_tier > fmp_plan`, so `FMPClient.get`, the cache gate, `job_skip_reason`,
the bar sources and the long-history store all refuse before any network call. An above-plan group is **never probed**, so a wrong recorded tier can only be discovered by editing it. A group recorded
*too low* is discovered by a real 402 plus a confirming canary. The plan value also sets the pacing of four `_Pacer` users (`FMP_PLAN_REQUESTS_PER_MIN`, pacing report). The Settings tier Select is editable, so an owner who
believes a group is on Starter can lower the recorded tier and the group goes live again.

**Setting the plan to Starter today would, in the DB as it stands:** `index_membership` (Premium), `daily_prices_long` (Premium) and `institutional_ownership` (Ultimate, shelved) become `above_plan`.
`intraday_bars` stays live (recorded Starter), `fundamentals` stays live (recorded Starter, discovered only at the first 402).

## 3. Cache safety

### 3a. How rows are written

| Store | Write rule | Does a shorter response overwrite longer history? |
|---|---|---|
| `FundamentalsCache` statements, ratios, key-metrics, growth, estimates, segmentation (`core/cache.py:33`, `get_or_fetch*`, `force_fetch`) | `INSERT ... ON CONFLICT DO UPDATE SET raw_json, fetched_at`: the whole payload is replaced. No row-count, no date, no merge check | **Yes, unconditionally.** A 5-row answer replaces a 10-row row. An empty `[]` replaces it too (only an exception skips the write) |
| Refresh triggers | earnings-aware staleness: after each ticker's next earnings date + 2 days; flat 7 days without an earnings signal. Every ticker therefore refreshes within roughly one quarter | the overwrite would reach all 592 tickers within about 90 days; a cold-cache rebuild or the Refresh button does it at once |
| `SharedBarsCache` "1d" (`clients/shared_bars_cache.py:265`, `daily_bar_sources.py`) | upsert per bar. **Replace** (delete the ticker's rows then insert) on: weekly Sunday full resync, a >0.5% overlap mismatch, a window the cache does not cover, a young listing. Guard: a "full" answer under 20 bars never replaces (`FMP_MIN_FULL_BARS`) | Yes for any answer of 20+ bars. The request window is `today - 1825 d` and retention is 6 years, so a 5-year cap loses at most the ~1 year beyond 5y that **no consumer reads** (LZ 4y, Weinstein 5y, others 2y) |
| `SharedBarsCache` "60m" | same pattern, 730-day window, 20-bar guard | 730 days is far inside a 5-year intraday limit; no loss |
| `LongHistoryBars` (10 years, 51 tickers, 119,146 rows) | cold: full fetch + replace; warm: top-up (no replace) unless a restatement mismatch forces a full refetch + replace (`clients/long_history_bars.py:160-205`). no minimum-bars guard exists in this store | Group is `above_plan` on Starter so it is **frozen, not overwritten**. If the owner lowers its recorded tier and Starter serves 5 years, a restatement replace would shrink a ticker to 5y |
| `CorporateEvent` (`data/corporate_events_data.py:117`) | **upsert only** ("a stored row never removed because FMP's response omitted it", regression test `test_a_narrower_second_response_never_deletes_cached_rows`); incoming rows older than the cutoff are not stored | **No.** The 4-year retention prune (`prune_old_events`, `RETENTION_DAYS = 365*4`) deletes by *event date* only (> 4 years old), which is the Chart's longest view, so it removes nothing that could not already be shown. It does not delete anything FMP's 1-year window would have prevented refetching (all events 1-4 years old stay) |
| `IndexConstituent` | delete-then-insert with sanity floors (480 S&P / 28 Dow) | a skipped refresh leaves the list untouched; a short list is refused by the floors |
| `TrendAnalysis`, `TickerScore`, signal tables | derived; recomputed from the above | indirectly affected |

**Net:** a **402 is cache-safe** (exception before the write). A **silent clamp is not**, for the statement/ratio caches. Daily bars and corporate events are safe in practice.
`backup_db` keeps 7 daily + 4 weekly gzips (about 153 MB each, `backend/backups/`), so a pre-downgrade snapshot would need to be copied aside to survive a silent overwrite that goes
unnoticed for more than a week (disk is 92% used, 2.0 GB free).

### 3b. What the cache holds today (read-only queries, 2026-10-02)

**Annual statements (rows per ticker, 592 tickers):**

| Cache key | 10 rows | 5-9 rows | 1-4 rows | 0 rows |
|---|---|---|---|---|
| `income_statement` annual | 542 | 35 | 8 | 7 |
| `balance_sheet_statement` annual | 537 | 39 | 9 | 7 |
| `cash_flow_statement` annual | 542 | 35 | 8 | 7 |
| `key_metrics` annual | 540 | 37 | 8 | 2 |
| `ratios` annual_10y | 542 | 35 | 8 | 7 |

Oldest fiscal year in the 10-row rows: 2016 (451 tickers) or 2017 (96). The shorter rows are consistent with listing age (their oldest years are 2018-2025), not with a plan cap.
Samples (income annual): AAPL 10 rows, 2016-09-24 to 2025-09-27; MSFT 10, 2017-06-30 to 2026-06-30; JPM 10, 2016-12-31 to 2025-12-31; KO 10, 2016-12-31 to 2025-12-31; NVDA 10, 2017-01-29 to 2026-01-25.
Revenue segmentation is deeper still (AAPL 16 rows from 2010, MSFT 17 from 2010).

**Quarterly statements:** 12 rows for 577 of 592 tickers, oldest 2023-09-30 (AAPL, MSFT, JPM), newest 2026-06/07.

**Daily bars (`SharedBarsCache` "1d"):** 603 tickers, 743,677 rows, **5.01 years for essentially every ticker** (AAPL, MSFT, JPM, SPY, XLK, KO all 1,259 bars, 2021-09-27 to 2026-10-01); the shortest is a 0.3-year new listing.
**60m:** 108 tickers, 381,731 rows, median span 742 days (2024-09-19 to 2026-10-01); 10,232 legacy rows without provenance.
**`LongHistoryBars`:** 51 tickers, median span 10.0 years (AAPL/MSFT/KO 2,513-2,517 bars from 2016-09-26).
**Corporate events:** earnings 9,775 rows / 580 tickers, dividends 6,812 / 441, splits 62 / 52; oldest event 2022-10-02, i.e. the 4-year cutoff.
**Legacy research cache:** `historical_price_eod`/`full_history_chunked`, 50 tickers fetched 2026-08-02, e.g. AMZN 7,348 daily rows from 1997-12-31, GOOGL 5,522 from 2005, MA 5,077 from 2009 (unwired `analysis/ma_magnet`).

### 3c. Which plan was Fathom on when 10 years of annual data was first fetched?

Evidence from git and logs (the plan name is **not recorded anywhere in the repo**):

| Date | Evidence | Implies for that plan |
|---|---|---|
| 2026-07-18 (first Step 1 commit `ef4fd29`) | requests `income-statement`/`cash-flow-statement` annual **limit=10** and quarter limit=4 from day one; earliest cache rows 2026-07-18 21:11 | 10 years of annual statements **and** quarterly statements served |
| 2026-07-20 (`fc33295`) | "FMP's own endpoint [sp500-constituent] is 402 Restricted on our plan" | constituents not on that plan |
| 2026-07-20 (`bulk_refresh_step4_annual.log`) | 1,032 requests at `limit=10`, 1,026 `200`s, 2 `402`s (BRK.B, BF.B) | limit=10 not refused |
| 2026-07-22 (`bulk_refresh_balance_sheet_quarterly.log`) | 518 `period=quarter&limit=12` balance-sheet calls, all 200 | quarterly statements served |
| 2026-07-26 (comment in `data/ratios_data.py:261`) | "can't fetch quarterly key-metrics/ratios directly (402 on our FMP plan)" | quarterly key-metrics/ratios refused (no retained log line) |
| 2026-07-26 (comment in `data/segmentation_data.py:12`) | "period=quarter 402s on both segmentation endpoints, confirmed empirically" | quarterly segmentation refused |
| 2026-08-02 (`full_history_chunked` cache) | 4-year chunked daily requests returned bars back to 1997 | **28 years** of daily EOD served |
| 2026-08-05 log | 563 income annual, 505 income/cash-flow quarter, 499 balance sheet quarter, 987 enterprise-values quarter, all 200 | quarterly statements and quarterly EV served for ~500 tickers |
| 2026-09-09 | all six intraday intervals returned 402 (`9ad2621`) | no intraday at all |
| 2026-09-15 (`8d3bd19`) | constituents now 200 ("FMP Ultimate serves them (previously 402)") | upgrade |
| 2026-09-24 (`9ad2621`) | all ~110 probed endpoints 200; 600-request burst at about 2,455/min with no 429 | key behaves like Ultimate |
| 2026-09-30 | `DataGroupGlobal.fmp_plan` last edited, value `Ultimate` | |

**What this suggests:** the key that was in use from 2026-07-18 to about 2026-09-15 had 10-year annual and quarterly statements and 28 years of daily bars, but no constituents, no intraday and no quarterly
key-metrics/ratios/segmentation. That is **not** a plan with "5-year annual, no quarterly statements, intraday allowed". Two readings, and the repo cannot choose between them: (a) the earlier
"Starter" was a legacy plan with different entitlements than FMP's current Starter (FMP restructured plans; the quarterly-statements and intraday differences point this way), or (b) FMP did not enforce the documented history caps
on that key. Either way **the old behavior is not a safe prediction of today's Starter**, and the site statement of a 5-year cap is neither confirmed nor refuted for annual statements by the 10-year cache.

## 4. History-depth needs

Annual statements: Step 1, Step 4, Ratios, Financials and Step 3's P/B lookback all request **10 years** (`ANNUAL_WINDOW = 10`). Daily/intraday bars: nothing nightly asks for more than 5 years.

| Feature | Depth needed | If history is capped at 5 years |
|---|---|---|
| Step 1 trend windows (`docs/specs/financials.md`: "10yr+TTM") | up to 10 annual + TTM | classifiers still run on 5 points; recovery/dip rules ("durable" needs >= 4 old periods) have less to work with; scores shift (the spec records the 5 -> 10 change as deliberate) |
| Step 4 ROE, ROIC, CCC, AR (`profitability.md`: "10yr+TTM", "a ticker's score reflects its full 10-year history") | 10 annual + TTM | reverts to the original 5-year behavior; older bad years stop dragging scores; some scores rise |
| Step 5 trend inputs (5yr trend, `debt.md`) | 5 | fine |
| Step 3 Valuation: 5-yr smoothing, P/B `pb_lookback` ("10 years" if >= 10 years of P/B else "5 years") | 5 / 10 | smoothing fine; P/B falls to the 5-year lookback for every ticker |
| Step 2 | 10 estimate rows (forward) | unaffected (future years) |
| Chart W/4Y weekly | about 7.9 years of daily bars (4y visible + weekly SMA200 warm-up) | `daily_prices_long` is Premium: frozen for 51 cached tickers, **empty chart for any other ticker** (no row, no fallback). With only 5y of dailies the weekly SMA200 would exist for roughly the last 60 weeks |
| Chart weekly Stage overlay | up to 10y of weekly history to seed the sticky machine | seeded from ~5y; the spec says the nightly job already replays only ~5y and the "since" date can differ rarely |
| Analyst Ratings 10-year price overlay | 10 years | frozen/empty for uncached tickers; `grades_historical` limit 120 (10 years of months) is a separate endpoint, tier unknown |
| Moat price chart (10-20 years, per the question) | **I found no such chart in the code or in `economic-moat.md`** (no price, bars or chart reference in `data/moat.py`); the only 10y price consumers are W_4Y and the Analyst overlay; a 20-year consumer exists only in the unwired `analysis/ma_magnet` research code | n/a |
| Weinstein engine (nightly) | `WEINSTEIN_LOOKBACK_DAYS = 365*5` | already 5 years (exactly Starter's cap) |
| Liquidity Zones | 4 years | fine |
| Momentum, Sector Heatmap, Market Breadth | 730 days (1y longest lookback) | fine |
| Kalman / `analysis/trend_structure` | no Kalman code in the app; `trend_structure` is the Weinstein engines and Stochastic only | n/a |
| D_6M, D_1Y, D_2Y chart ranges | 730 / 730 / 1,825 days, live | fine |
| 60m for Warren (730 d) and BB+RSI (60 d) | 2 years | fine vs a 5-year intraday limit |
| Corporate events backfill | 4 years of markers | cache holds 4y; a **new** ticker would only get what Starter's 1-year calendars return (**unverified** whether per-symbol `/earnings`, `/dividends`, `/splits` follow the calendar limit) |

**Edge:** the daily window is `today - 1825 d`, which is 1-2 days *inside* five calendar years, and the coverage check allows 10 days of slack, so an exact 5-year cap does not trigger daily full refetches. A cap slightly under five years (for example trading-day based) could make every ticker look "not covered" and refetch 5-year bodies nightly (about 590 x 0.22 MB = 128 MB/night); worth a verification question.

## 5. Intraday

- **Interval requested:** only `/historical-chart/1hour` (`FMPClient.get_historical_chart_1hour`, group `intraday_bars`). Warren (730-day request, `pipeline/nightly_warren_signal_calculation.py:64`) and BB+RSI (60-day request, then shared) both read the shared `"60m"` rows and build 2-hour candles from them. **No code path requests 1-minute, 5-minute, 15-minute, 30-minute or 4-hour bars**; 1-minute appears only in the unbuilt extended-hours (P5) feasibility notes.
- **5-year limit:** irrelevant to warm-up and validation. Warren replays 730 days with a 180-day write-side warm-up buffer; the cache holds a median 742 days; the 60m retention is 3 years and "the 60m history that can be fetched is about 730 days deep" by the code's own note.
- **Starter intraday tier, recorded in three places that disagree:**

| Where | Value |
|---|---|
| Live DB `datagroupsetting` (`intraday_bars`) | **Starter**, enabled, last success 2026-10-02 00:25 |
| Code seed `core/data_groups.py:107` (`GROUPS["intraday_bars"]`) | **Premium** ("P4 ... Off = cached-only"). The 2026-09-27 seed sync (`12138d4`) corrected five groups to match the DB and did not touch this one |
| `docs/specs/fmp-data-and-bar-cache.md:395` | **Premium, "seeded unverified"** |
| `docs/specs/warren-signal.md`, CLAUDE.md | do not state a tier |

Given the owner's fact (Starter has all intraday intervals except 1-minute), the DB value is the consistent one and the code seed and spec are stale. The 2026-09-24 investigation recorded "Premium? / Ultimate (1min)" as docs-only guesses.
Past 402s on this feature (all six intervals on 2026-09-09) were an account-level change, not a code issue.

## 6. Other tier-sensitive items and the data-group table

- **Index membership:** `refresh_sp500_list`, `refresh_nasdaq_list`, `refresh_dow_list` (Sunday 12:00/12:05/12:10 per `crontab.txt`) record `skipped` and leave `IndexConstituent` untouched (503 S&P, 102 Nasdaq-100, 30 Dow; last synced 2026-09-27). The weekly
  `/delisted-companies` sync (same group) also skips (`stale_data_health_check.py:207`): **no new delisted flags and no cleared flags**. The Wikipedia scrapers were removed in `8d3bd19` (recoverable from git; Wikipedia was reachable then, SEC's site was not).
- **Tracked-universe rule (a)** ("member of S&P 500, Nasdaq-100 or Dow") reads that table and **never expires**. Frozen list means: new index members are not added automatically (they enter only if viewed, watchlisted or manually rated, `tracked-universe.md` rules b/d/e), and removed members stay in the nightly universe forever. Of the 595 known tickers,
  518 are index members, 72 are tracked only through watchlist/manual/viewed. Today all 595 carry a recent `TickerView` (seeded on 2026-10-02 with 30 days of grace), so the 30-day expiry starts to bite on 2026-11-01. Market Breadth's universe is `IndexConstituent` "sp500" strictly, so its denominator freezes.
- **Corporate events job (disabled since 2026-10-01):** nothing changes by itself (markers already frozen). Re-enabling changes nothing about the call count (about 1,165 calls/night, about 6 min under a 192/min cap per the pacing report); a 1-year history would only shrink the bandwidth, and new tickers would get at most a year of markers.
- **ETF info:** recorded Starter (owner's value, seeded 2026-10-02, canary SPY). Unverified. The ETF page Overview and ETF watchlist columns read "unavailable" if refused; nothing else depends on it.
- **Profile, quote, price-change, search:** group `profile_quote`, recorded Starter, never returned a non-symbol-scoped 402. `/search-symbol`, `/search-name`, `/stock-price-change` are filed there although their own tier is unknown. Search is uncached and unpaced (pacing report).
- **Price target and grades:** `analyst_ratings` recorded Starter; `/price-target-*`, `/grades-*` tiers unrecorded. A refusal degrades to cached; the 3:10 AM snapshot job would classify symbol-agnostic 402s as failures past the 5% threshold (`check_failure_threshold`).
- **Never returned 402 on a normal symbol:** every enabled group above except `index_membership`, `intraday_bars` (before the upgrade) and `daily_prices_long` (never tested below Ultimate).
- **Not FMP:** `sec_company_facts` (SEC EDGAR, 792 MB in the cache) rides the `fundamentals` gate; it stops refreshing with it.
- **Also on Starter, pacing:** see the pacing report; the cross-process limiter is still unbuilt.

### Enabled data groups: recorded tier, users, effect on Starter

Recorded tier = live DB value (`datagroupsetting`, 2026-10-02). "Above plan" = `required_tier > Starter`, so refused before any call.

| Group | Recorded tier (DB / code seed) | Who uses it | Effect on Starter |
|---|---|---|---|
| `fundamentals` | Starter / Starter | Steps 1-5, Valuation, Ratios, Financials, header, Screener scores, nightly fetch, `/earnings` staleness, forex rate, SEC cross-check gate | **Breaks if `period=quarter` is refused** (sections 1-2). Annual and TTM endpoints unverified. Silent clamp of `limit` would shorten cached history |
| `profile_quote` | Starter / Starter | header, search, Refresh button, last close | works; per-endpoint tiers of search/price-change unverified |
| `analyst_ratings` | Starter / Starter | Analyst Ratings tab, Watchlist rating column, 3:10 AM price-target snapshot | likely works; per-endpoint tiers unverified; refusal = cached |
| `segmentation` | Starter / Starter | Segmentation card, nightly fetch | works (annual only already; history up to 17 rows cached) |
| `corporate_events` | Starter / Starter | Chart E/D markers (job disabled; cache frozen) | no change today; new tickers get at most the Starter history |
| `daily_prices` | Starter / Starter | Weinstein, LZ, Heatmap, Breadth, Momentum, Chart D ranges, last close, header volume tiles | **works**: nightly window is 5 years minus a day or two; the 6-year retention is never needed |
| `daily_prices_long` | **Premium** / Premium | Chart W_4Y, Analyst 10-year overlay | **above plan**: frozen for 51 cached tickers, empty for the rest |
| `intraday_bars` | Starter / **Premium** | Warren, BB+RSI, Chart signal markers | works if Starter includes 1hour (owner's fact); 730-day window; DB/seed/spec disagree (section 5) |
| `index_membership` | **Premium** / Premium | 3 weekly list refreshes, Screener universe, tracked-universe rule (a), Breadth universe, delisted sync | **above plan**: lists freeze, delisted sync stops, no code fallback |
| `etf_info` | Starter / Starter | ETF page Overview, ETF watchlist columns | unverified; failure = "unavailable" on ETF pages |
| `institutional_ownership` | **Ultimate** / Ultimate (enabled in DB, seeded off) | nothing (shelved, no tab) | above plan, no visible effect |
| `news` | Starter / Starter (enabled in DB, seeded off, never succeeded) | nothing (shelved) | none |
| (stale row) `insider` | Starter, disabled | nothing | none, harmless row |

## Feature dependency table (quarterly data and history depth)

| Feature | Quarterly | >5y history | State on Starter if only annual (<=5y) + no `period=quarter` |
|---|---|---|---|
| Step 1 Financials | TTM column | 10y annual window | **degrades** (annual-only, staler) |
| Step 2 Growth | no | no | **unchanged** |
| Step 3 Valuation | TTM CFO/NI/FCF, latest BS, shares | P/B 10y lookback | **breaks/degrades** (not traced to final verdict); P/B 5y |
| Step 4 Profitability | TTM + latest BS snapshot | 10y window | **degrades** (annual 10y/5y); ROE/ROIC TTM survive only if `key-metrics-ttm` is on plan |
| Step 5 Debt | entire input | 5y trend | **breaks**: `insufficient_data`, Overall Assessment empty |
| Overall Assessment / Screener score | via Step 5 | | **breaks** (no score for Standard/REIT stocks) |
| Header tiles | debt/EBITDA/interest/EV | | blank for those; P/E and price fine |
| Financials / Ratios tabs | quarterly tables, TTM column | 10y annual | quarterly blank; Ratios TTM depends on TTM endpoints |
| Speculative Growth | CFO direction, cash | | partial `None`s |
| Weinstein, LZ, Heatmap, Breadth, Momentum | no | <=5y | **unchanged** |
| Warren, BB+RSI | no | 2y intraday | **unchanged** (if Starter serves 1hour) |
| Chart D ranges | no | <=5y | unchanged |
| Chart W_4Y / Analyst 10y overlay | no | 10y | **freezes** (cached 51 tickers) / empty for others |
| Constituent lists, Screener universe, Breadth universe, delisted flags | no | | **freeze** (Premium) |
| Corporate events markers | no | 4y of markers | frozen now (job disabled); new tickers limited |
| Nightly fundamentals job | quarterly calls | 10y annual calls | group flips restricted on first ticker; reports success |

## 7. Bandwidth

**Method.** Per-call payload sizes from the cached JSON (`avg(length(raw_json))`, compact enough to be within about 10% of the wire size, uncompressed) times call counts from the pacing report (`httpx` log lines, last six nights). FMP's own accounting
(compressed or not, whether errors and empty responses count, whether the 30-day window is per key or per account) is **unknown**.

| Item | Payload | Calls | Per 30 days |
|---|---|---|---|
| Daily bars, Sunday full resync (586 x 5-year body, about 1,259 rows x 173 B = 0.22 MB) | 0.22 MB | 586 / week | **about 560 MB** (the largest single item; it is a belt-and-braces restatement check) |
| Daily bars, nightly incremental (trend job + last-close job, about 8 rows each) | 1-2 KB | about 1,170 / night | about 45 MB |
| Intraday 1hour: 105 incremental per night (about 25 rows x 110 B); occasional 730-day widening about 0.4 MB | 3 KB / 0.4 MB | 136-348 / night | 10-30 MB |
| Fundamentals: full per-ticker pull about 160 KB (income A/Q 26 KB, balance A/Q 40 KB, cash flow A/Q 33 KB, key-metrics 19 KB, ratios 32 KB, estimates, growth, EV, segmentation); each ticker refreshes about 4 times a year; plus weekly `earnings`, profile, price-change | 160 KB | 60-250 / night, 2,626 on a wave night | 40-60 MB on average (a 590-ticker full cycle is about 95 MB) |
| Price-target snapshot (consensus 0.1 KB, summary 0.3 KB) | 0.1-0.3 KB | about 590 / night | 2-5 MB |
| Delisted sync (157 pages x 100 rows) + index lists | about 18 KB / page | about 160 / week | about 12 MB |
| Interactive: a cold ticker open about 0.3-0.8 MB (fundamentals 160 KB, daily 90-220 KB per uncached Chart range, long history 0.45 MB the first time); warm opens are KB | | 18-35 cold calls | **100-400 MB** (lowest confidence: depends on how often the owner browses) |
| **Total, corporate events disabled (today)** | | | **about 0.8-1.1 GB** |
| Corporate events if re-enabled nightly (`/earnings` limit 1000 + `/dividends` limit 2000 per ticker, full history, no incremental) | about 30 KB / ticker | 1,165 / night | 15-35 MB per night, **0.45-1.0 GB** (pacing report: 20-35 MB/night) |
| **Total with corporate events** | | | **about 1.3-2.1 GB** |

**Verdict: comfortable.** Roughly 4-10% of 20 GB. **Confidence: medium on the order of magnitude (a factor of 2 either way), low on the interactive line.** The real risk is a runaway job, not steady state: a cold rebuild adds about 0.3 GB, and the unwired `ma_magnet`
research path pulls about 1.7 MB per ticker (about 1 GB for 590). The Sunday resync is the one line worth reducing if bandwidth ever matters (monthly instead of weekly would save about 420 MB/month).

**To measure it:** add `len(response.content)` (or `num_bytes_downloaded`) per request in `FMPClient._send`, and persist per day and per data group (calls, bytes, 402s, 429s) in a small table next to `DataGroupSetting` (about half a day; it fits the pacing report's `FmpUsageMinute` metrics table). Also check whether FMP's dashboard shows a usage meter, and compare it with the app's count for one week.

## 8. Verdict and options

### 8a. Verdict

| Class | Items |
|---|---|
| **Works as is** | daily bars and every consumer built on them (Weinstein, LZ, Heatmap, Breadth, Momentum, Chart D ranges, last close); Warren and BB+RSI (if 1hour is on Starter); profile/quote; Step 2; segmentation; corporate-event cache reads |
| **Degrades** | Step 1 and Step 4 (annual-only, up to 12 months staler, 5-year windows if capped); header debt/EBITDA/EV tiles blank; Financials quarterly tables blank; Speculative Growth partial; Ratios TTM date label |
| **Freezes** | constituent lists and everything keyed to them (Screener universe growth, delisted flags, breadth denominator); 10-year price history (W_4Y, Analyst overlay) for uncached tickers; corporate-event markers (already frozen) |
| **Breaks** | Step 5 for Standard and REIT stocks, therefore the Overall Assessment score and Screener ranking; Step 3 Valuation for most tickers; the `fundamentals` group flapping restricted and the nightly job reporting success while refreshing nothing |

**Fathom does not work acceptably on Starter in its current form if quarterly statements are refused.** If Starter *does* serve `period=quarter` and `limit=10` (the old key did), most of this reduces to the constituent
freeze and the long-history freeze.

### 8b. Smallest changes that make Starter workable

Sizes: S = under half a day, M = 1-2 days, L = more.

| # | Change | Fixes | Size | Risks / conflicts |
|---|---|---|---|---|
| 1 | **Never overwrite longer history.** In `_write_cache_row` and `force_fetch`, for list payloads keyed by `fiscalYear`/`date`: keep the existing rows not present in the new response and replace overlapping ones (merge, newest wins); refuse an empty `[]` over a non-empty row. In `_write_rows`/`_write` (bars): when the new frame starts more than about 30 days later than the cached first bar, upsert (`replace=False`) instead of delete-and-insert | silent 10 -> 5 year loss | **S-M** (about 1 day with tests) | a restated/removed old row is no longer dropped (rare; FMP corrections arrive on overlapping years and still replace). Touches the shared cache used by every statement; test per statement type. No spec conflict (`fmp-data-and-bar-cache.md` documents replace-on-restatement; that rule stays for the overlapping part) |
| 2 | **Make the restriction canary parameter-safe.** Probe the failing endpoint with its minimal parameters (annual, `limit=1`, and no `period=quarter`) and, in addition, record the failing *parameter profile* (endpoint + period + limit class) as restricted instead of the whole group. At minimum: do not mark the group when the minimal-parameter canary succeeds | one refused parameter taking down all of `fundamentals`; the weekly flap | **S** (canary change) to **M** (per-parameter restriction state in `DataGroupSetting` or a new table, UI chip "Quarterly refused") | `CLAUDE.md` "402 safety net" and `test_fmp_plan_detection.py` pin the current semantics; a new table needs `init_db`-time creation (SQLModel does not ALTER) |
| 3 | **Stop calling `period=quarter` when it is known refused** (a plan-derived or discovered capability flag), and cache the refusal for a day so page views do not repeat 402 + canary | wasted calls, log noise, flapping | **S** | none beyond item 2 |
| 4 | **Annual fallback for Step 5 (and TTM stand-ins for Steps 1/3/4/header).** Step 5: if the quarterly balance sheet is empty, use the latest annual balance sheet row and annual EBITDA/interest/CFO, labelled "FY" with the fiscal-year date; optionally prefer `ratios-ttm`/`key-metrics-ttm` for current ratio and interest coverage. Steps 1/3/4: a `sum_last_four_quarters`-style fallback to the last fiscal year when quarterly rows are absent | Step 5 `insufficient_data`, empty Overall | **M** (about 1.5-2 days incl. tests); the TTM-endpoint variant adds a methodology decision (net vs gross debt/EBITDA) | `docs/specs/debt.md` defines Debt/EBITDA and Current Ratio on latest-quarter and TTM bases, `financials.md`/`profitability.md` on "10yr+TTM": those specs need an "annual-only mode" section; Overall verdicts shift (staler inputs). A TTM-endpoint substitute is only valid if those endpoints are on Starter (**unverified**) |
| 5 | **Per-tier history clamps in the registry.** A `TIER_LIMITS` table (annual `limit`, daily/intraday years, calendar years) consulted by the client methods and by the bar/long-history windows, so a Starter plan asks for `limit=5` and 1-year calendars instead of probing 402 or clamping silently | param-scoped 402, silent clamp | **M** (about 1 day) | Steps 1/4 deliberately use 10 years (`profitability.md`): an owner decision whether to accept 5-year scoring on Starter. `test_data_groups_registry.py` must be extended |
| 6 | **Constituent-list fallback.** Restore the Wikipedia scrapers from `git show 8d3bd19^` (the S&P 500 / Dow / Nasdaq pipeline and fixtures), used only when `index_membership` is above plan or restricted; or hand-edit lists (about 20-25 S&P changes a year) | frozen universe and breadth denominator | **M** (restore + tests, about 1 day); **S** if the owner accepts a manual list | Wikipedia table layout can change (the original failure handling and sanity floors cover it); `tracked-universe.md`, CLAUDE.md "index_membership" text, `test_cron_wiring.py` job/group wiring |
| 7 | **Long-history fallback for W_4Y and the overlay** to the 5-year shared daily cache when `daily_prices_long` is off | empty W_4Y/overlay for new tickers | **S-M** | weekly SMA200 truncated to the last about 60 weeks, stage seeding shorter; `chart-tab.md` and `weinstein-stage.md` caveats |
| 8 | **Make the nightly fundamentals job notice a mid-run restriction** (re-check `job_skip_reason` every N tickers, record `skipped`/failure with a message) | green-but-empty run | **S** | pairs with `core/cron_health.py` message conventions |
| 9 | **Reconcile the `intraday_bars` tier** (code seed, `fmp-data-and-bar-cache.md:395`, DB) | three-way conflict | **S** (docs + one constant) | none |
| 10 | **Bandwidth meter** (section 7) | no measurement today | **S-M** | can share the limiter metrics from the pacing report |
| 11 | Pacing limiter (pacing report, Phase 2) | 300/min interactive overlap | **M** (1-1.5 days) | already specified; independent of tier |

A workable Starter that only freezes the constituent list and long history is items 1, 2, 3, 8, 9 (about 2 days); adding Step 5/TTM fallbacks (item 4) and the scorer decision (item 5) makes it feature-complete: **about 3-5 days total**.

### 8c. Premium for comparison

| Problem | On Premium (750/min, 50 GB, 30y history, 5-year calendars, constituents included) |
|---|---|
| `period=quarter` statements | **Verify.** The owner's fact says Starter lacks them; the old key had them. If Premium has them (likely, but not stated), no quarterly breakage |
| 10-year annual `limit=10` | Within 30 years of history; the cache keeps 10 |
| `index_membership` and `daily_prices_long` (recorded Premium) | live, no code change |
| `intraday_bars`, `corporate_events` calendars (5 years vs the 4-year retention) | live; 5-year calendars cover the 4-year chart window |
| `institutional_ownership` (Ultimate) | still above plan, shelved, no effect |
| Pacing | `_Pacer` users at 375/min (50% of 750); limiter proposal still applies at 600/min cap; the quarterly and constituents items vanish |
| Bandwidth | 50 GB cap vs 1-2 GB; no concern |

### 8d. What to verify with FMP before deciding (the app cannot check these)

1. Starter and Premium: `period=quarter` for `/income-statement`, `/balance-sheet-statement`, `/cash-flow-statement` (refused, or served?), and for `/key-metrics`, `/ratios`, `/enterprise-values`, `/financial-statement-full-as-reported`.
2. What Starter does to `limit=10`: refuses (402), silently returns 5 rows, or ignores the cap. Ask in writing; this decides whether item 1 (cache safety) or item 2 (canary) is the urgent change.
3. Tier of `/key-metrics-ttm`, `/ratios-ttm`, `/analyst-estimates`, `/financial-growth`, `/grades-*`, `/price-target-*`, `/stock-price-change`, `/search-*`, `/etf/info`, `/delisted-companies`.
4. History caps per endpoint on Starter: `/historical-price-eod/full` (calendar vs trading days; behavior on the 5-year edge), `/historical-chart/1hour` (confirm 1hour is included), per-symbol `/earnings`, `/dividends`, `/splits` (do they follow the 1-year calendar limit?).
5. Whether the constituent endpoints (`/sp500-constituent`, `/dowjones-constituent`, `/nasdaq-constituent`) are Premium for all three.
6. What bandwidth is metered (compressed or raw, errors, empty responses), what happens at 20 GB (429, 402, overage, throttle), and whether per-minute counting is rolling or calendar and whether 402/429 count.
7. When a plan change takes effect, whether the current key keeps working, and which plan name the pre-2026-09-15 key actually was (the repo cannot tell, and its behavior does not match the described Starter).
8. Whether FMP's terms allow keeping previously fetched data after a downgrade (the cache holds 10-year statements and 10-year bars that a Starter key could not refetch).

## Appendix: evidence queries and files

Read-only sqlite queries on `backend/fathom.db` (`mode=ro`): `datagroupsetting`/`datagroupglobal`; `fundamentalscache` grouped by `(statement_type, period)` and per-ticker row counts/min/max `date`; `sharedbarscache` span per ticker and
interval; `longhistorybars`; `corporateevent`/`corporateeventfetch`; `indexconstituent`, `tickerview`, watchlist/moat/valuation/bank-capital tables for the universe split. Logs: `backend/logs/bulk_refresh_*.log`,
`nightly_fundamentals_fetch*.log(.gz)` (402 lines by endpoint/symbol/period: every one symbol-scoped to BRK.B, BF.B, 0941.HK). Git: `ef4fd29`, `fc33295`, `8d3bd19`, `9ad2621`, `12138d4`, `36aa2ca`. Code: `clients/fmp_client.py`, `core/data_groups.py`,
`core/cache.py`, `clients/shared_bars_cache.py`, `clients/daily_bar_sources.py`, `clients/long_history_bars.py`, `data/corporate_events_data.py`, `data/step{1,3,4,5}_data.py`, `data/ticker_summary.py`, `data/ratios_data.py`, `data/financials_data.py`,
`scoring/overall.py`, `pipeline/nightly_fundamentals_fetch.py`, `pipeline/stale_data_health_check.py`, `data/tracked_universe.py`.
