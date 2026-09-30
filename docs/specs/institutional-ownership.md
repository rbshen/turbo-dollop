# Institutional Ownership (ticker-page tab), SHELVED 2026-09-27

## Status: shelved, not deleted

The feature shipped and was shelved the same day (2026-09-27). Tried against real tickers in live use, it
was judged low decision-value for short-premium / short-term trading, the same conclusion reached for
Insider Activity: 13F data's quarterly cadence and 45+ day reporting lag doesn't inform week-to-week
decisions. Unlike Insider Activity (fully deleted, see `docs/archive/claude-md-history-features.md`), this
feature's code, tests and DB schema are all still in the tree and it can be revived without code changes to
the backend.

- The `institutional_ownership` FMP Data Group's **default is disabled** (`core/data_groups.py`). The
  existing group-off gate in `get_institutional_ownership_data` already does the right thing (state (a)
  below: `enabled: false`, no FMP call, no cache read/write), so shelving needed only that one-line default
  flip.
- The tab is off the ticker page: it is dropped from `lib/tickerTabs.ts`'s `TickerTab` / `TICKER_TABS` and
  `TickerTabsContainer`, and from `lib/dataGroups.ts`'s `TAB_GROUPS` (both its own entry and the Summary
  tab's, since nothing on Summary surfaces institutional-ownership data). The `InstitutionalOwnershipTab`
  component and the `useInstitutionalOwnership` hook are unchanged and currently unimported.
- It never had a cron job, so Scheduled Jobs needed nothing. Settings > FMP data groups is fully data-driven off the
  live group list (same as `news`), so a disabled group just shows as an off toggle row; there is no
  separate "shelved" listing to prune.
- All backend/frontend code and its tests are left in the tree, each carrying a short revival comment
  (mirroring Insider Activity's own).
- The two cache statement types (`institutional_ownership_summary`, `institutional_ownership_holders`) were
  purged from `FundamentalsCache` on 2026-09-27 (224 rows, 23 tickers; real production usage between
  shipping and shelving, not test contamination).
- The seeded conftest state has `institutional_ownership` off (alongside `news`); the feature's own tests
  turn it on explicitly.

**To revive:** turn the `institutional_ownership` Data Group on in Settings > FMP data groups (no restart), then
re-add `"institutionalOwnership"` to the `TickerTab` union and `TICKER_TABS` (between Analyst Ratings and
Technical), the `InstitutionalOwnershipTab` branch in `TickerTabsContainer`, and its `TAB_GROUPS` entries.

Everything below describes the feature as built: accurate documentation of what exists, just inactive.

## What it is

A read-only lens on 13F institutional ownership. It never touches Step 1-5 / Overall Assessment scoring and
has no Screener or Watchlist surface.

**Data group.** `institutional_ownership` is an FMP Data Group at the **Ultimate tier** (both endpoints were
confirmed live 200s on our key during the feasibility investigation, with no cheaper tier documented). It is
registered in `core/data_groups.py` (`GROUPS`, `ENDPOINT_GROUP`, `STATEMENT_TYPE_GROUP`, `PROBE_ENDPOINTS`).
The canary is a fixed 2020 Q1 AAPL request, since the *current* quarter is never a safe canary: it routinely
reads empty pre-filing. Two `FMPClient` methods, `get_institutional_ownership_summary` and
`get_institutional_ownership_holders`, wrap FMP's `institutional-ownership/symbol-positions-summary` and
`institutional-ownership/extract-analytics/holder`. Neither `year` nor `quarter` is optional on the summary
endpoint (a 400 without both) and there is no bulk or multi-quarter mode, so it is one call per quarter.

## Data and the four-state model

`data/institutional_ownership_data.py`, exposed at `GET /api/tickers/{ticker}/institutional-ownership`:

- **(a) group off:** `enabled: false`, nothing fetched at all (no cache read, no FMP call).
- **(b) no coverage:** every quarter in the anchor-search window comes back empty, so `no_coverage: true`.
- **(c) latest quarter fails the plausibility guardrail** (below): the headline stat cards and sentiment
  badge degrade to `note`, but `positions` / `top_holders` still render (they are computed independently of
  the guardrail). An OLDER quarter failing it just drops that one point from the 8-quarter `trend`
  (`trend_quarters_shown` reports how many survived).
- **(d) a normal complete read.**

## Caching

Real caching, not fetch-fresh-per-view. Both endpoints go through the standard `FundamentalsCache` /
`core.cache.get_or_fetch` machinery (statement types `institutional_ownership_summary` /
`institutional_ownership_holders`, period `"<year>Q<quarter>"` per quarter) with a **dedicated
`INSTITUTIONAL_OWNERSHIP_STALENESS_DAYS` (7)** constant. That mirrors the old `insider_staleness_days`
convention (a per-feature window, not the shared `cache_staleness_days` default).
`as_of_quarter` / `fetched_at` / `data_stale_warning` are read directly off the anchor quarter's own
`FundamentalsCache` row (the same "re-read the row for its metadata" convention as
`analyst_ratings_data.py`'s `grades_consensus_row`), not a placeholder.

**Refetch-grace-window gate, on top of the flat staleness clock.** SEC's 13F deadline is 45 calendar days
after quarter-end, but real filings trickle in well past it (confirmed live: an AAPL holder's `filingDate`
landed ~5.5 weeks after that deadline). A quarter therefore stays in the normal ~weekly refetch rotation
through `FILING_DEADLINE_DAYS` (45) + `REFETCH_GRACE_DAYS` (56), i.e. ~101 days past its own quarter-end. Past
that, an **already-cached** quarter is served frozen forever (no further live attempts, however stale the
flat 7-day clock says it is). A quarter with **no cached row at all yet** is always fetched at least once no
matter how old, since this gate only stops *repeating* an attempt, not the first one. Without it, every tab
view of an old, fully-settled quarter would re-hit FMP every ~7 days forever.

## Plausibility guardrail

`_quarter_is_plausible` hides a quarter's ownership figures if `ownershipPercent` is `<0` or `>98%`, OR if the
implied shares-outstanding (`numberOf13Fshares / (ownershipPercent/100)`) diverges more than 15% from
Fathom's own `helpers/shares.py::compute_shares_outstanding`. **`shares_outstanding` on the tab is always
Fathom's own figure, never FMP's derived one**, which the feasibility investigation found diverges
materially on dual-class and GP-LP names. Confirmed live against **ARES**: every single tracked quarter's
13F-implied share count diverges 15-32% from Fathom's own `marketCap/price` figure (one quarter reads >100%
outright), so the guardrail correctly hides the stat cards, sentiment and entire 8-quarter trend for it
(`trend_quarters_shown: 0`) while `positions` / `top_holders` still render normally. That is a genuine,
structural characteristic of that ticker's data, not an implementation bug.

## Sentiment

"Accumulating" if >=3 of the last 4 (present and plausible) quarters have a positive
`ownershipPercentChange`; "Distributing" if >=3 are negative; otherwise "Neutral". It is computed only when
the latest quarter itself passes the guardrail.

## UI (as built, before shelving)

`useInstitutionalOwnership` + `InstitutionalOwnershipTab.tsx`: 4 stat cards (ownership %, holder count, shares
held vs. Fathom's shares outstanding, sentiment badge), a positions-breakdown tile row
(opened/increased/reduced/closed), an 8-quarter trend as **two stacked recharts panels** (ownership % and
holder count are on different scales, so never one dual-axis chart; the same reasoning as
`MarketBreadthCharts`'s percent-vs-count split), and a top-holders table (FMP already sorts
`extract-analytics/holder` descending by market value, so "top N" is one call, unlike Insider Activity's
100-row-truncation problem). While live, the tab sat in `lib/tickerTabs.ts` / `TickerTabsContainer.tsx`
right after Analyst Ratings, and in `lib/dataGroups.ts`'s `TAB_GROUPS` (its own tab, plus the Summary tab's
stale-data badge). All of that wiring was removed at shelving.

## Verification (no browser)

Verified live end-to-end against AAPL, TMP (Tompkins Financial Corp, a real S&P / regional-bank small-cap),
ARES, and CNSWF (genuinely zero 13F coverage, reads `no_coverage: true`).
