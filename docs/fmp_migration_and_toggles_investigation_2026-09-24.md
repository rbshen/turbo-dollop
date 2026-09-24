# FMP price-data migration + per-data-group toggles — Phase 0 investigation (2026-09-24)

Investigation only. No application code, config, crontab or `.env` was changed. All FMP/Massive
calls were small, made from a scratch folder (deleted afterwards); DB access was read-only
(`file:...?mode=ro`); the Weinstein/Liquidity Zone engines were run in memory only. Times are ET
unless noted. "Verified" = observed live on our key today; "docs" = FMP pricing/marketing material
found via web search (the pricing pages return 403 to non-browser fetches), not verified on our key.

## 0. Headlines

1. **Our FMP key currently behaves like the top (Ultimate) tier.** Every one of ~110 endpoint
   probes returned 200 — global exchanges (HK/Paris/Xetra/LSE/TSX/Tokyo), bulk endpoints, COT
   reports, ETF holdings, transcripts, all intraday intervals — and a 600-request burst sustained
   **~2,455 req/min with zero 429s** (Ultimate is documented at 3,000/min; the code comments still
   say the empirical limit was 300–600/min). **No tier boundary can be observed from this key**, so
   the plan-tier matrix (§2.4) below the "verified on our key" column is docs-only.
2. **The FMP-intraday contradiction is resolved as "the key's entitlement changed", not an endpoint
   quirk.** 2026-09-09: all six intervals 402. 2026-09-20 docs still cite 402s. 2026-09-24: 1min,
   5min, 15min, 30min, 1hour, 4hour all 200. Same endpoints, same paths → entitlement changed
   between ~09-20 and 09-23 (plan upgrade is the obvious explanation; `.env` mtime is 09-24 02:05
   UTC, which is after the 09-23 test, so it doesn't settle it). Consequence for design: **plan
   entitlement is dynamic and a 402 can appear or disappear without a code change** — exactly what
   the toggle design in §4 must handle.
3. **FMP can replace Massive and Yahoo for every price consumer**, including things Massive could
   not do: 10y+ history (daily EOD returns ~20y per call), global tickers, sector ETFs, SPY,
   `^GSPC`, session-anchored (09:30) 1-hour bars back to at least 2008, and extended hours.
4. **URGENT, independent of this migration: the current daily-bar cache has a split-adjustment
   bug** (§3.2). Massive is called with `adjusted=auto_adjust=False`, which for Massive/Polygon
   means *raw, un-split-adjusted*, while for yfinance `auto_adjust=False` still means
   split-adjusted. ~60 of 603 cached tickers have an unadjusted split cliff inside the 5y window
   (BKNG 25:1, NFLX 10:1, CMG 50:1, AVGO 10:1, ANET, GOOG, NOW, KLAC, XLK/XLE/XLB/XLU/XLY 2:1 …).
   **Live symptoms today:** Sector Heatmap 1Y returns for XLK/XLE/XLB/XLU/XLY read −30% … −54%
   (a 2:1 split read as a crash); BKNG's Weinstein stage reads `decline` (should be `advance`,
   slope −44.8% vs +0.4%); Liquidity Zones for split names carry phantom zones. FMP's
   `historical-price-eod/full` is exactly the required basis (split-adjusted, not
   dividend-adjusted) and fixes all of it.
5. A second, smaller cache defect: the 2026-09-23 bar for ~590 tickers was written at 15:50 ET
   (mid-session) and freshness only checks the bar's *date*, so those provisional closes are
   never corrected (only 28% of 09-23 closes are within 0.1% of the official close; finalized
   days match 99.8%).

## 1. Step 0 — repo state

- `git status`: clean at start. **Local commits not on origin/main (not pushed):**
  `d1d266a Add EODHD 2h bar aggregation script (09:30 ET anchored)`,
  `8e0acab Add FMP extended-hours pricing feasibility report`.
- `backend/.env`: `FMP_ENABLED=true`. **`MASSIVE_ENABLED` is not set** — it takes the code default
  `True` (`core/config.py:43`). `CRON_HEALTH_ENABLED=true`. Keys present: FMP, Massive, EODHD,
  Alpaca (names only).
- FMP plan tier: **no API exposes it** (`/api-key-details`, `/account`, `/user`, `/plan`,
  `/usage`, `/api-usage` all 404; no rate-limit headers). Tier is inferred from behaviour (headline 1).

## 2. Inventory and endpoint mapping

### 2.1 Price-data consumers (today)

Provider column = what actually serves it now. Universe ≈ 591 tracked tickers (`TickerScore`);
S&P 500 = 503; W1–W5 watchlist union ≈ 104; 11 sector ETFs. `SharedBarsCache` holds 603 tickers of
`1d` (727k rows, 2021-09→2026-09) and 105 of `60m` (365k rows).

| Consumer (file → function) | Job / trigger | Interval, lookback | Adjust basis | Symbols | Provider today | Calls / night | UI surfaces |
|---|---|---|---|---|---|---|---|
| Trend + Weinstein (`data/trend_analysis_data.py`, `pipeline/nightly_trend_calculation.py`) | cron 3:10 | 1d, 730d | split-adj, no div | full universe + SPY benchmark (not `^GSPC` — code uses SPY since 09-23) | `get_or_fetch_bars_batch` → Massive, per-ticker Yahoo fallback; non-US → Yahoo | ~1–3 grouped-daily + per-ticker backfills (Massive); 1 Yahoo batch for HK | Technical tab, ticker-header Weinstein pill, Screener stage filter (copied to `TickerScore` at 3:50) |
| Liquidity Zones (`data/liquidity_zone_data.py`, cron 3:25) | cron | 1d, 4y (1y daily slice + weekly resample) | split-adj | W1–W5 (~104) | same shared cache | shared with above | Technical tab LZ card, Chart-tab zone lines |
| Sector Heatmap (`data/sector_heatmap_data.py`, cron 3:30) | cron | 1d, 730d | split-adj, non-div (decision) | 11 SPDR ETFs | shared cache (Massive) | ≤11 | `/sectors` |
| Market Breadth (`data/market_breadth_data.py`, cron 3:35) | cron | 1d, 730d, 252-bar windows | split-adj | S&P 500 (503) | shared cache | shared with Trend job (warm read) | `/breadth` |
| Momentum (`data/momentum_data.py`, monthly cron 1st–5th 3:05) | monthly | 1d, 730d | split-adj | tracked universe | shared cache | shared | `/momentum` |
| Warren signal (`pipeline/nightly_warren_signal_calculation.py`, cron 3:40) | cron | **60m**, 730d → 2h candles | raw session bars | W1–W5 | **Yahoo only** (`SharedBarsCache "60m"`) | 1 Yahoo batch | Technical tab card, Chart markers, Screener fields |
| BB+RSI (`pipeline/nightly_entry_signal_calculation.py`, cron 3:20) | cron | **60m**, 60d | raw | W1–W5 | **Yahoo only**, same "60m" row | shares Warren's fetch | Technical tab card, Chart markers, Screener |
| Chart tab (`data/chart_data.py`) | on request | 1d/1w: D_6M/D_1Y (2y), D_2Y (3y), **W_4Y (10y)** | split-adj, non-div | any ticker incl. ETFs, non-US | ≤2y US → Massive live (no cache); **W_4Y and non-US → Yahoo live** | 1 per view | Chart tab |
| Chart events (`data/chart_events_data.py`) | on request | earnings 40 rows, dividends 400 | — | any | **FMP** when enabled, Yahoo on failure/pause | 2 per view | Chart E/D markers |
| Analyst-ratings 10y overlay (`data/analyst_ratings_data.py:42,139`) | on request | 1d, **10y** | non-div | any | **Yahoo live** | 1 per view | Analyst Ratings tab price line |
| Price/quote fallback (`data/ticker_summary.py:101–160`) | FMP paused only | latest | — | any | Massive snapshot → Yahoo (`YahooPriceCache`, 5d) | per view | ticker header price |
| Delisted probe (`pipeline/stale_data_health_check.py`) | weekly Sun 1:30 | 1mo | — | flagged tickers | Massive range call → Yahoo 2nd opinion | few | none (maintenance) |
| Backfills (`pipeline/backfills/backfill_massive_daily_bars.py` etc.) | manual, already run | — | — | — | Massive | — | — |

Cache-state facts (read-only DB): `^GSPC` cache is stale (last bar 09-22, 503 rows, from the Yahoo
era). Delisted/renamed names: WBA last bar 2025-08-27 (FMP: 2025-08-28), TWTR none (FMP `[]`),
`delisted_at` is currently NULL for every ticker in this DB.

### 2.2 FMP consumers (today) — all through `FMPClient.get` (`clients/fmp_client.py:64`)

| Feature area | Endpoints (`/stable`) | Cache key (`FundamentalsCache`) | Cron / trigger | Nightly volume | UI |
|---|---|---|---|---|---|
| Statements & ratios (Steps 1–5, Valuation) | income/cash-flow/balance-sheet (annual+quarter), key-metrics(+ttm), ratios(+ttm, annual 10y), enterprise-values, financial-growth, financial-statement-full-as-reported, treasury-rates, FX quote | `income_statement`… `ratios/*` (≈25 keys) | `nightly_fundamentals_fetch` 2:00 (paced 220 req/min, `TARGET_REQUESTS_PER_MINUTE`) | last 4 nights: 0, 53, **2,655**, 174 calls (weekly-staleness pattern; 2,655 calls = 44.8 min) | Analysis, Valuation, Screener, Watchlist |
| Profile / quote / search | `/profile`, `/quote` (+FX), `/stock-price-change`, `/search-symbol`, `/search-name` | `profile`, `quote`, `price_change` | live on ticker view; nightly batch (quote skipped, `live_quote=False`) | small | ticker header, search |
| Analyst estimates | `/analyst-estimates` | `analyst_estimates` | nightly | ~590 | Growth Rate, Valuation |
| Analyst ratings / price targets | grades-consensus, grades-historical, price-target-consensus/news/summary | `grades_*`, `price_target_*` | on view; `monthly_price_target_snapshot` (1st, 3:00) | monthly ~130+ | Analyst Ratings tab |
| Earnings / dividends | `/earnings` (limit 8 in cache; 40 for chart), `/dividends` | `earnings` | nightly (earnings-aware caching) + chart | ~590 | Chart markers, staleness logic |
| Segmentation | revenue-product/geographic-segmentation | `revenue_*_segmentation` | nightly | ~590 ×2 | Segmentation card |
| News | `/news/stock` | news cache | on view | small | News tab |
| Insider (**shelved**, own flag `INSIDER_ACTIVITY_ENABLED=false`) | insider-trading/search, /statistics | `insider_*` | on view | 0 | hidden tab |
| Index membership | sp500/dowjones/nasdaq-constituent | `IndexConstituent` | weekly Sun 1:00/1:05/1:10 | 3 | universe |
| Legacy daily EOD in cache | `/historical-price-eod/full` (`historical_price_eod` keys `daily`, `2y`, `3y`, `4y`, `8y`, `full_history_chunked`) | 591 `daily` rows refreshed nightly | nightly fetch | ~590 | see note |

Note: `get_historical_price_eod` still exists and `historical_price_eod`/`daily` is refreshed
nightly for 591 tickers via the fundamentals job (used for price-based ratios). That is already an
FMP daily-price consumer, separate from `SharedBarsCache`.

### 2.3 Replacement-endpoint test results (all live, today)

| Need | FMP endpoint | Result |
|---|---|---|
| Daily, split-adjusted, non-div (**required basis**) | `/historical-price-eod/full` | **PASS.** Matches the Yahoo-era rows 100% (AAPL/MSFT/NVDA/SPY/`^GSPC`/WBA). Fields: open/high/low/close/volume/vwap. |
| Daily, dividend-adjusted | `/historical-price-eod/dividend-adjusted` | PASS (`adjClose`); differs from `full` as expected. Not needed. |
| Daily, raw (no split adj) | `/historical-price-eod/non-split-adjusted` | PASS (`adjClose`); equals what our cache holds for split names (§3.2). |
| Daily light | `/historical-price-eod/light` | PASS (close+volume only). |
| Depth | `full` with `from=1990` | **5,000 rows per call** (AAPL back to 2006-11 = ~20y). No `from` → default 5y (1,253 rows). 10y+ = **1 call**. Newest-first. |
| Bulk all-symbols by date | `/eod-bulk?date=` | **PASS** — CSV (not JSON), **61,723 symbols incl. `^GSPC`, SPY, all 11 XL*, HK**; 3.5–3.9 MB, ~3 s. Columns symbol/date/open/low/high/close/adjClose/volume. **Historical dates are raw as of that date** → incremental appends must be split-corrected (see `/splits-calendar`). **One 429** seen immediately after my 600-request burst (recovered <1 min) — bulk appears to have its own tight limit; treat as ≤1 call/min until measured. |
| Splits feed (replaces Massive `get_recent_splits`) | `/splits-calendar?from=&to=` | PASS (455 rows for 8 weeks; `symbol,date,numerator,denominator`). (`/stock-splits-calendar`, `/stock-split-calendar`: 404 — wrong names.) Per-symbol `/splits?symbol=` also works. |
| Batch quote | `/batch-quote?symbols=` | PASS incl. `^GSPC`, SPY, XLK. Also `/batch-quote-short`, `/batch-exchange-quote` (14.5k rows), `/batch-index-quotes`, `/batch-aftermarket-trade`. |
| Live quote | `/quote` | PASS; `timestamp` = 16:00 close when market closed. |
| Indices | `^GSPC` via `/quote` + `/historical-price-eod/full` (20y) | **PASS.** `/historical-index-price/full` 404 (not needed). `/index-list` PASS (427). |
| Sector ETFs, SPY | same EOD/bulk/quote | PASS (all 11 XL* in bulk). |
| Non-US (HK 0005/0700, Paris MC.PA, Xetra SAP.DE, LSE VOD.L, TSX SHOP.TO, Tokyo 7203.T) | quote + EOD + 1hour | **PASS on every exchange** tried, incl. HK 1-hour bars (35/week). All 6 tracked HK tickers are covered. `BRK-B`, `BF-B` hyphen tickers PASS. |
| Intraday | `/historical-chart/{1min,5min,15min,30min,1hour,4hour}` | **All 200 today** (was 402 on 09-09). |
| Intraday anchoring | 1hour: 09:30, 10:30 … 15:30 (7 bars/day); 30min 09:30…15:30; 5min …15:55 | **Session-anchored at 09:30**, timestamps naive ET, same labelling as Yahoo 60m. |
| Intraday depth | 1-week windows tested at 2026, 2025, 2024, 2022, 2015, **2008**: all full weeks (AAPL) | Depth ≥ 18 years on AAPL. **Row cap per response**: 1min ≈1,170 (3 sessions), 5min ≈390–624, 30min ≈273, **1hour ≈434 (~62 sessions)** → must page by date window. |
| Extended hours | `extended=true` on 1min/5min/30min/1hour | PASS: 04:00→19:xx (1hour = clock-anchored 04:00…19:00). Undocumented parameter. `/aftermarket-trade`, `/aftermarket-quote` + batch PASS. `/quote` frozen at 16:00. |
| Session/holiday | `/holidays-by-exchange`, `/exchange-market-hours` | PASS (see 09-24 extended-hours report). |
| Delisted symbols | WBA, TWTR EOD | `200 []` (same "absent, not error" behaviour as Massive). EA/EQR/AVB **still return 2026 EOD and quotes** on FMP although the app treats them as delisted — see §6 questions. |
| Rate limit | 600 × `/quote-short`, concurrency 40 | **2,455 req/min, 0×429** (14.7 s). |

Not usable / not found: plan-tier endpoint; `is-the-market-open`/`market-hours` (404, per the 09-24
report).

### 2.4 Plan-tier matrix (minimum tier per endpoint group)

"Ours" = verified 200 on our key today (**does not prove the tier** — our key is entitled to everything).
"Tier" comes from FMP marketing/docs as summarized by web search (Starter 300 req/min, Premium 750,
Ultimate 3,000; Starter = US only, Premium adds deeper history + UK/Canada, Ultimate adds global,
transcripts, holdings, 1-min data, bulk). **Every Tier cell is docs-only/unverified**; per-endpoint
tiers on FMP's own docs pages could not be fetched (403). The Starter history cap (5y) is from
memory of FMP's pricing table and is also unverified.

| Group / endpoints | Ours | Min tier (docs) | Basis / caveat |
|---|---|---|---|
| Profile, quote, price-change, search | 200 | Starter | US real-time is in Starter |
| Statements/ratios/metrics/growth/EV, **10y annual** | 200 | **Premium** (Starter if 5y were enough) | We need ≥10y; Starter history cap unverified |
| Analyst estimates, grades, price targets, news, insider, segmentation | 200 | Starter–Premium (unknown per endpoint) | docs-only |
| Index constituents (sp500/dow/nasdaq) | 200 | Starter–Premium | docs-only |
| Daily EOD, US stocks/ETFs/`^GSPC`, 5y | 200 | Starter | docs-only |
| Daily EOD **10y+** (Chart W_4Y, Analyst overlay) | 200 | **Premium** (30y history) | docs-only |
| Daily EOD non-US (HK) / intraday non-US | 200 | **Ultimate** (global) | Premium adds only UK/CA per docs |
| `eod-bulk`, `*-bulk`, `batch-*` | 200 | **Ultimate** ("bulk delivery") | `batch-quote` tier unclear |
| Intraday 5min–4hour | 200 | Premium? (unclear) | 402 on 09-09 for all six; docs say only 1-min is Ultimate-exclusive |
| Intraday 1min | 200 | **Ultimate** | docs |
| Extended hours (`extended=true`, aftermarket-*) | 200 | unknown (likely Premium+) | undocumented param |
| ETF holdings, transcripts, COT | 200 | Ultimate | docs (not used by Fathom today) |
| Rate limit | 2,455/min observed | Ultimate 3,000/min | matches |

Design implication: because we can't observe a 402 on this key, the auto-detect path (§4.5) must be
built against a **simulated** 402 (a test double / a deliberately wrong-tier key on a scratch
account) — not verified live.

### 2.5 Estimated nightly FMP call volume if all daily jobs move to FMP

Rate limit is a non-issue (2,455/min measured vs today's self-imposed 220/min in the fundamentals job).

| Job | Preferred pattern | Calls |
|---|---|---|
| Trend / Breadth / Momentum / Heatmap / LZ daily bars | one `eod-bulk` for the new session + one `/splits-calendar` (last ~7d) | **2** (+ ~10 per-ticker `full` re-backfills for tickers that just split or are new) |
| Same, fallback if bulk 429s/unavailable | per-ticker `full?from=lastbar` | 603 (~25 s at 2,455/min) |
| Warren + BB+RSI (105 tickers) 1hour | per-ticker `from=lastbar` | ~105 nightly; **cold backfill of 730d ≈ 8–9 pages × 105 ≈ 900** once |
| Chart / overlay (on demand) | per-view `full` (1 call) | per view |
| Fundamentals (unchanged) | — | 50–2,700 (unchanged) |

## 3. Step 3 — parity vs the existing cache

Scratch harness (deleted). 16 tickers: AAPL, MSFT, NVDA, BKNG, ANET, XLK, XLE, SPY, `^GSPC`, WBA,
0005.HK, BRK-B, NFLX, CMG, AVGO, TSLA. FMP `full` (split-adj) vs cached `1d` closes, 2021-09→2026-09.

### 3.1 Daily-close parity (share of days within 0.1%)

| Ticker | FMP `full` | FMP raw (`non-split-adjusted`) | Reading |
|---|---|---|---|
| AAPL, MSFT, SPY, `^GSPC`, WBA, BRK-B, 0005.HK | **99.4–100%** | same | no split in window — FMP ≡ cache |
| NVDA | 100% | 45.6% | cache is split-adjusted (Yahoo-sourced) |
| BKNG | **9.8%** | 99.7% | cache is **raw**; 25:1 split 2026-04-06 → cache holds $4,184 on 04-01 and $176 on 04-06 (FMP full: $167 on 04-01) |
| ANET | 36.1% | 99.6% | raw; splits 2021-11 and 2024-12 (4:1 each) |
| XLK / XLE | 15.9% | 100% / 99.9% | raw; 2:1 on 2025-12-05 (XLK 04 Dec cache $291.07 vs FMP full $145.54) |
| NFLX | 17.2% | 99.7% | raw; 10:1 2025-11-17 ($1,154 vs $115.42) |
| CMG | 44.8% | 99.9% | raw; 50:1 2024-06 |
| AVGO | 44.1% | 99.7% | raw; 10:1 2024-07 |
| TSLA | 81.5% | 99.9% | raw; 3:1 2022-08 |

Largest single mismatches on non-split names: all ≤0.29% (BRK-B 2026-09-23 0.29%, 0005.HK
2024-12-24 0.27%, AAPL 2026-04-29 0.02%). **Volume** matches (<5%) 96–100% on non-split names.
**Missing dates:** cache has **zero** dates FMP lacks. FMP has 12–16 *extra* dates only because my
FMP window started 2021-09-01 vs the cache's 09-20/24. **2026-09-22 is present in FMP and in the
cache for every ticker** (only `^GSPC`'s cache is one session stale). WBA: FMP has one more bar
(2025-08-28) than the cache. HK: FMP has 750 more days than the 2y Yahoo cache; overlapping days 99.4%.

### 3.2 Root cause of the split cliffs (verified against Massive directly)

`MassiveDailySource` passes `adjusted=auto_adjust` (False) to Massive. Polygon `adjusted=false` =
**raw, not split-adjusted** (NVDA 2024-06-06 raw 1209.98 vs adjusted 120.998; BKNG 2026-04-01 raw
4184.56 vs adjusted 167.38; NFLX raw 1154.23 vs 115.42). yfinance's `auto_adjust=False` is
split-adjusted. The migration mapped one flag onto two different meanings. Cache is therefore
**mixed per ticker** (Yahoo-served rows adjusted, Massive-served rows raw). Universe scan:
**62 of 603 tickers** have a single-day close ratio <0.6 or >1.7, almost all splits (a few are real,
e.g. DD spin-off, MSTR). Row `fetched_at` shows the full history was re-fetched 2026-09-23 (1,255
of 1,258 rows per ticker), so the raw basis is the *current* state of the cache, not old data. The
"suspected BKNG/ANET inconsistency" is confirmed, and is much broader than those two.

### 3.3 Universe-wide check of the latest bar

Bulk 2026-09-23 vs cache 09-23: 597 tickers, **28.3% within 0.1%**, 88 tickers >0.5% off (max
1.9%: IREN, AXTI, ASTS, CHTR, NKE…). Same test for 09-22 and 09-18: **99.8%**, 0 tickers >0.5%.
Cause: the 09-23 bars were written at 19:50 UTC (**15:50 ET, mid-session**) by a one-off run
(`fetched_at` histogram), and freshness only compares the last bar's date, so provisional bars
stick. Tracked tickers absent from FMP bulk: AVB, EA, EQR, TWTR, WBA (all the "delisted five"; EA/
AVB/EQR nonetheless have recent FMP data). All 11 sector ETFs, SPY, `^GSPC` present.

### 3.4 In-memory engine comparison (no DB writes)

`compute_weinstein_stage` (730d, SPY benchmark) and `compute_liquidity_zones` (4y; swing 2, cluster
2%, 3 zones, recency 6 — the live `LiquidityZoneConfig`) run on cache bars vs FMP `full` bars.

| Ticker | Weinstein (cache → FMP) | LZ | Reason |
|---|---|---|---|
| AAPL, MSFT, NVDA, SPY, WBA, 0005.HK, CMG*, AVGO*, TSLA* | identical stage and since-date; slope/vsMA identical to ≤0.02pp; RS within 0.01 | identical zones (last price differs by ≤0.9% on 09-23 for BRK-B/TSLA/CMG only) | no cliff inside the 730d window, or window is post-split |
| **BKNG** | **decline → advance**; since 2026-01-26 → 2026-08-31; slope −44.83 → +0.38; vsMA −81.9 → −12.59 | support [150.14] → [148.04,127.2,123.18]; resistance 217.32 → 226.1 | raw 25:1 cliff in cache (04-06) |
| **XLK / XLE** | advance → advance but **since 2026-07-20 → 2025-06-09 / 2025-11-10**; Mansfield RS −2.73 → +13.32 / −6.85 → +7.07 | phantom resistances 296.09/305.99 (XLK), 94.82/98.97 (XLE) vanish | raw 2:1 cliff 2025-12-05 |
| **NFLX** | decline → decline; since 2025-11-17 → 2025-12-08; RS −72.2 → −27.3 | extra support 58.7 | raw 10:1 cliff |
| **ANET** | advance → advance; vsMA 22.66 → 22.43 | phantom resistance 416.74 (raw 2024-12 price) removed | raw 4:1 |
| BRK-B | slope 0.34→0.33, vsMA 3.40→3.11 | identical | 09-23 provisional bar (508.63 vs official 507.17) |
| AAPL/NVDA/etc. | RS 9.93→9.92 | — | tiny last-day/provider differences |

**Every difference traces to two causes**: (1) the raw-split cliffs, where FMP is *right* and the
cache is wrong; (2) provisional last-day bars. On tickers with neither, results are identical.
No case found where FMP is worse.

### 3.5 Intraday parity (cache Yahoo 60m vs FMP 1hour, 2026-09-14→23)

AAPL: 56/56 bars on identical timestamps, closes 100% within 0.1%, volume 91% within 5%. NVDA:
56/56, closes 98.2% within 0.1% (max 0.17%), volume 84%. BKNG: FMP has 7 bars the cache lacks
(cache 60m is one session stale — last bar 09-22). Volume differs more (consolidated vs Yahoo
venue volume); Warren (RSI/ADX/WVF on closes) and BB+RSI don't depend on volume. TSLA and 0005.HK
are not in the cache's 60m set (not on W1–W5), so not compared. **Warren event parity (full
replay comparison) was not run** — see phase P4.

## 4. Step 4 — toggle system design (proposal only)

### 4.1 Data groups (one per feature area, not per endpoint)

Tier column = minimum FMP tier per §2.4 (docs-only unless noted).

| Group key | Contains | Min tier | Cron jobs | UI it feeds |
|---|---|---|---|---|
| `fundamentals` | statements, ratios, key-metrics, growth, EV, as-reported, treasury/FX, analyst-estimates, earnings (staleness logic) | Premium (≥10y) | `nightly_fundamentals_fetch`, `nightly_score_recompute` reads cache only | Analysis, Valuation, Screener, Watchlist scores |
| `profile_quote` | profile, quote, price-change, search | Starter | (quote is on-demand) | ticker header, search, `/refresh` |
| `analyst_ratings` | grades, price-target-* | Starter–Premium | `monthly_price_target_snapshot` | Analyst Ratings tab (+ needs `daily_prices` for the overlay) |
| `segmentation` | revenue product/geo | Starter–Premium | (in nightly fundamentals) | Segmentation card |
| `news` | news/stock | Starter | — | News tab |
| `insider` | insider-trading-* | Starter–Premium | — | shelved (default **off**; replaces `INSIDER_ACTIVITY_ENABLED`) |
| `index_membership` | sp500/dow/nasdaq constituents | Starter | 3 weekly scrapers | universe, Screener |
| `corporate_events` | earnings history, dividends for chart | Starter | — | Chart E/D markers |
| `daily_prices` | EOD US stocks/ETFs/indices, bulk EOD, splits calendar | **Premium** (10y) | trend 3:10, LZ 3:25, heatmap 3:30, breadth 3:35, momentum (monthly), delisted probe | Technical (Weinstein/LZ/trend), Chart daily/weekly, Analyst overlay, Sector Heatmap, Breadth, Momentum, Screener stage filter, price fallback |
| `daily_prices_intl` | EOD for non-US symbols | **Ultimate** | same jobs, non-US subset | HK tickers everywhere above |
| `intraday_bars` | 1hour (later 5/1-min) | Premium? / Ultimate (1min) | BB+RSI 3:20, Warren 3:40 | Technical entry-signal cards, Chart markers, Screener signal fields |
| `extended_hours` | `extended=true`, aftermarket-* | unknown | — (not built) | ticker header pre/post price |

Granularity trade-off: splitting `daily_prices_intl` from `daily_prices` costs one more row but
matters because the tier differs (a Premium key gets 402 on HK symbols) and because a per-symbol
402 must not disable the whole US group (§4.5). Splitting `profile_quote` from `fundamentals` lets
a user keep live header prices while pausing the heavy nightly fetch. I would **not** split further
(per-statement-type groups): the fundamentals scoring needs all statements or none.

### 4.2 Storage: DB, not `.env` (recommended)

DB table (`DataGroupSetting`: `group_key` PK, `enabled`, `status` ∈ ok / plan_restricted / failing,
`restricted_since`, `last_success_at`, `last_error`, `updated_at`), plus one singleton row for the
master switch and one `fmp_plan` value (Starter/Premium/Ultimate, used to grey out groups above
plan). Rationale: the app already has this convention (`LiquidityZoneConfig`, `DiscountRateConfig`,
lazy-seeded singleton rows, editable from `/settings`); toggles then apply **live without the
restart** that `bin/start.sh` currently forces (prod mode, no hot reload); cron processes (separate
`uv run` processes) read the same truth as the API; and auto-detected plan restrictions (§4.5)
have to be *written* at runtime, which `.env` can't do. Costs: a DB read per gate check (mitigate
with a 5–10 s in-process cache and explicit invalidation on write); the pytest write-guard
(`tests/conftest.py`) needs the toggle table seeded in the in-memory engine. Keep in `.env` only
`FMP_API_KEY`/`FMP_BASE_URL`. Provide a tiny CLI (`python -m pipeline.data_groups pause-all|resume|status`) so the
switch can still be flipped when the API is down (replaces "edit `.env` and restart").

Effective state of a group = `master_on AND group.enabled AND group.min_tier <= fmp_plan AND
status != plan_restricted`. The UI shows *why* a group is off (user / master / above plan /
restricted by FMP / failing).

### 4.3 Gate points (registry approach)

One registry (`core/data_groups.py`): endpoint-path → group, `FundamentalsCache.statement_type` →
group, job name → group(s). `FMPClient.get` maps its endpoint to a group and raises
`FMPGroupDisabledError` (a **subclass of `FMPDisabledError`**, itself an `httpx.HTTPError`), so
every existing `except httpx.HTTPError`/`safe_fetch` site keeps working with no edits — the same
"no call site under `data/` needs any change" property today's flag has. `cache.get_or_fetch`,
`get_or_fetch_earnings_aware`, `force_fetch` replace `settings.fmp_enabled` with
`group_enabled(group_for(statement_type))` → serve the last cached row (current cache-only
behaviour preserved; nothing ever wiped). An unmapped endpoint should fail the registry test rather
than bypass the gate.

### 4.4 Dependency map / UI behaviour

| Group off | Stops refreshing | Still works (cached) |
|---|---|---|
| `daily_prices` | Weinstein/Trend, LZ, Heatmap, Breadth, Momentum, Chart, overlay, price fallback, Screener stage | last cached bars/rows; Chart has no cache → shows "unavailable" (today it silently falls back to Yahoo) |
| `daily_prices_intl` | HK tickers' daily features only | US unaffected |
| `intraday_bars` | Warren, BB+RSI | stored latest-state rows, event history, chart markers |
| `fundamentals` | Steps 1–5, Valuation, Screener scores | cached scores; nightly recompute is cache-only and keeps running |
| `profile_quote` | header price/change/cap, search (falls back to local universe as today), `/refresh` | cached quote |
| `analyst_ratings` | tab + monthly snapshot | cached |

Composite dependencies to surface: Analyst overlay needs `analyst_ratings` **and** `daily_prices`;
the Screener needs `fundamentals` + `daily_prices` + `intraday_bars` (it copies technical fields at
3:50). UI: replace the FMP/Massive/Yahoo cards in Settings → Status with one row per group (state
chip Live / Cached only / Not on plan / Failing, last success, min tier, "feeds:" list, toggle
greyed with tooltip when above plan or master off); a single `GET /api/config/data-groups` (replaces
`/api/config/fmp-status`, SWR-polled like `useCronHealth`) drives small "not refreshing" badges on
the affected pages (Technical cards, `/sectors`, `/breadth`, `/momentum`, Screener) showing the
as-of date they're frozen at. Turning a group off should warn with the list of dependent features.

### 4.5 Master switch and auto-detection

Master "disable all FMP": the singleton row; semantics = today's `FMP_ENABLED=false` (every group off,
cache-only everywhere, `/refresh` 503). Auto-detection: on **402** (plan restriction) mark the group
`plan_restricted` and short-circuit further calls; on 401/403 treat as a *key* problem (global, do
not blame a group); on 429 never mark (rate limit). Two cautions: (a) the exact 402/403 bodies must be
captured from a real restricted response — I could not produce one (§2.4); (b) a 402 can be
**symbol-scoped** (e.g. a non-US symbol on a US-only plan), so the failing call itself must not
disable the group — flag it only after a canary probe (a known-good symbol, e.g. AAPL) also 402s;
that is why `daily_prices_intl` is its own group. Re-probe restricted groups weekly and whenever
`fmp_plan` is edited, so an upgrade (as on ~09-20) self-heals without a manual step. Nightly jobs
for a disabled/restricted group log "skipped (group X off/restricted)" and finish as a heartbeat
success with `skipped` in the message — same as `nightly_fundamentals_fetch` does today
(`run.message = "Skipped — FMP disabled"`). Recommend adding a distinct `skipped` status to
`cron_health` so a long-off group doesn't read as healthy (verify against `core/cron_health.py`
before building; I did not audit its status model).

### 4.6 Every `FMP_ENABLED` / `MASSIVE_ENABLED` touchpoint and its replacement

| Touchpoint | Today | Replacement |
|---|---|---|
| `core/config.py:30,43` | `fmp_enabled`, `massive_enabled` settings | removed; one-release shim: `FMP_ENABLED=false` in `.env` seeds the master row off with a warning, then delete |
| `clients/fmp_client.py:65` `FMPClient.get` + `FMPDisabledError` | global gate | per-group gate, subclass exception (§4.3) |
| `core/cache.py:74,142,172` | global; serves stale row / raises if none | per-group via statement-type registry; same semantics |
| `core/main.py:165` `/api/config/fmp-status` | `{enabled}` | `/api/config/data-groups` |
| `core/main.py:647` `POST /refresh` 503 | blocks when FMP off (protects against clear-then-fail) | **subtlety**: with groups, `clear_ticker_cache` must only clear rows of *enabled* groups, or 503 if any group it would clear is off — otherwise a partial refresh wipes rows it cannot refetch |
| `data/ticker_search.py:114` | local-universe fallback | `profile_quote` off → same fallback |
| `data/ticker_summary.py:101–160,300` | Massive snapshot → Yahoo price fallback when FMP off | `profile_quote` off but `daily_prices` on → last daily close from FMP/cache; no Yahoo/Massive. Removes `YahooPriceCache` and `yahoo_cache.py` (P6) |
| `data/chart_events_data.py:187` | FMP vs Yahoo | `corporate_events` group; Yahoo removed |
| `data/chart_data.py`, `data/analyst_ratings_data.py` | Massive/Yahoo live | FMP `full` (`daily_prices`) |
| `clients/daily_bar_sources.py::get_daily_bar_source` | `massive_enabled` rollback lever | **transitional** DB value on `daily_prices`: provider preference `fmp` / `massive` (default flips during P2), deleted in P6 |
| `clients/technical_sources.py` | hard-wired Yahoo, "FMP unwired placeholder" | `FMPTechnicalSource` implemented in P4 |
| `pipeline/nightly_fundamentals_fetch.py:171`, `monthly_price_target_snapshot.py:86` | early return `skipped` | per-group guard (`fundamentals`; `analyst_ratings`) |
| Trend/LZ/heatmap/breadth/warren/bb+rsi/momentum jobs | no guard (documented "zero FMP calls") | new group guard, `skipped` |
| `pipeline/stale_data_health_check.py` | `massive_enabled` decides flagging | flagging rule uses provider = FMP only; single-provider evidence caveat disappears (dual-provider logic must be rethought — see §5) |
| `bin/start.sh:95` | skips the AAPL `/quote` check when paused | skip when master off or `profile_quote` off; a 402 must warn, not fail startup |
| `core/data_source_status.py`, `DataSourceCard.tsx`, `StatusSection.tsx` (`FMP_POWERS`, `MASSIVE_POWERS`, `flagLabel`) | 3 provider cards | group table; `massive`/`yahoo` `DataSourceHealth` rows dropped in P6 |
| Tests | 23 test files reference the flags (heaviest: `test_stale_data_health_check` 21, `test_ticker_summary` 18, `test_chart_events_data` 9, `test_chart_data` 8, `conftest` 7) | fixture that seeds group state in the in-memory engine; `conftest` currently pins flags |
| Docs | `CLAUDE.md` "Pausing the FMP subscription" and ~15 other mentions, `OPS_RUNBOOK.md` (8), `crontab.txt` comments (3), `docs/*` | rewrite; the CLAUDE.md section is the spec for cache-only behaviour and should be carried over verbatim in intent |

### 4.7 Where it slots in

**Before** any price migration (P1), because P2 introduces the `daily_prices` group and replaces
`MASSIVE_ENABLED`'s rollback role; building the group registry first means the price work lands
into the new model instead of adding a third flag.

## 5. Step 5 — risks and phase plan

**Single-vendor risk.** FMP as sole source for fundamentals *and* prices means one billing lapse,
plan downgrade, key problem or outage stops everything at once; today's `FMP_ENABLED=false`
degrades gracefully only because prices have other providers. The 09-09→09-24 entitlement flip shows
the plan is a moving part. Mitigations: (1) `SharedBarsCache` is the real safety net (5–6y stored) —
all features already read cache-first; (2) the group toggles make a partial loss (e.g. Ultimate →
Premium losing `daily_prices_intl`/1-min) degrade one feature, not all; (3) keep **one** thin,
dormant, manual fallback for daily bars (the existing Yahoo adapter, ~120 lines) at least one
quarter after cutover — my recommendation; deleting it at P6 is acceptable if you'd rather have
zero secondary dependencies (open question). Massive can be dropped fully (paid $29/mo, and its
`adjusted` semantics caused §3.2).

**What FMP cannot / does not cleanly cover.** No plan-tier introspection; historical bulk EOD is
raw so incremental appends need split correction (`/splits-calendar`); `eod-bulk` is CSV, ~3.7 MB, one
date per call and showed a 429 (limit unmeasured); intraday responses are row-capped so backfills
must page; `extended=true` is undocumented; volume is not identical to Yahoo's (fine for our
indicators); no working "is the market open" endpoint (session logic stays client-side, as today);
the delisted-ticker logic (`stale_data_health_check`) relied on Massive+Yahoo agreeing — with one
provider, FMP returning `[]` is the only signal, and FMP still serves recent data for EA/EQR/AVB
which the app treats as delisted (worth checking the flag's definition, §6); the cache-freshness
rule compares bar *date* only, which also needs hardening (never trust a bar written before the
session close; e.g. record `fetched_at` vs 16:00 ET and refetch the last bar).

**Phase plan — confirmed with corrections.**

| Phase | Confirmed? | Evidence / correction | Effort (eng-days, incl. tests+docs) |
|---|---|---|---|
| **P0.5 (new, recommended now)** | add | fix the live split-basis bug independent of migration: heatmap 1Y for 5 sector ETFs and BKNG/NFLX/CMG/AVGO/ANET stages are wrong today. Minimal fix: `adjusted=true` in `MassiveDailySource` + one forced re-backfill, or simply do it as the first step of P2 | 0.5–1 (or fold into P2) |
| P1 toggle system | **yes, first** | §4; existing FMP groups only (+ `daily_prices` row seeded but unused) | 3–4 |
| P2 daily US price consumers → FMP via `DailyBarSource` | yes | `FMPDailySource` (`full` backfill, `eod-bulk` + `/splits-calendar` incremental), transitional provider preference, one forced re-backfill on the split-adjusted basis, freshness hardening, parity harness re-run (Weinstein/LZ/Heatmap/Breadth/Momentum diffs). Adds Massive-snapshot replacement (`/quote`) for price fallback | 3–4 |
| P3 long-history Yahoo consumers | yes, **smaller than assumed** | Chart W_4Y, Analyst 10y overlay, non-US and chart events are each ~1 call of `full` (20y per call, verified); non-US needs `daily_prices_intl` (Ultimate) | 1–1.5 |
| P4 intraday Warren / BB+RSI | yes | `FMPTechnicalSource` on `1hour` (09:30-anchored, verified identical timestamps), paging (~434-row cap), incremental `from=`; **must run a full Warren/BB+RSI event replay parity test before cutover** (not done here) and re-tune the 180-day write buffer only if replay behaviour differs | 3–4 |
| P5 extended hours | yes | `extended=true` + `aftermarket-*`; session-state client-side (`holidays-by-exchange`); needs UI decisions | 2–3 |
| P6 remove Massive/Yahoo + flag leftovers | yes | delete `massive_client`, `daily_bar_sources` Yahoo/Massive classes, `yahoo_client/yahoo_cache/technical_sources` Yahoo path, `YahooPriceCache`/`DataSourceHealth` rows, `MASSIVE_*` settings/key, `stale_data_health_check` rework, docs | 1.5–2 |

Total ≈ 14–19 engineer-days. P1 should not start P2's price cutover until the parity results in §3 are
re-run on FMP-fed caches, and P4 should follow P2 by at least a week of clean nightly runs.

## 6. Open questions

1. **Split-basis bug**: do you want the P0.5 hotfix immediately (Sector Heatmap 1Y is wrong on the live page for XLB/XLE/XLK/XLU/XLY), or fold it into P2?
2. **Plan**: is the key intentionally on Ultimate now (and staying)? The design assumes intl/1-min are available; if it drops to Premium, `daily_prices_intl` (6 HK tickers) and 1-min go away.
3. **Yahoo at the end**: delete entirely, or keep one dormant manual daily-bar fallback for a quarter (my recommendation)?
4. **Delisted flag**: FMP still returns 2026 data for EA/EQR/AVB, while `delisted_at` is NULL for all in this DB although CLAUDE.md lists five as delisted — what is the intended state?
5. **`.env` shim**: OK to keep `FMP_ENABLED=false` as a one-release seed for the master row, or remove it outright in P1?
6. **`skipped` in cron health**: OK to add a real `skipped` status (touches `core/cron_health.py`, banner, tests)?
7. **`eod-bulk` limit** is unmeasured (one 429 after a burst). I can characterise it before P2, or P2 can default to per-ticker incremental (~25 s) and treat bulk as an optimisation.
8. Extended hours (P5) product shape (header pill vs chart) is undecided.
