# ETF page feasibility investigation (2026-10-01)

Report-only. No code or DB changes. FMP was probed live with a throwaway script outside the repo
(raw responses never touched `fathom.db`); DB reads were read-only. Browser rendering was **not**
verified (no browser available) -- where a UI behavior is stated, it is inferred from the code and
from the cached rows of the two ETFs already in the DB (SPY, TECL).

Scope: US ETFs only.

## Summary

- All five FMP ETF endpoints work on the current key. **Two calls are enough** for the info block:
  `/etf/info` (profile + AUM + expense ratio + embedded sector weights) and `/etf/holdings`.
  `/etf/sector-weightings` returns exactly what `/etf/info`'s `sectorsList` already contains
  (verified identical on SPY), so it is redundant.
- ETF price/technical coverage is mostly already there: Weinstein runs nightly for every tracked
  ticker (an ETF becomes tracked as soon as its profile is cached by viewing it or watchlisting it),
  and is computed on demand when missing/stale. **LP zones, BB+RSI and Warren are watchlist-only
  (`W1`-`W5`) and cache-only** -- an ETF outside those lists shows "not tracked" cards.
- The ticker page has **no ETF awareness at all** today (the only ETF handling is the Screener
  filter and the score/Step 5 short-circuits). An ETF opens the full stock-shaped page; most tabs
  are empty, and the header shows a misleading sector/industry line.
- Detection is reliable: `profile.isEtf || profile.isFund`, already exposed to the frontend as
  `TickerSummaryOut.is_etf`.
- Smallest viable change: one new data group (`etf_data`), two client methods, two new cache keys in
  the existing `FundamentalsCache` (no new table, no new cron job), one overview endpoint, and an
  `is_etf` branch in the existing ticker page. No new route.

## 1. FMP ETF endpoints (live, 2026-10-01)

Base `https://financialmodelingprep.com/stable`. The app's recorded plan is Ultimate; **the required
tier of these endpoints could not be verified** (FMP's pricing/docs pages return 403 to WebFetch and
the API itself does not report tiers). They work on the current key, so the tier is <= the account's
actual plan. Recommend seeding `Premium` (conservative; no effect while the plan is Ultimate) and
confirming against the FMP pricing page by hand.

| Endpoint | SPY | XLK | SMH | QQQ | TLT | GLD | Notes |
|---|---|---|---|---|---|---|---|
| `/etf/info` | 200, 2.5 KB | 200, 1.6 KB | 200, 1.1 KB | 200, 2.0 KB | 200, 1.0 KB | 200, 1.3 KB | One row. `[]` for non-ETFs (AAPL, BRK-B, closed-end fund PTY). |
| `/etf/holdings` | 200, **141 KB**, 505 rows | 200, 21.5 KB, 77 | 200, 7.6 KB, 27 | 200, 30 KB, 106 | 200, 14.8 KB, 49 | 200, 243 B, **1 row** | Sorted by weight desc. |
| `/etf/sector-weightings` | 12 rows | 3 | 1 | 11 | 1 (`Cash & Others` 100%) | 1 (`Cash & Others` 100%) | Identical to `/etf/info.sectorsList`. |
| `/etf/asset-exposure` | 56 rows | 45 | 20 | 52 | 35 | 16 | Which *other ETFs* hold this ETF (reverse lookup). Not relevant. |
| `/etf/country-weightings` | 8 | 5 | 7 | 8 | 2 | `[]` | `weightPercentage` is a **string** like `"97.79%"`. Not needed. |

Fields:

- `/etf/info`: `symbol, name, description (full prose), isin, assetClass, securityCusip, domicile,
  website, etfCompany (issuer), expenseRatio (percent, 0.09 = 0.09%), assetsUnderManagement (USD),
  avgVolume, inceptionDate, nav, navCurrency, holdingsCount, isActivelyTrading, updatedAt,
  sectorsList[{industry, exposure}]`.
- `/etf/holdings`: `symbol, asset (the holding's ticker), name, isin, securityCusip, sharesNumber,
  weightPercentage, marketValue, updatedAt`.
- `/etf/sector-weightings`: `symbol, sector, weightPercentage`.

Data quality:

- **Equity ETFs (SPY/XLK/SMH/QQQ):** complete and current -- holdings `updatedAt` 2026-09-30 to
  2026-10-01, weights sum to exactly 100.0, top-10 concentrations look right (SPY 38.7%, XLK 64.5%,
  SMH 67.3%, QQQ 46.6%). Sector weights sum to 100.
- **Quirks:** `holdingsCount` != row count (SPY 504 vs 505, XLK 74 vs 77, QQQ 102 vs 106, SMH 26 vs
  27) because cash/derivative lines are included as rows. QQQ has a `-0.138%` contra-future row.
  Cash/futures rows have an empty `asset` (or a junk one: `IXTZ6`, `2602335D`). XLK reports 0.12%
  "Energy" (classification noise from the sector provider). SPY `AAPL`/`NVDA` etc. names are
  upper-case on SPDR funds and mixed-case on others.
- **Bond ETF (TLT):** holdings are individual Treasuries -- `asset` is empty, `name` reads
  "TREASURY BOND 4.75% 05/15/2055". Real weights but no tickers, so no per-holding link.
  `sectorsList` is a single `Cash & Others 100%` -- meaningless, hide it for non-Equity.
  `assetClass` = "Fixed Income".
- **Commodity ETF (GLD):** `holdingsCount` 0; holdings is one synthetic row ("Physical Gold",
  weight 100), `updatedAt` 2026-09-24 (a week old vs. daily for equity funds). Sector =
  `Cash & Others 100%`. `assetClass` = "Commodities". Country weightings `[]`.
- Other spot checks: IBIT `Alternatives`, USO `Commodities`, VXX/SMHU (ETNs) come back from
  `/etf/info` with 2/0 holdings; mutual fund VFIAX returns full info (504 holdings).

Payload: SPY holdings is 141 KB for one call (the app's `FundamentalsCache.raw_json` stores whatever
the fetch lambda returns), so the fetch lambda should **trim to top-N + count + total weight +
as-of** before caching (~3-4 KB). QQQ 30 KB is the next largest.

## 2. What happens today with an ETF ticker

Evidence: SPY and TECL are already in the DB (TickerScore + cache rows), plus code reading.

- **Ticker page (`/tickers/XLK`).** `GET /summary` works (profile returns `isEtf: true`).
  `TickerTabsContainer` renders the standard 9 tabs with no ETF branch (the frontend's only
  `is_etf` use is the Screener filter).
  - Header: `ticker_summary.py` passes the raw FMP sector/industry through (only `TickerScore.sector`
    is nulled for ETFs), so **every ETF's header eyebrow reads "Financial Services · Asset
    Management"** (all six test ETFs return exactly that) -- misleading.
  - Cached data for SPY/TECL: ~20 statement types cached as `[]` (income statement, balance sheet,
    cash flow, key metrics, ratios, enterprise values, growth, estimates, segmentation, grades,
    price targets). Financials/Ratios/Analysis/Valuation/Analyst Ratings tabs therefore have nothing
    to show. Scoring is *honest* rather than wrong: SPY row = Steps 1/2/4 `insufficient_data`,
    Step 5 `not_supported` (explicit ETF branch), no overall score, no valuation.
  - Still rendered for ETFs: Moat pill/tab (manual rating is allowed -- see risk 7), Fair Value pill,
    Speculative Growth pill, "Next earnings: Not yet announced" (SPY has an `/earnings` history of
    null-actuals, handled in `helpers/earnings.py`).
  - Works correctly: Chart (daily bars, hourly bars, dividend markers), Technical Weinstein card,
    header price/change/market cap/beta, Summary description.
- **Watchlist add.** `POST /watchlists/{id}/tickers` does no validation of any kind, so an ETF adds
  fine. Rows come from `compute_ticker_score(cache_only=True)`; an ETF row has blank/"insufficient
  data" step scores, blank overall, and no ETF marker (`WatchlistRowOut` has no `is_etf`).
  `_consensus_rating` makes one live `/grades-consensus` call per stale ETF (returns `[]`).
- **Ticker search.** `search_tickers` returns ETFs (and CBOE-listed ETNs) like any symbol -- the
  search endpoints return no type field, so there is no ETF marker in the dropdown. US filtering
  works (`AMEX`/`NASDAQ`/`CBOE` are in `US_EXCHANGES`).
- **Screener.** Already handled: `TickerScore.is_etf` + `excludeEtfs` hard-exclude ETFs
  (client-side) and `/screener/meta` excludes them from the "X of Y" count for `universe=all`. No
  gap.
- **Nightly jobs.** Once an ETF has a cached profile it is in `load_full_tracked_universe`, so
  fundamentals fetch, price-target snapshot, last-close snapshot, corporate-events and score
  recompute all include it. Fundamentals fetch has **no ETF skip**: ~25 FMP calls per ETF per
  7-day staleness window, all returning `[]` (cheap in absolute terms; pure waste).
- **Sectors heatmap.** Unaffected. The 11 sector ETFs have bars cached nightly (1258 daily bars
  each) but no profile/TickerScore until someone opens them.

## 3. Technical coverage

| Engine / job | Universe | ETF on a watchlist | ETF merely viewed |
|---|---|---|---|
| Weinstein (`nightly_trend_calculation`, 00:05) | full tracked universe (index + profile-cached + scored + any watchlist) | nightly | nightly (viewing caches the profile) + on-demand compute if missing/stale |
| Liquidity Zones (00:15) | `W1`-`W5` union only | yes | no -- "not tracked" card, cache-only |
| BB+RSI (00:20) / Warren (00:25) | `W1`-`W5` union only | yes (60m bars via FMP `1hour`) | no -- cache-only |
| Sector heatmap (00:35) | 11 SPDR sector ETFs, fixed | -- | -- |
| Market breadth (00:40) | S&P 500 constituents (+ per-sector buckets) | no | no |
| Monthly momentum | manually Moat-rated tickers only | no | no |
| Pullback / Near-term / Reversal cards | **deleted** with the trend-structure removal (2026-10-01 commits) | -- | -- |

- The brief's "pullback card" no longer exists. Technical tab today = Weinstein card + BB+RSI +
  Warren + Liquidity Zones.
- Making the ETF technicals non-stale needs **only watchlist membership**: put the curated ETFs on
  `W1`-`W5` (zero code) or add a dedicated ETF list (see proposal). The three jobs each define
  `WATCHLIST_NAME_PATTERN = ^W[1-5]$` locally (plus the backfill script) -- not centrally in
  `data/watchlists.py`, contrary to what CLAUDE.md implies.
- Capacity: W1-W5 already hold 105 distinct tickers; a dozen to two dozen ETFs is a small increment.
- **Price-history chain correction:** it is **FMP only** -- Massive was removed in Phase 6a and Yahoo
  in Phase 6b (2026-09-26); there is no fallback anywhere (`docs/specs/fmp-data-and-bar-cache.md`,
  `clients/daily_bar_sources.py`). Confirmed live: `/historical-price-eod/full` returns clean bars
  for SMH and GLD, `/historical-chart/1hour` for XLK and TLT. Routing is by listing exchange
  (`is_us_listed`; `AMEX`/`NASDAQ`/`CBOE` = US); a ticker with no cached profile defaults to US.
  ETFs go through the same `SharedBarsCache` / `daily_prices` / `intraday_bars` groups as stocks.

## 4. ETF detection

- Source: FMP `/profile` -- `isEtf` and `isFund` (separate booleans).
- Live results: SPY, XLK, SMH, QQQ, TLT, GLD, USO, IBIT, SPYG, ARKK, VXX (ETN), SMHU (ETN) ->
  `isEtf: true`. PTY (closed-end fund) and VFIAX (mutual fund) -> `isFund: true` only. AAPL, BRK-B ->
  both false. 12/12 ETFs/ETNs flagged by `isEtf`, 14/14 products by `isEtf || isFund`, no stock
  false positives in the sample. The app's existing rule is already `isEtf || isFund`.
- Already plumbed: `ticker_summary.py` -> `TickerSummaryOut.is_etf` -> frontend type
  (`lib/api/types.ts`), and `TickerScore.is_etf` -> Screener. `classify_company_type(..., is_fund)`
  returns `"ETF"` first.
- Secondary check: `/etf/info` returns `[]` for non-ETFs and closed-end funds -- use it to decide
  whether to render the info block (a CEF page shows technicals only).
- Where to apply: a single `if (data.is_etf)` branch in `TickerTabsContainer` (tab set + header
  variant). Backend needs no routing change.

## 5. Gating (Data Groups)

No existing group covers these endpoints (`profile_quote` is stock profile/quote/search).

Registration, per `core/data_groups.py` and `tests/test_data_groups_registry.py`:

- `GROUPS["etf_data"] = GroupMeta("ETF info & holdings", default_tier="Premium" (unverified),
  default_enabled=True, live=True, feeds=("ETF page info block",))`.
- `ENDPOINT_GROUP["/etf/info"] = ENDPOINT_GROUP["/etf/holdings"] = "etf_data"`.
- `STATEMENT_TYPE_GROUP["etf_info"] = STATEMENT_TYPE_GROUP["etf_holdings"] = "etf_data"`.
- `PROBE_ENDPOINTS["etf_data"] = ("/etf/info", {"symbol": "SPY"})`. Note the convention says
  "always AAPL", but AAPL returns `200 []` on this endpoint, so use SPY here (see risk 2).
- Toggle/status/tier UI is generic (Settings > FMP data groups reads `GROUPS`), so it appears
  automatically. Frontend: add the group to `lib/dataGroups.ts` `TAB_GROUPS` for the ETF info tab.
- Off = cache-only (`get_or_fetch` serves the stale row); the card shows the existing
  `GroupOffBadge`.
- Do not register `/etf/sector-weightings`, `/etf/asset-exposure`, `/etf/country-weightings`
  (unused endpoints; the registry test only fails on endpoints used in code).

## 6. Proposal

### Layout (ETF branch of the existing `/tickers/[symbol]` page)

- **Header (ETF variant):** name, ticker, exchange, price/change; drop the sector/industry eyebrow
  (replace with issuer + asset class from `/etf/info`), and hide Assessment / Moat / Fair Value /
  Speculative Growth / Perf-vs-SPY / "Next earnings". Keep the Weinstein stage pill and
  Add-to-watchlist. Refresh button keeps working (it clears stock caches -- consider hiding).
- **Tabs:** `Overview` (default), `Technical`, `Chart` -- i.e. hide Financials, Ratios, Analysis,
  Valuation, Moat, Analyst Ratings.
- **Overview:** info strip (issuer, expense ratio, AUM, inception, NAV, holdings count, asset
  class, website) + description + top holdings table (top ~15-25: name, linked ticker when `asset`
  is a clean US-looking symbol, weight; "top 10 = X%" footer) + sector weights (small horizontal
  bars, only when `assetClass` is Equity; follow the single-series bar chart style memory) + "as of"
  from holdings `updatedAt`. Technical + Chart tabs are the existing components unchanged.
  Optionally embed the Weinstein pill/mini-chart on Overview so the page is price-first.

### Smallest change list

| Area | Change | Size |
|---|---|---|
| Backend: client + gate | `fmp_client.get_etf_info/get_etf_holdings`; `etf_data` group, endpoint + statement-type maps, probe canary; `Settings.etf_staleness_days` (default 1-2; do not hardcode at call site) | S (~60 LOC) |
| Backend: data/API | `data/etf_data.py::get_etf_overview` via `get_or_fetch` with a **trimming fetch lambda** (top N + count + total weight + as-of; sector list from `/etf/info`, hidden when not Equity); `EtfOverviewOut` schema; `GET /api/tickers/{t}/etf-overview` (null when `/etf/info` is empty or group off with no cache) | M (~150 LOC) |
| DB | **None.** Reuse `FundamentalsCache` keys `(ticker, "etf_info"/"etf_holdings", "latest")`. Data-group row is lazy-seeded. No cron job, so no `CRON_JOB_NAMES`/crontab changes | -- |
| Routing | **None.** Keep `/tickers/[symbol]`; branch on `summary.is_etf` | -- |
| Frontend | ETF tab set + header variant; `EtfOverviewTab` (info strip, holdings table, sector bars); `useEtfOverview` hook; types; `TAB_GROUPS`/`dataGroups.ts` entry | M (~400 LOC) |
| Watchlist / Screener | Screener: nothing. Watchlist: add `is_etf` to `WatchlistRowOut`, render "ETF" instead of blank score cells. Curated set: **v0 = put ETFs on an existing W list (no code)**; v1 = a dedicated list (e.g. `ETF`) by widening the pattern to `^(W[1-5]\|ETF)$` in the 3 nightly jobs + backfill (extract one shared constant while there) | S (~60 LOC) |
| Nightly efficiency (optional) | Skip `is_etf` tickers in `nightly_fundamentals_fetch` and price-target snapshot (saves ~25 empty FMP calls/ETF/week) | S (~20 LOC) |
| Search (optional) | No type field from FMP search; skip for v1 | -- |
| Tests | Registry/group-metadata tests (largely automatic); client + `get_etf_overview` with in-memory engine + monkeypatched `fmp_client` (trim logic, non-equity sector hiding, empty info -> null, group off -> cache-only); route test; frontend: tab-set branch, header variant, holdings/sector rendering, `tsc`/`eslint` | M (~350 LOC backend, ~250 frontend) |
| Docs | New `docs/specs/etf-page.md`; update `fmp-data-and-bar-cache.md` (endpoint inventory 35 -> 37, new group), `CLAUDE.md` group list, `sector-heatmap.md` (labels now links), `docs/decisions.md` | S |

### Sectors heatmap -> ETF page links

Straightforward. `SectorHeatmapGrid.tsx` renders ticker labels as plain text with a comment saying
they are deliberately not links "because /tickers/<ETF> still renders the stock-shaped page"
(echoed in `docs/specs/sector-heatmap.md`). Once the ETF branch exists: wrap the label in a
`Link` to `/tickers/<ETF>` (honour the app's new-tab convention), update the component test, and
amend the spec line. Bars for all 11 funds are already cached nightly, so the first Weinstein
compute is local. Side effect: the first open caches the profile, which adds that ETF to the full
tracked universe (nightly fundamentals fetch etc.) unless the ETF skip above is built.

## Risky / inconsistent with docs and the brief

1. **Brief vs. code: price chain.** There is no FMP -> Massive -> Yahoo chain; FMP is the sole
   source since P6b. **Brief vs. code: "pullback card"** was removed with trend-structure. The
   sector-heatmap spec already notes the ETF page "was never shipped" -- this is that follow-up.
2. **Tier unverified, canary convention.** `etf_data`'s required tier is a guess. The `_canary_params`
   logic swaps in AAPL on a symbol-scoped 402; AAPL returns `200 []` on `/etf/info`, so a real
   plan-level restriction would only be recognised if AAPL also 402s (likely, not tested). Probe
   with SPY and treat as a known deviation from "canary is always AAPL".
3. **Holdings payload.** 141 KB for SPY if cached untrimmed; trim in the fetch lambda.
4. **Data quirks to render defensively:** `holdingsCount` != rows; negative/cash/future rows; empty
   or junk `asset`; GLD/non-equity holdings dated up to a week old; non-Equity sector weights are a
   meaningless "Cash & Others 100%"; `country-weightings` uses percent strings (not used).
5. **Stock-shaped page leaks today:** misleading "Financial Services · Asset Management" header on
   every ETF; stock pills/tabs on empty data; an ETF with no cached profile triggers ~25 empty
   stock-statement fetches on first view and nightly thereafter.
6. **Technicals are watchlist-gated.** LP/BB+RSI/Warren have no on-demand path; an ETF not on a
   `W1`-`W5` list shows "not tracked". The `W[1-5]` pattern is duplicated in four files, not
   centralised as CLAUDE.md suggests.
7. **No ETF guard on Moat.** `PUT /tickers/{t}/moat` accepts any ticker, and the monthly momentum
   universe is "every Moat-rated ticker", so a Moat rating set on an ETF would put it into the
   stock momentum snapshot. Hide the Moat tab/pill on the ETF page (and optionally reject in the
   API).
8. **Minor doc/DB drift noticed:** the live `datagroupsetting` table still has an `insider` row (the
   group was deleted from code 2026-09-27) and `news` is enabled there although CLAUDE.md says it is
   seeded/tested off. Not related to this feature.
9. **Unverified:** actual rendering of each stock tab for an ETF (no browser); only inferred from the
   code and SPY/TECL cached rows.
