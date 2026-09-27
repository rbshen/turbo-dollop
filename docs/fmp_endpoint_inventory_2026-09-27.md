# FMP endpoint inventory (2026-09-27)

Read-only static investigation at commit `d0fb62d`. No application code was changed.
Purpose: ground truth for a manual FMP plan-tier cross-check, ahead of any relayout of the
Settings > Status data-group toggles. **No relayout is proposed here.**

## How this was gathered

- Every FMP request goes through `FMPClient.get` (`backend/clients/fmp_client.py`), base URL
  `https://financialmodelingprep.com/stable` (`core/config.py::fmp_base_url`). A repo-wide search
  (`financialmodelingprep`, `httpx.`/`requests.`, `fmp_client.` / `_client.` / `client.get_*`, and
  the `docs/`, `bin/`, `backend/scripts/` trees) found **no FMP call that bypasses the client**.
  `bin/start.sh` (AAPL `/quote` preflight) imports the same singleton. `backend/scripts/` holds
  one file (`weinstein_4stage_simulation.py`) that makes no FMP call. Nothing under `docs/` calls
  FMP (they only describe it).
- The gate registry is `core/data_groups.py`: `ENDPOINT_GROUP` (endpoint -> group),
  `ENDPOINT_GROUP_OVERRIDES_USED` (endpoints reached by two groups via an explicit `group=`),
  `PROBE_ENDPOINTS` (canary per group), `STATEMENT_TYPE_GROUP` (cache-key gate).
- Group state below was read directly from the live `backend/fathom.db` (`datagroupsetting`,
  `datagroupglobal`), opened read-only.

**Totals: 35 distinct endpoint paths** (34 fully gated by a single group; `/quote`, `/earnings` and
`/historical-price-eod/full` are each reached by two groups). All 35 are mapped in `ENDPOINT_GROUP`;
none is ungated.

## Part 1 -- Data groups as they exist now

Master switch: **on**. "My FMP plan" (`datagroupglobal.fmp_plan`): **Ultimate**.
`Tier` / `Verified` are the **DB-recorded** values (user-edited). The code seed default
(`GROUPS` in `data_groups.py`) is shown where it differs, since the DB has diverged from the seeds.

| Group key | Label | Enabled | Tier (DB) | Verified (DB) | Code seed tier | Status | Last success | "Feeds" list (from `GROUPS`) |
|---|---|---|---|---|---|---|---|---|
| `fundamentals` | Fundamentals | on | Starter | yes | Premium | ok | 2026-09-26 | Analysis tab (Steps 1-5), Valuation, Screener scores, Watchlist scores, Nightly fundamentals fetch |
| `profile_quote` | Profile & quote | on | Starter | yes | Starter | ok | 2026-09-27 | Ticker header (price, change, market cap), Ticker search, Refresh button |
| `analyst_ratings` | Analyst ratings | on | Starter | yes | Premium | ok | 2026-09-27 | Analyst Ratings tab, Watchlist rating column, Nightly price-target snapshot |
| `segmentation` | Segmentation | on | Starter | **no** | Premium | ok | 2026-09-24 | Segmentation card |
| `news` | News | on | Starter | yes | Starter | ok | never | News tab |
| `insider` | Insider activity | **off** (shelved) | Starter | **no** | Premium | ok | never | Insider Activity tab (shelved) |
| `index_membership` | Index membership | on | Premium | yes | Starter | ok | never | S&P 500 / Dow / Nasdaq constituent lists, Screener universe, Weekly index refresh jobs |
| `corporate_events` | Corporate events | on | Premium | yes | Premium | ok | 2026-09-26 | Chart earnings/dividend markers, Earnings/dividends/splits cache, Delisted-ticker flags |
| `daily_prices` | Daily prices | on | Starter | yes | Premium | ok | 2026-09-27 | Trend / Weinstein, Liquidity Zones, Sector Heatmap, Market Breadth, Momentum, Chart tab (daily ranges), Header avg-volume / dollar-volume |
| `daily_prices_long` | Daily prices (long history) | on | Premium | yes | Premium | ok | 2026-09-26 | Chart tab (weekly 4y range), Analyst Ratings price overlay (10y) |
| `intraday_bars` | Intraday bars | on | Starter | yes | Premium | ok | 2026-09-26 | Warren RSI/ADX/WVF entry signal (2h), BB+RSI entry signal (2h), Chart tab entry-signal markers |
| `extended_hours` | Extended hours | on | Starter | yes | Premium | ok | never | (not wired yet -- P5). **`live=False` in code: no endpoint, client method, or call site exists.** |

**12 data-group rows** (11 wired to real calls + 1 seeded-but-unwired). `news` and `index_membership`
show "never" for last success in the DB even though the code calls them; see Part 3.

## Part 2 -- Endpoints, grouped by current data group

"Active" key: **Yes** = reachable in the running app or a scheduled cron. **Shelved / one-shot /
unwired** are called out explicitly. Cache-key names are the `FundamentalsCache.statement_type`.

### `fundamentals` (12 endpoints; `/quote` and `/earnings` each appear here only through an explicit override)

| Endpoint | Client method | Caller(s) (file::function context) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/analyst-estimates` | `get_analyst_estimates` | `data/step2_data.py` (`get_step2_data`) | Growth Rate (Step 2) forward CAGR; also Valuation's growth input | `fundamentals` | Yes |
| `/ratios` (annual, limit 1 / 10) | `get_ratios` | `data/step2_data.py`, `data/step3_data.py`, `data/ratios_data.py`, `data/ticker_summary.py`, `data/speculative_growth_data.py`; backfill `bulk_refresh_*` | Step 2 fallback, Valuation (P/B history), Ratios tab, header, Speculative Growth | `fundamentals` | Yes |
| `/ratios-ttm` | `get_ratios_ttm` | `data/ratios_data.py`, `data/ticker_summary.py`; backfill `pipeline/backfills/bulk_refresh_ratios_ttm.py` | Ratios tab, ticker header ratios | `fundamentals` | Yes (backfill is one-shot, already run) |
| `/key-metrics` (annual) | `get_key_metrics` | `data/step4_data.py`, `data/ratios_data.py`; backfill `bulk_refresh_step4_annual.py` | Profitability (Step 4) ROE/ROIC inputs, Ratios tab | `fundamentals` | Yes |
| `/key-metrics-ttm` | `get_key_metrics_ttm` | `data/step4_data.py`, `data/ratios_data.py` | Step 4 TTM, Ratios tab | `fundamentals` | Yes |
| `/income-statement` (annual + quarter) | `get_income_statement` | `data/step1_data.py`, `step3_data.py`, `step4_data.py`, `step5_data.py`, `financials_data.py`, `ticker_summary.py` | Financials, Valuation, Profitability, Debt, Financials tab, header | `fundamentals` (also the group's canary) | Yes |
| `/cash-flow-statement` (annual + quarter) | `get_cash_flow_statement` | `data/step1_data.py`, `step3_data.py`, `step4_data.py`, `step5_data.py`, `financials_data.py`, `speculative_growth_data.py` | Financials, Valuation, Profitability, Debt, Speculative Growth | `fundamentals` | Yes |
| `/balance-sheet-statement` (annual + quarter) | `get_balance_sheet_statement` | `data/step3_data.py`, `step4_data.py`, `step5_data.py`, `financials_data.py`, `ratios_data.py`, `ticker_summary.py`, `speculative_growth_data.py`; backfills | Valuation (book value, debt), Profitability, Debt, header | `fundamentals` | Yes |
| `/enterprise-values` (quarter, limit 1) | `get_enterprise_values` | `data/ticker_summary.py` | Ticker header (EV) | `fundamentals` | Yes |
| `/financial-growth` (annual, limit 1) | `get_financial_growth` | `data/ticker_summary.py` | Ticker header growth stats | `fundamentals` | Yes |
| `/financial-statement-full-as-reported` (quarter/annual, limit 1) | `get_financial_statement_full_as_reported` | `data/step5_data.py` (Bank path; NPL via `helpers/npl.py`, deposit checks) | Debt (Step 5) Bank NPL ratio | `fundamentals` | Yes (Bank-classified tickers only) |
| `/earnings` (limit 8) -- **override** `get_earnings` -> `fundamentals` | `get_earnings` | `data/ticker_summary.py`, `helpers/earnings.py` | Earnings-aware cache staleness (next/last report date) used by header + statement caches | `fundamentals` (explicit `group=`); registry default for the path is also `fundamentals` | Yes |
| `/quote` for `<CCY>USD` -- **override** `get_forex_quote` -> `fundamentals` | `get_forex_quote` | `data/step3_data.py::_resolve_fx_rate` (cache key `forex_rate`) | Valuation: reported->USD FX for non-USD reporters (14 ADRs) | `fundamentals` (explicit `group="fundamentals"`) | Yes (non-USD reporters only) |

(The two override rows are the same URL paths counted once each in Parts 3/4; the endpoint total of 35 counts each path once.)

### `profile_quote`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/profile` | `get_profile` | `data/ticker_summary.py`, `step1/2/3/4/5_data.py`, `watchlist_data.py`, `speculative_growth_data.py`, `clients/sec_edgar.py` | Company classification, sector/industry, exchange (also drives `is_us_listed` routing), ETF flag, header | `profile_quote` | Yes |
| `/quote` (stock) | `get_quote` | `data/ticker_summary.py`, `step3_data.py`, `analyst_ratings_data.py`; `bin/start.sh` preflight (AAPL) | Ticker header price/market cap/change, Valuation current price, Analyst tab; group canary | `profile_quote` | Yes |
| `/stock-price-change` | `get_price_change` | `data/ticker_summary.py` (ticker and `SPY`) | Header performance tiles, 5Y-vs-SPY | `profile_quote` | Yes |
| `/search-symbol` | `search_symbol` | `data/ticker_search.py` | Ticker search (symbol prefix) | `profile_quote` | Yes |
| `/search-name` | `search_name` | `data/ticker_search.py` | Ticker search (company name), queried in parallel with `/search-symbol` | `profile_quote` | Yes |

### `analyst_ratings`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/grades-consensus` | `get_grades_consensus` | `data/analyst_ratings_data.py`, `data/watchlist_data.py` | Analyst Ratings tab, Watchlist rating column; group canary | `analyst_ratings` | Yes |
| `/grades-historical` (limit 120) | `get_grades_historical` | `data/analyst_ratings_data.py` | Rating History chart | `analyst_ratings` | Yes |
| `/price-target-consensus` | `get_price_target_consensus` | `data/analyst_ratings_data.py`, `pipeline/nightly_price_target_snapshot.py` (daily 02:10, all US-listed tracked tickers) | Analyst tab targets; daily price-target snapshot | `analyst_ratings` | Yes |
| `/price-target-summary` | `get_price_target_summary` | `data/analyst_ratings_data.py` | Price-target-by-recency buckets | `analyst_ratings` | Yes |
| `/price-target-news` | `get_price_target_news` | **only** `pipeline/backfills/backfill_price_target_snapshots.py` | One-time price-target history backfill (32,764 rows, already run) | `analyst_ratings` | **One-shot script; not called by the app or any cron** |

`BF-B` is sent as `BF.B` to all three `/price-target-*` endpoints (`PRICE_TARGET_SYMBOL_OVERRIDES`).

### `segmentation`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/revenue-product-segmentation` | `get_revenue_product_segmentation` | `data/segmentation_data.py`; nightly fundamentals fetch | Segmentation card; group canary | `segmentation` | Yes |
| `/revenue-geographic-segmentation` | `get_revenue_geographic_segmentation` | `data/segmentation_data.py`; nightly fundamentals fetch | Segmentation card | `segmentation` | Yes |

### `news`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/news/stock` | `get_stock_news` | `data/news_data.py` (`ARTICLE_LIMIT` 30) | News tab; group canary | `news` | Yes (on tab view; cached in its own `NewsCache` table with a minutes-scale TTL, not `FundamentalsCache`, so it is not in `STATEMENT_TYPE_GROUP`-gated cache path -- only the `FMPClient.get` gate applies) |

### `insider` (user toggle is off -- feature shelved)

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/insider-trading/search` (paged, up to 4 x 500) | `get_insider_trading_search` | `data/insider_activity_data.py` | Insider Activity tab | `insider` | **Shelved.** Code reachable, but the group is seeded/kept off and the tab is removed from the UI |
| `/insider-trading/statistics` | `get_insider_trading_statistics` | `data/insider_activity_data.py` | Insider Activity sentiment; group canary | `insider` | **Shelved** (same) |

### `index_membership`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/sp500-constituent` | `get_sp500_constituents` | `scrapers/sp500_scraper.py` (cron Sun 01:00, `scrapers.refresh_sp500_list`) | S&P 500 list, Screener universe, Market Breadth universe | `index_membership` | Yes |
| `/dowjones-constituent` | `get_dowjones_constituents` | `scrapers/dow_scraper.py` (cron Sun 01:10) | Dow list; group canary | `index_membership` | Yes |
| `/nasdaq-constituent` | `get_nasdaq_constituents` | `scrapers/nasdaq_scraper.py` (cron Sun 01:05, `scrapers.refresh_nasdaq_list`) | Nasdaq list (ticker-header index pill) | `index_membership` | Yes |

### `corporate_events`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/earnings` (limit 1000) -- **override** `get_earnings_history` -> `corporate_events` | `get_earnings_history` | `data/corporate_events_data.py` (cron 03:12 nightly) | Chart "E" markers via `CorporateEvent` cache | `corporate_events` (explicit `group=`) | Yes |
| `/dividends` (limit 2000) | `get_dividends` | `data/corporate_events_data.py` | Chart "D" markers; group canary | `corporate_events` | Yes |
| `/splits` (weekly, `SPLITS_REFRESH_DAYS`=6) | `get_splits` | `data/corporate_events_data.py` | Stored in `CorporateEvent`; **no chart marker reads it yet** | `corporate_events` | Yes (fetched and stored; no consumer) |
| `/delisted-companies` (~157 pages/run) | `get_delisted_companies` | `pipeline/stale_data_health_check.py::sync_delisted_flags` (cron Sun 01:30) | `TickerScore.delisted_at` flags that stop bar re-fetching | `corporate_events` | Yes |

Note: `limit` values in code are `EARNINGS_LIMIT`/`DIVIDENDS_LIMIT` constants in `corporate_events_data.py` (client defaults 40/400 are only used by tests).

### `daily_prices`

`/historical-price-eod/full` is one path used by two groups (see the override table in Part 3).
Rows here are the `daily_prices` callers.

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/historical-price-eod/full` | `get_historical_price_eod` (default `group="daily_prices"`) | `clients/daily_bar_sources.py::FMPDailySource` (nightly trend job 03:10 incremental; Sun weekly full resync), feeding `SharedBarsCache` "1d" | Trend/Weinstein, Liquidity Zones, Sector Heatmap, Market Breadth, Momentum | `daily_prices` | Yes |
| `/historical-price-eod/full` | same | `data/chart_data.py::_fetch_fmp_bars` (explicit `group="daily_prices"`), per request | Chart tab D_6M/D_1Y/D_2Y | `daily_prices` | Yes |
| `/historical-price-eod/full` | same (no explicit group) | `data/ticker_summary.py` (cache key `historical_price_eod`/`daily`) | Header avg-volume / dollar-volume tiles | `daily_prices` | Yes |
| `/historical-price-eod/full` | same (no explicit group) | `data/last_close_data.py` (cron 03:15, `pipeline.nightly_last_close_snapshot`) | Last official close (header price fallback) | `daily_prices` | Yes |
| `/historical-price-eod/full` | same (no explicit group) | `pipeline/backfills/backfill_fmp_daily_bars.py` (via `FMPDailySource`) | One-time 5y re-backfill (run 2026-09-24) | `daily_prices` | **One-shot script** |
| `/historical-price-eod/full` | same (no explicit group) | `analysis/ma_magnet/data.py` | MA-magnet research code | `daily_prices` (by default) | **Unwired research** (only imported by other `analysis/ma_magnet/` scripts; no production caller) |

### `daily_prices_long`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/historical-price-eod/full` (10y window) | `get_historical_price_eod(..., group="daily_prices_long")` | `clients/long_history_bars.py::_fetch` (lazy, on view), reading into `LongHistoryBars` | Chart W_4Y weekly range; Analyst Ratings 10y price overlay | `daily_prices_long` | Yes |

### `intraday_bars`

| Endpoint | Client method | Caller(s) | Feature | Gated by | Active? |
|---|---|---|---|---|---|
| `/historical-chart/1hour` (RTH only, paged newest-first) | `get_historical_chart_1hour` | `clients/daily_bar_sources.py::FMPIntradaySource` (via `shared_bars_cache`, nightly Warren 03:40 and BB+RSI 03:20; `SharedBarsCache` "60m") | Warren RSI/ADX/WVF, BB+RSI, Chart entry-signal markers | `intraday_bars` | Yes |

### `extended_hours`

No endpoint, no client method, no call site. Seeded row only.

## Part 3 -- Multi-group endpoints and non-FMP items that share the gate

| Path | Reached by | Resolution |
|---|---|---|
| `/quote` | `get_quote` -> `profile_quote`; `get_forex_quote` -> `fundamentals` (explicit `group=`) | Same URL, two groups. A `fundamentals`-off state blocks FX conversion even though `/quote` is otherwise live under `profile_quote`, and vice versa |
| `/earnings` | `get_earnings` (limit 8) -> `fundamentals`; `get_earnings_history` (limit 1000) -> `corporate_events` | Same URL, two purposes and two groups |
| `/historical-price-eod/full` | default -> `daily_prices`; `long_history_bars` passes `daily_prices_long` | `ENDPOINT_GROUP_OVERRIDES_USED` lists it. Most callers omit `group=` and rely on the default |
| `sec_company_facts` (**SEC EDGAR, not FMP**) | `clients/sec_edgar.py`, cached via `get_or_fetch` | Mapped to `fundamentals` in `STATEMENT_TYPE_GROUP` only to preserve the old pause behaviour; no FMP endpoint |

## Part 4 -- Unwired, dead, one-shot or shelved (summary)

- **Shelved:** both `/insider-trading/*` endpoints (group `insider` off; tab removed from UI).
- **One-shot / not run by any cron:** `/price-target-news` (only `backfill_price_target_snapshots.py`); the `bulk_refresh_*` and `backfill_fmp_daily_bars.py` scripts (they use endpoints that are also live elsewhere).
- **Unwired research code:** `analysis/ma_magnet/data.py` calls `/historical-price-eod/full` but nothing in production imports it.
- **Fetched but unused downstream:** `/splits` (stored, no consumer). `/financial-statement-full-as-reported` is only exercised for Bank-classified tickers.
- **Seeded group with no endpoint:** `extended_hours`.
- **Massive / Yahoo:** confirmed **no** remaining Massive, Yahoo, Alpaca or EODHD call sites or client modules in `backend/` (Phases 6a/6b). No such dead fallback paths were found to flag.
- `/nasdaq-constituent` is **not** in `PROBE_ENDPOINTS` (the `index_membership` canary uses `/dowjones-constituent`), and `PROBE_ENDPOINTS` has no entry for `extended_hours` (no endpoint).

## Part 5 -- Endpoints that don't fit cleanly / verify manually

Fit issues (grouping semantics, not code errors):

1. **`/quote` (FX use)** is registered under `fundamentals`, not `profile_quote`, purely so the Valuation FX lookup follows Valuation's pause behaviour. A `<CCY>USD` forex quote is a different product from a stock quote and may sit in a different FMP tier; check both uses.
2. **`/earnings`** serves two purposes (staleness dates under `fundamentals`; chart history under `corporate_events`). Check whether tier differs by `limit` (8 vs 1000).
3. **`/historical-price-eod/full`** is split across `daily_prices` / `daily_prices_long` only by requested date range. Both are the same FMP endpoint; the split exists to represent history depth (the seeded rationale is Starter 5y vs Premium 30y). Several `daily_prices` callers omit an explicit `group=` and rely on the default; the ticker-header avg-volume request looks back only `DAILY_PRICE_LOOKBACK_DAYS`, not years.
4. **`/delisted-companies`** is filed under `corporate_events` for convenience; it is a market-wide reference list, not per-ticker corporate-action data. `/splits` shares that group but feeds no chart marker yet.
5. **`/search-symbol`, `/search-name`, `/stock-price-change`** are under `profile_quote`, which is labelled "Profile & quote". Confirm tier for each individually; search and price-change are not obviously in the same FMP product as profile/quote.
6. **`/enterprise-values`, `/financial-growth`, `/key-metrics(-ttm)`, `/ratios(-ttm)`, `/analyst-estimates`, `/financial-statement-full-as-reported`** are all lumped under `fundamentals`. In FMP's own catalogue these may sit in different tiers; the group's single recorded tier (Starter in the DB) covers all 12.
7. **`/analyst-estimates`** is in `fundamentals`, not `analyst_ratings`, even though it is analyst data; it feeds Growth Rate scoring.
8. **`/grades-*` and `/price-target-*`** (5 endpoints) share one group and tier, but `/price-target-news` is only used by a spent backfill.
9. **`/nasdaq-constituent`** is grouped with S&P/Dow under `index_membership`, but its plan tier may differ from the other two; the group canary only tests Dow.

Confidence notes:

- **Recorded tiers are the user's own entries**, not FMP-verified facts; `segmentation` and `insider` are unverified in the DB, and several DB tiers (Starter) are lower than the code seeds (Premium), so the seeds cannot be trusted as evidence.
- Two `news` / `index_membership` rows have no recorded `last_success_at` in the DB even though their code paths exist. I did not investigate why (the news tab may have simply not been viewed since the timestamp column was added; the index scrapers only run on Sundays). Worth a glance if you rely on that chip.
- The "Feature" column for cache-key-based reads was derived from call-site context in the `data/*` modules; each `step*_data` function is also run indirectly by `nightly_fundamentals_fetch` (02:00) and `compute_ticker_score`, so an endpoint listed under "Analysis tab" is also hit by that cron. I did not enumerate every transitive path.
- The exact set of endpoints hit by `compute_ticker_score` (Screener/Watchlist scoring) was not traced call-by-call; it composes the same `get_step*`/`get_summary` functions listed above.
