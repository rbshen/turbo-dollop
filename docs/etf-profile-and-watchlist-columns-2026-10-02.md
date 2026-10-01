# ETF page: what `/profile` adds, and ETF watchlist columns (2026-10-02)

Report-only. No code or DB changes. FMP was probed live with a throwaway script outside the repo (raw responses
never touched `fathom.db`); DB reads were read-only (`mode=ro`). Browser rendering was **not** verified. Built on
`docs/etf-page-investigation-2026-10-01.md` and `docs/specs/etf-page.md` (where they differ, the code wins).

Constraints honoured: no Ultimate-tier endpoint, US ETFs only, the Overview tab is currently `/etf/info`-only.

Live calls made: `/profile` x7 (QQQ, SPY, SMH, XLK, GLD, TLT, AAPL), `/etf/info` x6, `/stock-price-change` x7,
`/quote` x7. All 200. Probe time: 2026-10-01 ~20:20 UTC (market just closed).

## Summary

- **`/profile` adds almost nothing the ETF page does not already have.** The summary the ETF page already loads
  (`TickerSummaryOut`) carries price, change, market cap, beta, 52-week range, 1M/6M/YTD/1Y/5Y/10Y performance and
  30-day volume. `/profile` overlaps `/etf/info` on name, description, ISIN, CUSIP, average volume and the inception
  date (with disagreements, item 2). The one useful profile-only field is `lastDividend`, which is **a trailing-12-month
  distribution per share, not the last payment** (verified: SPY 7.58272 is exactly the sum of its four latest cached
  dividends). It gives a distribution yield for free.
- **No new FMP call and no new table** is needed for any ETF-page addition proposed here.
- **Do not show profile `marketCap` on an ETF page.** It is price x shares, and it visibly contradicts the AUM already in
  Fund facts (QQQ 528.7B vs 498.6B, TLT 39.3B vs 46.2B).
- **Beta is only meaningful for equity ETFs** (TLT reports 2.4; implausible for a Treasury fund against equities).
- **Watchlist today:** one hard-coded 13-column stock table for every list. An ETF row is mostly blank cells plus an
  "ETF" badge, a live-fetched consensus rating that always resolves to "N/A", and a misleading Beta.
  Column sets cannot vary per list.
- **Everything proposed for the ETF list (price, 1D/1M/YTD/1Y, Weinstein stage, BB+RSI, Warren, nearest LP zone) can be
  served from data already in the DB**, with zero new FMP calls, if performance is computed from the cached daily bars.
  `/stock-price-change` works and is cheap, but its cached copy is up to 7 days old, so it is the wrong source for a
  "1D" column.
- The one new FMP dependency for ETF-list columns is `/etf/info` (asset class, expense ratio): one call per ETF per day
  at worst, only for ETFs on a list being viewed.

## 1. `/profile` on ETFs (live, 2026-10-01)

Tier: the repo's `profile_quote` group (`/profile`, `/quote`, `/stock-price-change`) is recorded as **Starter** in the
live DB (`datagroupsetting.required_tier`) and in the code seed. Those are the owner's entries, not FMP-verified (FMP's
docs return 403 to our fetcher; `docs/specs/fmp-data-and-bar-cache.md` says the same). It works on the current key
(plan recorded as Ultimate). One call per symbol; no batch variant is used (a registry test pins that any bulk/batch
endpoint must be Ultimate).

Freshness: the probe's `price`/`change` matched `/quote` exactly, so the profile snapshot is same-day. Its `volume` was a
few minutes behind `/quote` (QQQ 35,146,489 vs 35,370,061). **The app caches the profile for 30 days**
(`Settings.profile_staleness_days`), so every price-like profile field in the DB can be a month old. The app already
takes price, change, market cap and 52-week range from `/quote` (force-fetched on every live ticker-page view), and
only beta, name, exchange, sector/industry, description and `isEtf`/`isFund` from the profile.

Samples are QQQ / SPY / SMH / XLK / GLD / TLT; AAPL in brackets where useful.

| Field | Sample values | ETF status | Notes |
|---|---|---|---|
| `symbol`, `companyName` | `Invesco QQQ Trust, Series 1` / `State Street SPDR S&P 500 ETF` / `VanEck Semiconductor ETF` / `State Street Technology Select Sector SPDR ETF` / `SPDR Gold Shares` / `iShares 20+ Year Treasury Bond ETF` | Populated | Same as `/etf/info.name` on all 6. |
| `price` | 742.03 / 763.99 / 617.81 / 197.81 / 382.76 / 77.71 (AAPL 330.32) | Populated | Equals `/quote.price` at probe time. Cached 30 days, so the app reads price from `/quote`. |
| `change`, `changePercentage` | +2.26/+0.31% / +1.36/+0.18% / +8.81/+1.45% / +2.06/+1.05% / +1.92/+0.50% / -0.07/-0.09% | Populated | Same as `/quote`. Intraday-live while the market is open. |
| `marketCap` | 528.7B / 813.8B / 77.9B / 129.4B / 135.0B / 39.3B | Populated, **misleading as "market cap"** | Looks like price x shares outstanding, i.e. a market-implied AUM. Versus `/etf/info.assetsUnderManagement`: **+6.0% / +0.3% / +4.0% / +2.3% / -4.6% / -15.0%**. The gap is not explained by premium to NAV (price vs NAV was within +/-1.8%), so share counts and AUM are as-of different times. |
| `beta` | 1.232 / 1.01 / 1.98 / 1.348 / 0.45 / **2.4** (AAPL 1.085) | Populated; **meaningless for bond/commodity** | Equity ETFs read sensibly (SPY 1.01, SMH 1.98). TLT 2.4 is implausible for a Treasury fund; the benchmark and window are undocumented. GLD 0.45 is plausible but not an equity beta in any useful sense. |
| `lastDividend` | 3.09182 / 7.58272 / 1.1047 / 0.79319 / **0** / 3.89049 (AAPL 1.06) | Populated; **mislabelled** | Trailing-12-month dividends per share, not the last payment (SPY: 1.88883 + 1.90352 + 1.797 + 1.99337 = 7.58272, the four latest `CorporateEvent` rows). GLD `0` is a true "no distribution", not unknown. Yield = value / price: QQQ 0.42%, SPY 0.99%, SMH 0.18%, XLK 0.40%, TLT 5.0%. A distribution yield, not an SEC yield. Under-reads for an ETF listed less than a year. |
| `range` | `555.6-748.65` / `629.28-779.37` / `315.05-671.83` / `126.68-198.73` / `351.4-509.7` / `76.76-92.19` | Populated | A 52-week low-high **string** (needs parsing). Equals `/quote.yearLow`/`yearHigh`, which the app already uses (`week52_low/high`). |
| `volume` | 35.1M / 46.2M / 5.08M / 10.9M / 5.77M / 82.6M | Populated | Slightly lags `/quote.volume`. |
| `averageVolume` | 39.6M / 48.6M / 9.76M / 9.76M / 8.77M / 30.9M | Populated | **Identical** to `/etf/info.avgVolume` on all 6. The app already computes its own 30-day average from bars (`avg_volume_30d`), because this field is closer to a 50-63 day average. |
| `currency` | USD x6 | Populated | |
| `exchange`, `exchangeFullName` | NASDAQ / AMEX / NASDAQ / AMEX / AMEX / NASDAQ; `NASDAQ Global Market` / `New York Stock Exchange Arca` | Populated | Only source for the listing venue (`/etf/info` has none). The header already shows it. SPY on NYSE Arca reads `AMEX` (FMP's code; in `US_EXCHANGES`). |
| `sector`, `industry` | `Financial Services` x6; `Asset Management` (TLT `Asset Management - Bonds`) | Populated, **misleading** | The fund sponsor's business, not the fund's. Already suppressed everywhere (`TickerScore.sector` nulled for ETFs; no header eyebrow). |
| `description` | 254-882 chars | Populated | **Byte-identical** to `/etf/info.description` on all 6. |
| `isin`, `cusip` | present on all | Populated | Equal to `/etf/info.isin`/`securityCusip` on all 6. |
| `website` | issuer product pages | Populated | **Differs from `/etf/info.website` on 4 of 6** (QQQ, SPY, XLK, TLT). The profile's SPY link is the Australian site (`ssga.com/au/en_gb/...`); `/etf/info` has the US one. |
| `ipoDate` | 1999-03-10 / 1993-01-22 / 2000-05-05 / 1998-12-22 / 2004-11-18 / 2002-07-30 | Populated | A listing or first-trade date. **Differs from `/etf/info.inceptionDate` on 3 of 6** (SMH 2000-05-05 vs 2011-12-20; XLK 12-22 vs 12-16; TLT 07-30 vs 07-21). |
| `cik` | trust CIK | Populated | Not useful on the page. |
| `ceo`, `fullTimeEmployees` | `""`, `null` | Empty / null | Stock-only. |
| `phone`, `address`, `city`, `state`, `zip` | sponsor HQ (SPY, XLK and GLD all `1 Iron Street, Boston`) | Populated, irrelevant | The sponsor's office, not the fund's. |
| `image` | FMP logo URL | Populated | Not used by the app. |
| `isEtf` / `isFund` | `true` / `false` on all 6 (AAPL `false` / `false`) | Populated | The app's detection rule (`isEtf \|\| isFund`) holds. |
| `isActivelyTrading`, `isAdr`, `defaultImage` | `true`, `false`, `false` | Populated | |

AAPL baseline: every field above is populated; `ceo` is `John Ternus`, `fullTimeEmployees` is `"166000"`, sector
`Technology`. The profile has **no** shares-outstanding, no `mktCap` key (the app's `profile.get("mktCap")` fallback
never fires on the stable API), no dividend yield and no ETF-specific fields (expense ratio, NAV, asset class, issuer).

## 2. Overlap with `/etf/info`

| Fact | `/profile` | `/etf/info` | Better source |
|---|---|---|---|
| Name, ISIN, CUSIP, description, average volume | identical | identical | Either; `/etf/info` (already used). |
| AUM | `marketCap` (price x shares, real-time-ish) | `assetsUnderManagement` (daily, `updatedAt` 2026-10-01; TLT 2026-09-29) | `/etf/info` for the page's AUM. They disagree by 0.3% to 15% on the test set, so **never show both**. |
| Inception | `ipoDate` (listing/first-trade) | `inceptionDate` | `/etf/info`. The profile date is a listing date and for SMH reflects a 2000 predecessor listing (inferred from the 2000 vs 2011 gap). |
| Issuer | none | `etfCompany` (`Invesco`, `SPDR`, `VanEck`, `IShares`) | `/etf/info`. |
| Exchange | `exchange`/`exchangeFullName` | none | `/profile`. |
| Website | issuer page | issuer page | `/etf/info` (the profile's SPY link is a non-US page). |
| Asset class, expense ratio, NAV, holdings count, sector weights, domicile | none | yes | `/etf/info` only. |
| Beta, TTM distribution, 52-week range | yes | none | `/profile` (beta, distribution); the range is better from `/quote`. |

Disagreements on the test tickers: market cap vs AUM (all six), inception vs IPO date (SMH, XLK, TLT), website (four).
Nothing else differs, which is consistent with both endpoints drawing description, ISIN, CUSIP and volume from one
source.

## 3. What the app already stores and shows

- **Persisted:** the whole profile response, as one `FundamentalsCache(ticker, "profile", "latest")` row (~1.4-1.8 KB for
  an ETF), refreshed on a **30-day** window (`profile_staleness_days`). Not a table of fields: `get_summary` reads
  individual keys at request time. `TickerScore` denormalizes only `is_etf`, `company_name`, `sector` (nulled for ETFs),
  `industry`, `market_cap` (from the quote), `beta`.
- **Quote:** `FundamentalsCache(ticker, "quote", "latest")`, force-fetched on each live ticker-page view; read through
  `get_or_fetch` (7-day window) on the nightly/cache-only paths.
- **Price change:** `FundamentalsCache(ticker, "price_change", "latest")`, `cache_staleness_days` = **7 days**. Live
  example: SPY's row was fetched 2026-09-29 and is still served on 2026-10-01. So `perf_1m/6m/ytd/1y/5y/10y` in
  `TickerSummaryOut` can be up to a week old.
- **ETF header** (`EtfHeader`): fund name, `TICKER · EXCHANGE`, price, daily change, caption "Exchange-traded fund · <asset
  class>", the watchlist button.
- **ETF Overview** (`EtfOverviewTab`, from `/etf/info`): Fund facts (issuer, asset class, expense ratio, AUM, holdings
  count, NAV, average volume, inception, domicile), About, Sector weights (equity funds), "as of".
- **Already in the summary the ETF page loads but not displayed on an ETF:** `week52_high/low`, `perf_1m/6m/ytd/1y/5y/
  10y`, `beta`, `avg_volume_30d`, `avg_dollar_volume_20d`. Not in the summary: the profile's `lastDividend`
  (`dividend_yield` is `None` for an ETF because `/ratios-ttm` answers `[]`).
- **Does showing more profile fields need a new FMP call or table? No.** The profile row is already cached for every
  ETF that has been opened. The only plumbing is exposing `lastDividend` (one new `TickerSummaryOut` field), and
  `EtfOverviewTab` receiving the summary, which `EtfTickerPage` already has.
- DB state today: 7 ETF profiles cached (SPY, TECL, GLD, XLV, SMH, IBIT, XLK), `etf_info` cached for the same 7,
  `TickerScore.is_etf` for 3 (SPY, TECL, GLD). The watchlist named `ETF` exists and is empty. No ETF is on any
  `E<number>` list. Note the live DB has `etf_info`'s required tier as **Starter**, while `docs/specs/etf-page.md` still
  says the seed is Premium (an owner edit; the spec is stale on this point).

## 4. Other cheap data (stable quote and price change)

- **`/stock-price-change`** (group `profile_quote`, recorded tier Starter): 200 on all 7 symbols, ~258 B each. Returns
  `1D, 5D, 1M, 3M, 6M, ytd, 1Y, 3Y, 5Y, 10Y, max` as percent. Useful and sensible for ETFs (QQQ 1Y +23.0%, TLT 1Y
  -13.0%, GLD YTD -3.4%). The `1D` is **intraday-live** (equals `/quote.changePercentage` to the digit while the
  session runs). Also: `max` for AAPL is 257,258.8%, so the field is split-adjusted-from-IPO and not for display.
- **`/quote`** (group `profile_quote`, Starter): 200, ~450 B. Adds `dayLow/High`, `yearLow/High`, `priceAvg50`,
  `priceAvg200`, `previousClose`, `open`, `volume`, `timestamp`. The 50/200-day averages are cheap context but the app
  already has bar-derived technicals.
- **Cost:** FMP counts one request per symbol per call (no per-endpoint weight found in the app's rate-limit model);
  Starter's documented limit is 300 requests/min (`FMP_PLAN_REQUESTS_PER_MIN`). A 100-ETF list would be 100 calls per
  page load if polled: feasible, but needless.
- **Recommendation: do not poll either for the watchlist.** The watchlist page is deliberately cache-only
  (price/change were removed from it on 2026-08-03 because the live quote made it the one page that always hit FMP).
  The daily bars are already cached nightly for the whole tracked universe, split-adjusted (not dividend-adjusted;
  `clients/daily_bar_sources.py`), 1,253-1,259 daily bars for the ETFs checked. Price, 1D, 5D, 1M, 3M, 6M, YTD and 1Y
  are all computable locally from them (price return, consistent with the app's other bar-derived numbers), as of the
  last completed session, with **zero FMP calls** and no stale 7-day cache. Caveat: a never-nightly'd ETF has no bars
  yet (SMH had none cached at probe time; it appears after the next `nightly_trend_calculation`).

## 5. Watchlist columns today

Single component, `frontend/components/watchlist/WatchlistTable.tsx`; rows from `GET /api/watchlists/{id}/rows`
(`data/watchlist_data.py::get_watchlist_rows`, all cache-only except the consensus call).

| # | Column | Sortable | Source | Stock-only? | ETF row today |
|---|---|---|---|---|---|
| 1 | Ticker + company name | yes | `TickerScore.company_name`; ticker | no | Correct. |
| 2 | Sector | yes | `TickerScore.sector` (nulled for ETFs) | yes | **Blank.** |
| 3 | Rev (5y mini bars) | no | Step 1 annual revenue, cache-only | yes | **Empty box** (statements `[]`). |
| 4 | NI (5y mini bars) | no | Step 1 net income | yes | **Empty box.** |
| 5 | CFO (5y mini bars) | no | Step 1 CFO | yes | **Empty box.** |
| 6 | Moat | yes | `TickerMoat` manual rating | yes | **Blank** (the moat API rejects ETFs; a rating set before the guard would still show). |
| 7 | Value | yes | Step 3 verdict | yes | **Blank.** |
| 8 | Analysis | yes | `overall_score` / verdict pill | yes | **"ETF" neutral badge** (replaces the blank score). Correct. |
| 9 | Rating | yes | `/grades-consensus` via `_consensus_rating`, **live** on a stale cache (7 days) | yes | **"N/A"**, after a wasted live call per ETF per window (answers `[]`). Not wrong, but a dead column and a wasted call. |
| 10 | Mkt cap | yes | `TickerScore.market_cap` (the quote's `marketCap`, last cached, up to 7 days old) | no, but semantics differ | **Populated and roughly right** as a market-implied AUM, but differs from the AUM on the ETF page (up to 15%). |
| 11 | Beta | yes | profile `beta` | partly | **Populated, misleading** for bond and commodity ETFs (TLT 2.4). |
| 12 | P/E | yes | trailing P/E from `/ratios-ttm` | yes | **Blank** (no EPS). |
| 13 | Remove | no | action | no | Correct. |

How column sets are chosen: they are not. The header and the cells are hand-written JSX in one component, `COLUMN_COUNT
= 13` is a constant, and the loading skeleton spans it. Only the **sort rules** are per list (`localStorage`
`fathom-watchlist-sort-<id>`); there is no per-list or per-row-type column configuration. `WatchlistOut.monitored`
already tells the frontend whether a list is `E<number>` or `ETF`, and `WatchlistRowOut.is_etf` tells it which rows are
funds, so both inputs for a view choice exist. ETFs can sit on any list (the only guard is the 100-ticker cap), so mixed
lists are possible and must keep working.

Already persisted but not exposed on the row (`TickerScore` fields, read by `compute_ticker_score(cache_only=True)` which
the row already calls): `weinstein_stage` (+ `_since_date`, `_ma_slope_pct`, `_vs_ma_pct`, `_pending_direction`),
`bb_rsi_entry_signal`, `warren_active_signal_kind`, `warren_last_buy_fired_at`. Not on the row and not on `TickerScore`:
liquidity zones (`LiquidityZoneAnalysis`, `support_zones_json`/`resistance_zones_json`, per ticker and timeframe) and the
`etf_info` cache row.

## 6. Proposal

### (a) ETF page: a "Trading data" block

Place it in the **left column of the Overview, between "Fund facts" and "About this fund"**, as `DefinitionRow`s in the
same style (mono, right-aligned values). Sector weights stay alone in the right column. All values come from the
summary the page already loads, except one new field.

| Row | Source | Handling |
|---|---|---|
| 52-week range | summary `week52_low/high` (from `/quote`) | Omit if either is missing. |
| Distribution (TTM) | new `TickerSummaryOut.trailing_dividend` from profile `lastDividend`; yield = value / price | Omit when `null`, **omit when `0`** (GLD: "no distribution" is not worth a row; the existing Fund-facts rule already omits a 0-as-unknown). Show `$7.58 / 0.99%` for equity and bond funds. Caption that it is trailing, not an SEC yield. Under-reads for a fund younger than a year; hide when inception is under 12 months old. |
| Beta | summary `beta` | **Equity asset class only** (from `/etf/info`); omit for Fixed Income, Commodities, Alternatives and when the asset class is unknown. |
| Average dollar volume (20d) | summary `avg_dollar_volume_20d` | Omit if `null`. A liquidity read an ETF buyer cares about. Do not repeat average share volume (already in Fund facts). |
| Performance 1M / 6M / YTD / 1Y | summary `perf_*`, signed mono, `text-positive`/`text-negative` per the app's convention | `null` -> omit the cell. Hide 1Y when the fund is under a year old (FMP clamps young listings' longer horizons to since-listing). **Stale up to 7 days** (see item 3): either accept with an "as of" or compute from bars with the shared helper in (b). |

Considered and **not** recommended:

- Profile `marketCap` (contradicts the AUM row above it).
- `ipoDate` (disagrees with the `/etf/info` inception date on 3 of 6).
- Premium/discount to NAV: NAV is end-of-day (`updatedAt` hours old) while the header price is intraday, so the number
  is wrong during the session. Only valid against the last close; skip.
- Profile `averageVolume` (identical to `/etf/info`), sector/industry, address/phone/CEO, `range` string.

Size: S-M. Backend: one summary field (~5 LOC + a test). Frontend: a `TradingDataSection` plus formatter in
`lib/etfOverview.ts` (the file that already decides what to omit) and passing the summary into `EtfOverviewTab`
(~120 LOC with tests). Risks: summary and Overview are two requests, and the Overview must not block on the summary;
the 7-day performance lag; yield wording. No conflict with `docs/specs/` except the heading "Overview tab (FMP
`/etf/info` only)" in `etf-page.md`, which becomes untrue.

### (b) Recommended ETF column set for the ETF list

Recommended (14 columns including remove), every one from data already in the DB except two `/etf/info` facts:

| # | Column | Source | Notes |
|---|---|---|---|
| 1 | Ticker + fund name | existing | |
| 2 | Asset class | `/etf/info` (cached row) | Replaces the blank Sector. |
| 3 | Close | last cached daily bar (or `TickerLastClose`) | Label "Close" not "Price"; last completed session. |
| 4 | 1D % | bars: last / previous - 1 | Signed, coloured, sortable. |
| 5 | 1M % | bars | Sortable. |
| 6 | YTD % | bars | Sortable. |
| 7 | 1Y % | bars | Sortable; `—` under a year of history. |
| 8 | Stage | `TickerScore.weinstein_stage` | Existing `WeinsteinStagePill` (`labelSet="screener"`, "S1"-"S4"); **runs nightly for any tracked ETF, even on an unmonitored list**. Sort by stage rank. |
| 9 | BB+RSI | `TickerScore.bb_rsi_entry_signal` | Compact pill when active, otherwise `—`. Only monitored lists have data; unmonitored shows `—` with a "not tracked" tooltip. |
| 10 | Warren | `TickerScore.warren_active_signal_kind` | Compact pill reusing the Warren card's label/tone map. Same monitored-list caveat. |
| 11 | LP support % | `LiquidityZoneAnalysis` daily, nearest `support_zones[0].distance_pct` | Negative number = distance below price. Same caveat. |
| 12 | LP resist % | nearest `resistance_zones[0].distance_pct` | Positive. Two numeric columns sort cleanly, unlike one mixed "nearest zone" cell. |
| 13 | Expense | `/etf/info.expenseRatio` | `0.09%`; keep a real 0. Sortable. |
| 14 | Remove | existing | |

Optional, not in the minimal set: AUM (`/etf/info`, better than the quote's market cap), 5D/3M/6M (the same helper
computes them), weekly LP zones. Dropped as stock-only or misleading: Sector, Rev/NI/CFO, Moat, Value, Analysis, Rating,
Mkt cap, Beta, P/E. The mini revenue/earnings charts have no analogue for a fund.

Which rows get the ETF view: **rule-based, no toggle**: the ETF view is used when the list is the `ETF` list
(`ETF_WATCHLIST_NAME`) **or** the list is non-empty and every loaded row has `is_etf`; any other list keeps the stock
view. Mixed lists therefore stay stock lists (see (c)). Default ETF sort: 1M descending (the stock default is Analysis,
which is meaningless for funds). Sort state stays per list in `localStorage`; `SortableField`/`DEFAULT_DIRECTION`/
`watchlistSort.ts` gain the new fields.

Backend, ETF rows only (guarded by `score.is_etf`, so the stock-row payload and tests are untouched), in
`watchlist_data.py::_compose_row`:

- Add to `WatchlistRowOut`: `asset_class`, `expense_ratio`, `close`, `close_as_of`, `change_1d_pct`, `perf_1m_pct`,
  `perf_ytd_pct`, `perf_1y_pct`, `weinstein_stage` (+ since-date for the tooltip), `bb_rsi_entry_signal`,
  `warren_active_signal_kind`, `lp_support_distance_pct`, `lp_resistance_distance_pct`. The Weinstein/BB+RSI/Warren fields
  are straight copies from the `score` the row already holds.
- Returns from the cached daily bars through the **existing** read path (`clients/shared_bars_cache`, which handles the
  provisional-last-bar and close-aware freshness rules), via one small pure helper (`helpers/period_returns.py`) that the
  ETF page's performance row can reuse so the two surfaces never disagree. Do not write raw SQL against
  `SharedBarsCache`.
- LP distances: one cache-only read of `LiquidityZoneAnalysis` per ETF row (reuse `get_liquidity_zone_data`).
- `asset_class` and `expense_ratio` via `get_etf_overview`, inside the existing `_LIVE_FETCH_CONCURRENCY` semaphore like
  `_consensus_rating`. This is the only FMP traffic added: at most one `/etf/info` call per ETF per day (TTL
  `etf_info_staleness_days = 1`), only when the list is opened; a 100-ETF list is at most 100 calls (Starter allows
  300/min, the semaphore caps concurrency at 8). The `etf_info` group is off -> cache-only, the cells show `—`.
- Skip the consensus call for ETF rows (saves one wasted `/grades-consensus` per ETF per 7 days).

Frontend: a new `EtfWatchlistTable` next to `WatchlistTable`, plus extracting the shared pieces both need (the remove
cell, `SortableHead`, `HEAD_CLASS`, the skeleton). Do **not** build a generic column-definition framework for two
fixed layouts. Cell rules from the design system: mono right-aligned numbers, explicit sign, `—` when missing,
compact pills for stage/signals, no new colours.

Size: backend M (~200 LOC + tests), frontend M-L (~300 LOC + tests). Risks: see below.

### (c) ETF rows on non-ETF lists

Keep the stock view, and make the ETF rows honest rather than blank:

- **Rating:** skip the live call; render `—`.
- **Beta:** hide for ETF rows (it is only meaningful for equity funds and the row does not know the asset class without
  the `/etf/info` read; hiding is the safe default).
- **Mkt cap:** keep (it is a correct market-implied figure), accepting the small difference from the page's AUM.
- **Sector, Rev/NI/CFO, Moat, Value, P/E:** leave blank as today (a dash in each would add noise to a row that already
  carries the "ETF" badge in Analysis).
- No ETF-only columns appear on a stock list; to see them, put the ETF on the `ETF` list.

Size: S (~30 LOC backend, ~10 frontend). This is also worth doing on its own, independent of (b).

### Risks and conflicts

- **Stale spec line:** `docs/specs/weinstein-stage.md:337` says the Watchlist/Screener "existing Weinstein columns show only
  the stage". The Watchlist has had no Weinstein column since the trend cluster was removed on 2026-09-06. The new Stage
  column does not conflict, but the line should be corrected.
- **`docs/specs/etf-page.md`** needs updates: the Overview heading ("`/etf/info` only"), the "TTL: fetched only when an ETF
  Overview is opened (no nightly job)" paragraph (the list view also fetches), the "Watchlist rows" bullet (the ETF view
  replaces the Analysis-cell badge on ETF lists), and the Premium-vs-Starter tier note.
- **`docs/decisions.md`:** price/change columns were removed from the stock table on 2026-08-03 to keep the page
  cache-only. Reintroducing "Close"/"1D" on the ETF view from cached bars keeps that property, but should be recorded as
  a decision (and not extended to the stock table without one).
- **Data gaps, not bugs:** an ETF with no cached bars yet (new to the list) shows `—` until the next nightly; LP, BB+RSI and
  Warren only exist for monitored lists, so an ETF on an unmonitored list shows `—`; `etf_info` is blank for an ETF whose
  group is off with nothing cached.
- **Basis:** bar-derived returns are split-adjusted price returns, not total returns, and `/stock-price-change` may use a
  different basis (not verified); the ETF list and the page must use the same helper so they agree.
- **Unverified:** FMP's own tier for each endpoint (only the owner's recorded tiers), the basis of `beta`, and anything
  visual (no browser).
- **No data-group or registry change** is needed: `/profile`, `/quote`, `/stock-price-change` and `/etf/info` are already
  mapped; nothing here calls a bulk or batch endpoint.

## Proposed minimal change list

1. **(c) Honest ETF rows on stock lists** (S, independent, lowest risk): skip `_consensus_rating` for ETFs (`—`), hide
   Beta for ETF rows. ~40 LOC with tests.
2. **(a) "Trading data" block on the ETF Overview** (S-M): add `trailing_dividend` to the summary; `TradingDataSection`
   with 52-week range, distribution (TTM), beta (equity only), 20-day dollar volume, performance; update
   `docs/specs/etf-page.md`. No new FMP call, no table.
3. **(b) ETF list view** (M-L, two commits: backend row enrichment + shared period-returns helper; then the frontend
   `EtfWatchlistTable` with the rule-based switch and the new sort fields). Update `etf-page.md`, `weinstein-stage.md`
   (stale line) and `docs/decisions.md`.
4. Optional later: reuse the period-returns helper on the ETF Overview so its performance row is not up to 7 days stale;
   short-circuit `get_summary` for ETFs (existing known limit).
