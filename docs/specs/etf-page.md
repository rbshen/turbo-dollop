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

## Overview tab (FMP `/etf/info`, plus a Trading data block read from cache, after an on-demand bar warm-up)

`GET /api/tickers/{t}/etf-overview` -> `EtfOverviewOut`. Two columns, 7/5 (`lg:grid-cols-12`). The fund facts, About text
and sector weights come from FMP `/etf/info`; the **Trading data** block (below) is computed from rows the app already
caches and adds no FMP call.

- **Left:** "Fund facts" as `DefinitionRow`s (mono, right-aligned values): issuer, asset class, expense ratio (percent,
  `0.09%`), assets under management (compact money), holdings count, NAV, average volume, inception date, domicile.
  Then "Trading data" (next section), then "About this fund": the description as plain text. A fact FMP did not return is
  **omitted**, not blank; a `0` that FMP uses for "unknown" (GLD's `holdingsCount`, NAV, AUM, volume) is omitted too (the
  expense ratio keeps a real 0).
- **Right:** "Sector weights" as single-series (`series-1`) bars, largest first, exact figure printed. Shown only for
  equity funds (`assetClass` Equity, or unknown with a real sector list). For any other asset class, or when the only
  entry is "Cash & Others 100%" (what FMP returns for bond and commodity funds), the section shows "Sector weights are
  not shown for funds that don't hold stocks." instead. "Fund data as of <FMP updatedAt date>" sits below.
- **States** (`status` on the body, never a 5xx for an FMP problem): `ok`; `unavailable` with `reason` `group_off`
  (group off, master off, above plan or restricted, and nothing cached) or `fetch_failed` (call failed and nothing
  cached); `no_data` (FMP answered `[]`: a stock or closed-end fund). A failed refetch with a cached row serves the stale
  row; an off group serves its cached row even if stale. The Technical and Chart tabs never depend on this call.

### Trading data block (2026-10-02)

`EtfOverviewOut.trading_data` (`EtfTradingDataOut`, built by `data/etf_data.py::_trading_data`), rendered by
`EtfOverviewTab` between Fund facts and About this fund with the same `DefinitionRow` style, a sentence-case section
title and a 13px tertiary caption (`lib/etfOverview.ts::tradingDataRows` / `tradingDataCaption`). It is built only when
`status` is `ok` (the unavailable and no-data states show their message alone) and is **None, and the section hidden,
when every row is omitted**. No new endpoint, table or cron job: every input is a cache-only read; the one possible FMP call is the on-demand daily-bar warm-up described under "Bar coverage" (2026-10-02).

| Row | Source | Omitted when |
|---|---|---|
| 1M, YTD, 1Y performance | cached daily bars (`SharedBarsCache`, interval `1d`) via `clients/shared_bars_cache.py::read_cached_completed_daily_bars` and `scoring/etf_returns.py::compute_window_returns` | no bar reaches back far enough for that window, bars are stale, or the value rounds to 0.00 |
| 52-week range | cached `quote` row (`yearLow` / `yearHigh`) | either end missing or 0 |
| Average volume (30d), average dollar volume (20d) | the same cached bars (30 calendar days of volume; close x volume over the last 20 bars) | no bars, or 0 |
| Distribution yield (TTM) | cached `profile` `lastDividend` / current price (cached quote price, else the last bar close), shown with the per-share amount | `lastDividend` null, zero or negative, or no price |
| Beta | cached `profile` `beta` | asset class (from `/etf/info`) is not Equity (bond, commodity, other, unknown), or 0 |

- **Performance basis.** Split-adjusted **price** return, not total return: FMP's daily bars are not dividend-adjusted, the same
  basis the Sector Heatmap uses (`docs/specs/sector-heatmap.md`), and the same calendar-offset windows (last close on/before
  `anchor - 1 month` / `1 year`; YTD base is the prior year's last close). It does **not** read the 7-day-cached
  `price_change` row, so it is never a week old. The anchor is the newest completed-session bar; the caption names its date.
- **Bar coverage.** The read itself is a pure cache read (it never fetches, writes or widens the shared cache). Since
  2026-10-02 the Overview request first runs `_warm_daily_bars`: when the shared daily-bar cache holds none or is behind the
  last completed session (a first view, or an ETF that left the nightly universe 30 days after its last view), it fetches
  and caches them through `get_or_fetch_bars` (one FMP call, only then, never from a nightly job; a failure is swallowed
  and the block simply stays as it was). An ETF in the nightly universe always has current bars, so it costs nothing. The read covers 400 calendar days, so a 1Y window needs a bar on/before `anchor - 1 year`: a cache only
  one year wide, or a fund younger than a year, omits 1Y (never a clamped since-listing value). A bar dated after the last
  completed session (an in-progress one) is dropped, as is a last bar written before its own session's close (the
  provisional-bar rule); a newest bar more than 5 calendar days behind the last completed session omits every
  performance row.
- **Distribution.** FMP's profile `lastDividend` is the **trailing-12-month** distribution per share, not the last payment
  (verified in `docs/etf-profile-and-watchlist-columns-2026-10-02.md`), so the row is labelled "Distribution yield (TTM)" and
  the caption says it is not an SEC yield. It under-reads for a fund listed less than a year; that is not special-cased.
- **Deliberately not shown:** the profile's `marketCap` (it contradicts the AUM in Fund facts; AUM stays the only size
  figure), the profile's `averageVolume` (identical to Fund facts' value). "Average volume (30d)" here is the bar-derived
  30-calendar-day figure and so differs from Fund facts' `/etf/info` "Average volume" (which is closer to a 50-63 day average).

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
- **Tier: `Starter`**, the owner's recorded value (Settings > FMP data groups, 2026-10-02), now also the code default
  (`GROUPS["etf_info"]`). It is not FMP-verified: FMP's docs and pricing pages return 403 to our fetcher and the API does
  not report tiers. The code default only matters when the row is first created: `core/data_groups.py::_seed` creates
  *missing* rows and never rewrites an existing one, so a live DB value (Premium, Starter or anything else) is left alone.
  The tier is editable in Settings and the 402 safety net corrects a wrong value at runtime. (Until 2026-10-02 the seed was
  Premium, a conservative guess.)
- **Canary SPY, not AAPL** (`PROBE_ENDPOINTS["etf_info"]`, and `CANARY_SYMBOL_OVERRIDES` for the 402 canary in
  `FMPClient._handle_plan_restriction`): AAPL answers `200 []` on `/etf/info`, which could never confirm a plan-level 402.
  This is the one exception to "the canary is always AAPL".
- **TTL: `Settings.etf_info_staleness_days = 1`.** The row is fetched on demand: when an ETF Overview is opened and the
  cached row is older than one day (a cache hit makes no call). There is no nightly job for it and
  `nightly_fundamentals_fetch` skips ETFs. It is one small row (~1-2.5 KB), and NAV, AUM and average volume move daily while
  the descriptive fields do not change, so one day keeps the numbers current without a call per view; never hard-code it
  at a call site. The Trading data block reads the cached `etf_info` row only through the same call (for the asset class).
- Off = cache-only (stale row served); the ticker-page badge (`TAB_GROUPS.overview = ["etf_info"]`) shows "not
  refreshing -- as of <date>".

## Add to watchlist

`EtfWatchlistButton` (ETF page only; stock pages keep `AddToWatchlistButton`). One click calls
`POST /api/tickers/{t}/etf-watchlist`: adds to the watchlist named **"ETF"**, creating it if missing, idempotent
(`added: false` for a member, even at the cap). At the 100-ticker cap it answers 400 with a message naming the list and
`n/100`, shown under the button. **The "ETF" list is ETF-only** (2026-10-04): the add is refused with a 400 (`XYZ is not an ETF.
The "ETF" watchlist holds ETFs only.`) for anything that is not a known ETF (cached profile / score row says ETF, or an
`EtfScreenerRow`), a never-seen ticker included; the check runs before the list is created. The generic add and bulk add
enforce the same rule for a list named "ETF" (bulk: all or nothing, every offender named). The list can't be renamed or
deleted, and no other list can take the name (`data/watchlists.py::tickers_not_allowed_on_watchlist`; the Watchlists page shows no
rename or delete control for it). See docs/decisions.md, 2026-10-04. Once the ETF is on any **monitored** list the button becomes a quiet, disabled ghost
"On watchlist <name>" with a check icon (first name in natural order, `+N` when on several); removal stays on the
Watchlists page. Which lists are monitored comes from `WatchlistOut.monitored` (backend `is_monitored_watchlist_name`),
so the frontend never re-implements the naming rule. An ETF only on an unmonitored list still shows the primary button.

The header's action cluster also holds the shared universe button (Add to / Remove from Universe, first in the cluster, before the watchlist button; nothing for a protected or delisted ETF), the same flow the stock header uses, with its note or error under the cluster. The header row does not wrap (the title shrinks instead); see [Tracked universe](tracked-universe.md), "Frontend".

## Related changes

- **Search:** `TickerSearchResult.is_etf` renders a small "ETF" badge. FMP's search has no security-type field and a
  per-result `/profile` call would cost calls and add every searched ticker to the tracked universe, so the flag comes
  from local knowledge only (`data/etf_data.py::known_etf_tickers`: a cached profile with `isEtf`/`isFund`, or a
  `TickerScore.is_etf` row). An ETF never opened, scored or watchlisted is therefore **not labelled** until its page is
  first viewed.
- **Watchlist rows:** the list named "ETF" holds ETFs only (see "Add to watchlist"), but it is still rendered by the stock table until the
  dedicated ETF table is built (a later step); an ETF on any other list is a stock-table row. `WatchlistRowOut.is_etf` (from the score row) shows an "ETF" badge in the Analysis cell in place of
  the blank score, and the Rating cell shows a dash: `data/watchlist_data.py::_compose_row` makes **no** `/grades-consensus`
  call for an ETF row (FMP answers `[]` for a fund, so it was one wasted call and one empty cached row per ETF per window)
  and the row carries the `N/A` placeholder (`NO_CONSENSUS_RATING`), which sorts last. The consensus call is made after the
  row's cache-only reads because it depends on them; a ticker with no score row (no cached profile) is not known to be an
  ETF and still makes it. Stock rows are unchanged.
- **Sectors heatmap:** each sector label is one `Link` to `/tickers/<ETF>` (new tab, like other ticker links).
- **`nightly_fundamentals_fetch`** skips known ETFs/funds when it builds its own universe
  (`load_fundamentals_fetch_universe`); an explicit `--tickers` list is still honoured. The score recompute and momentum
  use the tracked universe (an ETF that was only opened, not added, is not in it, see [Tracked universe](tracked-universe.md)); search
  uses the wide known set.

## `/summary` for an ETF: the stock-only fetches are skipped (2026-10-02)

`data/ticker_summary.py::get_summary` decides `is_etf` (`isEtf || isFund`, the app's one rule) from the **profile**, which is
always the first fetch (so the first-ever open of an ETF is recognised before any stock-only call), and for an ETF/fund it
skips everything only a company has an answer for: `/earnings`, `/ratios` (latest and TTM), the quarterly balance sheet and
income statement, `/enterprise-values`, `/financial-growth`, the SPY comparison row, and Step 2 / Step 3 (which would
themselves fetch analyst estimates, annual ratios, cash flow, key metrics ...). FMP answered every one of them `[]`, so
nothing is lost: no call, **no empty `FundamentalsCache` row**. The fetches live in
`_fetch_stock_only_data`; the stock path runs them unchanged and in the same order.

Kept, because they return real data for a fund: `/profile`, `/quote` (force-fetched on a live view, with the last-close
fallback), `/stock-price-change`, and the 45-day daily-price fetch behind the header's volume fields. The summary an ETF gets
back is identical to the old cascade's except `perf_5y_vs_spy_*` (now None: the "5Y vs SPY" pill is a stock comparison the
ETF header does not show) and `valuation_source` (None instead of `"auto"`; `fair_value_*` and `eps_growth_3_5y` were
already None). Applies to both the live and the `cache_only` path (the latter makes no call either way).

Calls on the first-ever open of an ETF (a fresh cache): **18 before, 4 after** (profile, quote, price change, daily prices);
a repeat open within the staleness windows makes 1 (the live quote) before and after. Measured by
`tests/test_etf_summary_short_circuit.py`.

Not covered: `POST /api/tickers/{t}/refresh` still runs `compute_ticker_score(cache_only=False)`, whose Step 1/2/4/5 calls are
not short-circuited (the ETF page has no Refresh button, and `nightly_fundamentals_fetch` skips known ETFs). A custom
valuation saved against an ETF (not creatable from the ETF page) is not read by the summary.

## Known limits

- The caption says "Exchange-traded fund" for every `isEtf || isFund` ticker, including a mutual fund or closed-end fund.
- Empty stock-statement rows cached for an ETF before 2026-10-02 stay in `FundamentalsCache` (2026-10-02 read-only check of
  the live DB: 103 empty rows across the 7 cached ETFs, plus 4 non-empty `earnings` rows whose `epsActual` is all null).
  Nothing reads them for an ETF and nothing refreshes them any more, so `pipeline.prune_cache` (it deletes every
  `FundamentalsCache` row older than `Settings.cache_retention_days`, 180 days) removes them in time; they were not deleted by hand.
