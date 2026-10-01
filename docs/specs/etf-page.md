# ETF page

US ETFs get their own variant of the ticker page (`/tickers/<ETF>`), built for technical trading and for identifying an
ETF's theme. Built 2026-10-01 from `docs/etf-page-investigation-2026-10-01.md` (where the two differ, the code wins:
the investigation proposed two endpoints and a holdings table; only `/etf/info` was built). No Ultimate-tier endpoint is
used. US ETFs only; non-US ETFs, holdings, country weights and "which ETFs hold this stock" are out of scope.

## Detection and routing

`TickerTabsContainer` reads `TickerSummaryOut.is_etf` (FMP profile `isEtf || isFund`, the app's one existing rule) and
renders `EtfTickerPage` instead of the stock page. No new route. The stock branch is untouched (same header, nine tabs,
same lazy tab mounting). The summary request is still the gate for both, so a bad ticker still 404s before anything else.

## Page structure

- **Header** (`EtfHeader`): fund name, `TICKER · EXCHANGE`, price and daily change, a 13px tertiary caption
  "Exchange-traded fund" plus the asset class from `/etf/info` (asset class is dropped while that loads or when it is
  unavailable), and one primary "Add to watchlist" button. Deliberately absent: the sector/industry eyebrow (FMP reports
  every ETF as "Financial Services · Asset Management"), the Assessment, Moat, Fair value, Speculative growth and 5Y vs
  SPY pills, the index-membership pill, the Weinstein pill, the next-earnings line and the Refresh button (it clears
  stock caches).
- **Tabs, in order:** Overview, Technical, Chart (`ETF_TICKER_TABS` in `lib/tickerTabs.ts`). No Financials, Ratios,
  Analysis, Valuation, Economic Moat or Analyst Ratings tab or card. A shared `TickerTabs` takes the tab set as a prop.
- **Moat cannot reach an ETF.** `PUT /api/tickers/{t}/moat` answers 400 for a ticker the app knows is an ETF/fund, and
  `data/momentum_data.py` additionally drops `TickerScore.is_etf` rows from the monthly momentum universe (covers a
  rating set before the guard).

## Overview tab (FMP `/etf/info` only)

`GET /api/tickers/{t}/etf-overview` -> `EtfOverviewOut`. Two columns, 7/5 (`lg:grid-cols-12`).

- **Left:** "Fund facts" as `DefinitionRow`s (mono, right-aligned values): issuer, asset class, expense ratio (percent,
  `0.09%`), assets under management (compact money), holdings count, NAV, average volume, inception date, domicile.
  Then "About this fund": the description as plain text. A fact FMP did not return is **omitted**, not blank; a `0` that
  FMP uses for "unknown" (GLD's `holdingsCount`, NAV, AUM, volume) is omitted too (the expense ratio keeps a real 0).
- **Right:** "Sector weights" as single-series (`series-1`) bars, largest first, exact figure printed. Shown only for
  equity funds (`assetClass` Equity, or unknown with a real sector list). For any other asset class, or when the only
  entry is "Cash & Others 100%" (what FMP returns for bond and commodity funds), the section shows "Sector weights are
  not shown for funds that don't hold stocks." instead. "Fund data as of <FMP updatedAt date>" sits below.
- **States** (`status` on the body, never a 5xx for an FMP problem): `ok`; `unavailable` with `reason` `group_off`
  (group off, master off, above plan or restricted, and nothing cached) or `fetch_failed` (call failed and nothing
  cached); `no_data` (FMP answered `[]`: a stock or closed-end fund). A failed refetch with a cached row serves the stale
  row; an off group serves its cached row even if stale. The Technical and Chart tabs never depend on this call.

## Technical and Chart tabs

The existing components, nothing restored. Audited for stock-only dependencies: the Weinstein card, BB+RSI, Warren, LP
zones and the chart are all bar-based, so none needed hiding. Adapted:

- **Chart:** the Earnings overlay toggle is hidden and forced off (a fund reports no earnings); dividends, EMAs, BB, LP,
  BB+RSI and Warren overlays are unchanged.
- **BB+RSI, Warren and Liquidity Zones** run nightly only for monitored watchlists, so an ETF not on one shows the
  existing "Not tracked" state with ETF copy (`notTrackedMessage(check, isEtf)` in `lib/monitoredWatchlists.ts`, built from
  `ETF_WATCHLIST_NAME` and `MONITORED_WATCHLISTS_PHRASE`) pointing to the "ETF" list. Weinstein computes on demand.

## Data: the `etf_info` data group

- Group `etf_info` ("ETF info"), feeds the Overview tab. Endpoint `/etf/info` only (`ENDPOINT_GROUP`); cache key
  `FundamentalsCache(ticker, "etf_info", "latest")` (`STATEMENT_TYPE_GROUP`). No new table, no cron job.
- **Tier: `Premium`, unverified.** FMP's docs and pricing pages return 403 to our fetcher, and the API does not report
  tiers, so the lowest tier FMP lists it on could not be confirmed. The repo's tiers are Starter/Premium/Ultimate; if FMP's
  docs badge it "Basic" that is the repo's Starter. Premium was chosen as the conservative guess (it has no effect while
  the plan is Ultimate and is editable in Settings > FMP data groups); the 402 safety net corrects a wrong guess at
  runtime.
- **Canary SPY, not AAPL** (`PROBE_ENDPOINTS["etf_info"]`, and `CANARY_SYMBOL_OVERRIDES` for the 402 canary in
  `FMPClient._handle_plan_restriction`): AAPL answers `200 []` on `/etf/info`, which could never confirm a plan-level 402.
  This is the one exception to "the canary is always AAPL".
- **TTL: `Settings.etf_info_staleness_days = 1`.** The row is fetched only when an ETF Overview is opened (no nightly
  job), it is one small row (~1-2.5 KB), and NAV, AUM and average volume move daily while the descriptive fields do not
  change. One day keeps the numbers current without a call per view; never hard-code it at a call site.
- Off = cache-only (stale row served); the ticker-page badge (`TAB_GROUPS.overview = ["etf_info"]`) shows "not
  refreshing -- as of <date>".

## Add to watchlist

`EtfWatchlistButton` (ETF page only; stock pages keep `AddToWatchlistButton`). One click calls
`POST /api/tickers/{t}/etf-watchlist`: adds to the watchlist named **"ETF"**, creating it if missing, idempotent
(`added: false` for a member, even at the cap). At the 100-ticker cap it answers 400 with a message naming the list and
`n/100`, shown under the button. Once the ETF is on any **monitored** list the button becomes a quiet, disabled ghost
"On watchlist <name>" with a check icon (first name in natural order, `+N` when on several); removal stays on the
Watchlists page. Which lists are monitored comes from `WatchlistOut.monitored` (backend `is_monitored_watchlist_name`),
so the frontend never re-implements the naming rule. An ETF only on an unmonitored list still shows the primary button.

## Related changes

- **Search:** `TickerSearchResult.is_etf` renders a small "ETF" badge. FMP's search has no security-type field and a
  per-result `/profile` call would cost calls and add every searched ticker to the tracked universe, so the flag comes
  from local knowledge only (`data/etf_data.py::known_etf_tickers`: a cached profile with `isEtf`/`isFund`, or a
  `TickerScore.is_etf` row). An ETF never opened, scored or watchlisted is therefore **not labelled** until its page is
  first viewed.
- **Watchlist rows:** `WatchlistRowOut.is_etf` (from the score row) shows an "ETF" badge in the Analysis cell in place of
  the blank score.
- **Sectors heatmap:** each sector label is one `Link` to `/tickers/<ETF>` (new tab, like other ticker links).
- **`nightly_fundamentals_fetch`** skips known ETFs/funds when it builds its own universe
  (`load_fundamentals_fetch_universe`); an explicit `--tickers` list is still honoured. The score recompute, momentum and
  search still use the full tracked universe.

## Known limits

- `/summary` for an ETF still runs the stock cascade (statements, ratios, step 2/3 scoring), all answered `[]`: about ten
  wasted cached calls per ETF per window. Cutting it needs an `is_etf` short-circuit inside `get_summary`; not done.
- The caption says "Exchange-traded fund" for every `isEtf || isFund` ticker, including a mutual fund or closed-end fund.
