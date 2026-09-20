# Minimal ETF ticker page -- Round 2 investigation (2026-09-20)

Phase 1 only: investigation, no code changes. Scope: a minimal page for viewing an ETF
itself (profile, holdings, sector/country weighting), gated on the already-shipped `is_etf`
classification. Round 3 is out of scope and not discussed.

Live FMP calls used: **20 of ~20** (5 funds x 4 endpoints: VOO, XLK, AGG, ARKK, TQQQ), all
HTTP 200. Everything else was read-only: a sqlite `mode=ro` engine swapped onto every
module's `engine` reference (any write raises -- and did, once, proving the guard worked),
`FMP_ENABLED` forced off in-process (zero FMP calls, stale cache served as-is), no copy of
`fathom.db`. Only exception types were logged, never URLs/keys. All scratch files deleted.

## 1. Verdict in one paragraph

All four ETF endpoints **work on our plan**, the data for equity ETFs is **clean and
internally consistent** (weights sum to exactly 100, sorted, every row date-stamped), and the
existing app already carries more of an ETF page than expected (price/chart/technicals all
work today). Three things make it **bigger than "minimal"**: (a) bond and leveraged funds
break the "table of stocks" assumption -- AGG's holdings are 13,428 rows / 3.9 MB with **no
ticker on any row**, TQQQ's top holding is "Net Other Assets (Liabilities)" at 26.5%; (b) the
ticker page is not a shell you can swap tabs in -- **the header itself is stock-shaped** and
several pieces actively misbehave for an ETF (section 5); (c) `/etf/sector-weightings` is
**redundant** with `/etf/info` (a good surprise: one fewer call and cache key).

## 2. Endpoint access and shapes

| Endpoint | Access | Shape (one row = ...) |
|---|---|---|
| `/stable/etf/info?symbol=X` | 200 | list of 1 fund object |
| `/stable/etf/holdings?symbol=X` | 200 | one row per holding, sorted by weight desc |
| `/stable/etf/sector-weightings?symbol=X` | 200 | one row per sector |
| `/stable/etf/country-weightings?symbol=X` | 200 | one row per country (no `symbol` field) |

Nothing here is plan-gated (unlike intraday). Untested (budget): behavior for a **non-ETF**
symbol, a closed-end fund (`isFund`), or a non-US-listed ETF -- see risks.

### `/etf/info` (VOO, trimmed)

```
{"symbol":"VOO","name":"Vanguard S&P 500 ETF","assetClass":"Large Cap Equity",
 "domicile":"US","etfCompany":"Vanguard","expenseRatio":0.03,
 "assetsUnderManagement":1800000000000,"avgVolume":7860071,"holdingsCount":505,
 "inceptionDate":"2010-09-07","nav":702.22,"navCurrency":"USD","isActivelyTrading":true,
 "isin":"US9229083632","securityCusip":"922908363","website":"https://investor.vanguard...",
 "description":"...497 chars...","updatedAt":"2026-09-19T23:41:20.006Z",
 "sectorsList":[{"industry":"Basic Materials","exposure":1.62}, ...]}
```

Populated in practice: **all 19 keys populated on all 5 funds** (none null/empty), keys
identical across funds. `expenseRatio` is in **percent** (0.03 = 0.03%; SPY's 0.09 in Round 1
also matches the real 0.0945%). `inceptionDate` is ISO. `updatedAt` 2026-09-19..20 on all.

| | VOO | XLK | AGG | ARKK | TQQQ |
|---|---|---|---|---|---|
| assetClass | Large Cap Equity | Equity | Fixed Income | Equity | Equity |
| AUM | $1.80T | $121.9B | $137.3B | $5.56B | $36.9B |
| expenseRatio | 0.03 | 0.08 | 0.03 | 0.75 | 0.97 |
| holdingsCount (info) | 505 | 73 | 13,418 | **10** | 123 |
| holdings rows returned | 508 | 76 | 13,428 | **46** | 127 |

Quality notes:
- **`holdingsCount` is unreliable**: ARKK says 10 but has 46 holdings rows. Derive the count
  from the holdings rows, don't display the info field. (For the other four it is within a
  few rows -- the rows include cash/other lines.)
- **AUM for Vanguard funds looks fund-level, not ETF-class** (VOO $1.8T; VTI was $2.3T in
  Round 1). Very likely includes the mutual-fund share classes -- **not verified against an
  independent source**. The header's own `market_cap` for SPY (FMP quote) was $810.5B vs.
  `/etf/info` AUM $786.9B, so two different "size" numbers exist on the same page; label them.
- `assetClass` vocabulary is inconsistent ("Equity" vs "Large Cap Equity" vs "US Equity" seen
  in Round 1 on HEMI) -- display as-is, never branch logic on it.

### `/etf/holdings`

Row keys (identical on every row of every fund): `symbol` (the ETF), `asset` (holding's
ticker), `name`, `isin`, `securityCusip`, `sharesNumber`, `weightPercentage`, `marketValue`,
`updatedAt`.

| | VOO | XLK | AGG | ARKK | TQQQ |
|---|---|---|---|---|---|
| rows | 508 | 76 | **13,428** | 46 | 127 |
| sorted by weight desc | yes | yes | yes | yes | yes |
| sum of weights | 100.000 | 100.000 | 100.000 | 100.000 | 100.000 |
| negative / zero weights | 0 / 0 | 0 / 0 | **1 / 1** | 0 / 0 | 0 / **11** |
| `updatedAt` | 2026-09-20 (all rows) | 09-20 | **09-18** | 09-20 | 09-20 |
| rows with blank `asset` | 3 | 2 | **13,428 (all)** | 4 | 25 |
| top-10 / top-25 / top-100 weight | 37.8/51.5/75.1 | 61.3/83.6/100 | 6.4/11.5/28.6 | 49.7/82.6/100 | 64.4/82.1/99.1 |

- **Sorted, sums to 100, every row date-stamped** -- unlike Round 1's asset-exposure endpoint.
  `updatedAt` is identical on every row of a fund, so one `as_of` per fund is available for
  free (AGG's 09-18 is a Friday, consistent with a weekend fetch; the others read the fetch
  date, so it may be "FMP refreshed" rather than "holdings as-of" -- can't tell which).
- **Equity funds (VOO/XLK/ARKK): a clean table.** Blank-`asset` rows are cash/other
  (`US Dollar`, `MKTLIQ 12/31/2049`, `SSI US GOV MONEY MARKET`) and, on ARKK, **private/
  unlisted names with no ticker** (`OPENAI GROUP PBC SERIES C` 2.2%, `BRERA HOLDINGS PLC WTS`).
  Rows must be identified by `name`, with `asset` shown only when present.
- **Bond fund (AGG): "holdings" does not mean the same thing.** 13,428 bonds/pools
  (by a rough name match: ~2,800 mortgage pools, ~300 Treasuries, ~10,400 other -- corporates,
agencies, etc.), `asset` blank on every row,
  `sharesNumber` = 0 (par, not shares), identity only via `name`/CUSIP
  (`TREASURY NOTE 4.63% 02/15/2035`), a **negative** `USD CASH` row (-2.05% / -$2.8B), and a
  top row that is a cash sweep (2.81%). The top 100 rows are only 28.6% of the fund. A
  "stocks it owns" table is the wrong frame; a **top-N-by-weight bond table with a "13,428
  holdings" count** is the honest one.
- **Leveraged fund (TQQQ): weights sum to 100 but the composition is derivatives/cash.** Top
  row is `Net Other Assets (Liabilities)` **26.5%**, then `PROSHARES GENIUS MNY MKT ETF` 19.2%,
  then Treasury bills; the actual stocks are ~3% each. 25 blank-`asset` rows, 11 zero-weight.
  Displayable, but an unqualified "Top holdings" title would mislead.
- `name` casing varies by issuer (`Apple Inc` vs `APPLE INC`) -- display as-is or title-case.

### `/etf/sector-weightings` -- **redundant with `/etf/info`**

Row: `{"symbol":"VOO","sector":"Basic Materials","weightPercentage":1.62}` (number). Sums to
100.000 on all 5. **Identical to `info.sectorsList` on all 5 funds** (same sectors, same
values, verified). Alphabetical, not sorted by weight. Recommendation: **skip the endpoint**,
read `info.sectorsList` (saves a call and a cache key per ETF).
- Trivial/empty breakdowns are real: **AGG = one row, `Cash & Others` 100%** (a bond fund has
  no equity sectors); TQQQ = `Cash & Others` 39.3%; XLK = 99.8% Technology (plus a 0.15%
  `Energy`, presumably a reclassified holding). A sector chart must treat "Cash & Others >=
  ~95%" as "not applicable".

### `/etf/country-weightings`

Row: `{"country":"United States","weightPercentage":"97.74%"}` -- **`weightPercentage` is a
string with a trailing `%`** here (a number in sector-weightings) -- parse it. No `symbol`
field. Sums: VOO 100.00, XLK 100.01, AGG 99.99, ARKK 100.01, TQQQ 100.00 (rounding).
Row counts 8/4/**38**/7/8; an `"Other"` bucket appears (AGG 27.4%, TQQQ 39.3% = its cash/
derivatives, ARKK 4.1%) and sits in weight order, not at the end. Verified sorted by weight
desc on all 5 (still worth sorting client-side, since it's unguaranteed). Meaningful for AGG (67.6% US) unlike its sector list; XLK's
"98.4% US" is issuer domicile-of-holding, fine.

## 3. Payload sizes (measured)

Wire bytes (HTTP body, from the call log) -- and, in brackets, what an untrimmed
`json.dumps` cache row would store:

| Fund | info | holdings | sector | country |
|---|---|---|---|---|
| VOO | 2,098 | 143,951 [122,612] | 1,103 | 555 |
| XLK | 1,642 | 21,246 [18,052] | 303 | 278 |
| AGG | 1,486 | **3,902,819 [3,338,227]** | 91 | 2,572 |
| ARKK | 1,432 | 13,052 [11,118] | 563 | 484 |
| TQQQ | 2,333 | 35,539 [30,203] | 1,159 | 556 |

Trimmed holdings (only `asset`, `name`, `weightPercentage`, `marketValue`, compact JSON):
top-25 = 2.5-2.8 KB on all five; top-100 = 4.7-11.0 KB (VOO 10.1, XLK 7.4, AGG 11.0, ARKK
4.7, TQQQ 10.2). A top-250 slice is **extrapolated (~25 KB), not measured**. Latency 1.0-2.3 s
per call (AGG holdings slowest at 2.30 s); the four calls for one fund are independent and
can run concurrently (~1-2.5 s cold).

## 4. Round 1 overlap / reuse

- **The cache row is the same one.** Round 1's optional per-ETF enrichment (`/etf/info` for
  name/AUM/expense) and this page's `etf_info` read are the *same call*. Keyed by the **ETF
  symbol** (`("VOO","etf_info","latest")`), one row serves both: if Round 1's holders list
  ever shows AUM/expense, or this page renders, the other is a cache hit. Round 1's `/etf-list`
  is **not** needed here (`/etf/info` carries the name).
- Same conventions: `get_or_fetch` + `fetch_fn` that trims before caching, `as_of` from
  `fetched_at`, "not cached yet" vs "cached and empty" distinction, lazy-on-view, no prefetch.
- Round 1's "Held by" is hidden when `is_etf` (no overlap in rendering). Conversely, once an
  ETF page exists, Round 1's holder rows (`VTI`, `VOO`, ...) become natural link targets --
  noting the possibility only; not designed here.
- Round 1's asset-exposure and this round's holdings are inverse views of the same data; for
  SPY/AAPL they agreed exactly (Round 1). AGG's holdings look the same shape as an equity
  fund's but use blank `asset`, so nothing from Round 1's reverse lookup applies to bonds.

## 5. What an ETF ticker page does today (Phase 2.1)

How measured: the app's own API in-process (read-only) for SPY, plus reading the components.
API behavior below is **observed**; how it *renders* is **read from code, not seen** (no
browser). The gate `TickerTabsContainer` only checks that the summary loaded (404 -> "not
found"); **nothing on the ticker page consumes `is_etf`** (frontend `is_etf` appears only in
Screener code and `types.ts`), so an ETF gets the full stock experience. Still true.

SPY's cache: 24 rows, of which **19 are the empty list `[]`** (all income/balance/cash-flow/
ratios/key-metrics/enterprise-value/growth/analyst-estimates/segmentation/as-reported rows).
Real data: `profile`, `quote`, `price_change`, `earnings` (placeholders), price history.

Header (shown on every tab)
- **Misleading:** eyebrow reads "Financial Services . Asset Management" (the same text real
  asset managers carry -- this is the collision `classify_company_type` already documents);
  "Next earnings: **Not yet announced**" is always printed (ETFs don't report earnings).
- Correct: name, `SPY . AMEX`, price, change, Weinstein pill; Add-to-Watchlist; Refresh.
- Blank/hidden (probably): Assessment chip, Moat/Valuation/Speculative-Growth/5Y-vs-SPY pills.
- **Silent waste:** `GET /score` returns a row with `overall_score = None` for every ETF, and
  the route treats `None` as "recompute", so **every ETF header load re-runs the full
  `compute_ticker_score` and upserts `TickerScore`** (in my read-only harness this surfaced as
  a write error -- HTTP 500 -- which is the harness's guard, not a production failure, but it
  proves the write is attempted on every call). The header also fires moat, speculative-growth
  and trend requests.

| Tab | What the API returns for SPY | What the user sees (from code) |
|---|---|---|
| Summary | description (good: the fund blurb), price/perf 1M-10Y, 52w, market cap, beta, avg volume (all real); P/E, EPS growth, debt, EV, FV = null | metrics grid with real quote metrics plus many "-"; **two "SPY does not disclose a business-segment / geographic revenue breakdown" blocks** (segmentation is non-null but empty) |
| Financials | 33.8 KB payload, every statement all-null, period labels "-" | a full wall of empty rows |
| Ratios | 8.7 KB, all-null | same |
| Analysis | Steps 1/2/4 `insufficient_data`; Step 5 `not_supported` (there IS an explicit ETF branch); Overall = incomplete | Financials card "Required figures were unavailable for SPY"; Overall card **"Incomplete -- could not load Financials, Growth Rate, Profitability, Debt"** -- reads as a load failure, not "not applicable" |
| Valuation | `selected_method: PASS`, reasoning lists stock checks, `company_type=ETF` | a "PASS" method walk-through of stock rules |
| Economic Moat | `moat: null` | **an editable Moat picker -- a user can save a moat rating on an ETF**, which then triggers a score recompute |
| Analyst Ratings | banner `N/A`, 0 analysts, all targets null | empty shell |
| Technical | trend/Weinstein/etc. all present | **meaningful and correct** (BB+RSI/Warren/Liquidity show "Not tracked" unless on W1-W5) |
| Chart | HTTP 200, bars + `dividend_markers: 2` (6M), `earnings_markers: 0`, source Yahoo | **meaningful and correct** (verified live; Yahoo-sourced, no FMP) |

So: **2 of 9 tabs are already right (Technical, Chart), 1 is half-right (Summary), 6 are empty
or misleading.**

Cost side: with FMP on, an ETF's first pass through those tabs (plus `POST /refresh`, which
runs `compute_ticker_score(cache_only=False)` and refetches everything) triggers ~19 FMP calls
that all return `[]`. `pipeline.nightly_fundamentals_fetch` does the same weekly per viewed ETF
(already flagged in CLAUDE.md's ETF section as "Not done"). At today's one ETF (SPY) this is
~19 wasted calls a week -- immaterial; it scales with ETFs viewed, not with anything else.

## 6. Can the existing shell branch on `is_etf`? (Phase 2.2)

**Yes -- cleanly, at one point.** `TickerTabsContainer` already holds every hook before its
early returns; once `data` (the summary) resolves, `if (data.is_etf) return <EtfTickerPage/>`
before the stock header/tabs mount. No routing change (`/tickers/[symbol]` is one route), and
crucially nothing of the stock tab set mounts, so its FMP fetches never fire.

Reusable as-is
- `PageContainer`, the sticky header wrapper markup, the summary-loading/error/`TickerNotFound`
  gate (one shared gate, before the branch), `PriceChange`, `fmtMoney`, `AddToWatchlistButton`.
- `ChartTab` (unchanged), `TechnicalTab` (unchanged -- it already degrades to "not tracked").
- `MetricsGrid` + `TickerSummaryOut` for the price/performance block (needs an ETF-specific
  `MetricGroup` config: drop P/E, EPS, debt, EV; keep price, perf 1M-10Y, 52w, avg volume,
  beta).

Needs a small change
- `TickerTabs` reads the module constant `TICKER_TABS`; give it a `tabs` prop (or add an ETF
  tab list in `lib/tickerTabs.ts`). ~5 lines.
- `RefreshButton` -> `POST /refresh` triggers the stock cascade; needs an ETF-aware path
  (clear cache only, or skip the score recompute for `is_etf`).

Needs an ETF-specific replacement
- **The header** (`TickerHeader` is stock-only: sector eyebrow, valuation/moat/growth/assessment
  pills, next-earnings line). An `EtfHeader` with name, ticker . exchange, price/change,
  the Weinstein pill, and (from `/etf/info`) issuer + asset class instead of the sector line.
- New tab bodies (below) and their data hooks.

Not a "materially different page" -- it is the same page shell with a second header and tab
set behind one `if`.

## 7. Proposed minimal ETF page (Phase 2.3) -- "what goes where"

Four tabs (fewer than the stock's nine): **Overview . Holdings . Technical . Chart**
(Technical/Chart reused verbatim).

- **Overview**: fund description; a profile block from `/etf/info` -- issuer, asset class,
  AUM, expense ratio (as "0.03%"), inception date, NAV, holdings count (from row count),
  domicile, website; the price/perf metrics grid (existing quote fields).
- **Holdings**: top-N table (name, ticker when present, weight, market value), a "N holdings,
  as of <date>" caption, and top-10 concentration; **sector bars and country bars beside/below
  it** (sector from `info.sectorsList`, country from `/etf/country-weightings`). Empty/trivial
  states: sector list that is ~100% `Cash & Others` -> "Not applicable for this fund";
  bond funds get a "Top holdings (bonds, by weight)" title and the total-count line; leveraged
  funds keep cash/derivative lines but the title stays neutral ("Holdings").
- **Technical / Chart**: as-is.

Deliberately left out: Financials/Ratios/Analysis/Valuation/Moat/Analyst Ratings/News, the
Assessment/Moat/Valuation pills, and any "Held by" (Round 1 already gates on `is_etf`).

Backend surface: two read routes -- `GET /api/tickers/{t}/etf-info` (profile + sectors) and
`GET /api/tickers/{t}/etf-holdings` (trimmed holdings + country). Two rather than one so the
Overview tab never waits on AGG's 2.3 s holdings call; each guards with `is_etf` (cached
profile) so a stock symbol never causes an FMP call.

## 8. Watchlist / Screener (Phase 2.4)

- **Screener:** excludes ETFs (closed). Nothing to do.
- **Watchlist:** an ETF can be added (the Add button appears on the ETF page and nothing gates
  it; SPY is on no watchlist today). For SPY the row composes to: name, exchange, market cap,
  beta populated; `sector = None` (deliberately: `ticker_score` nulls it for ETFs); Steps 1/2/4
  `insufficient_data`, Step 5 `not_supported`; revenue/net-income/CFO trend cells empty;
  Moat/Valuation guarded (nothing drawn); consensus rating "N/A". **One thing draws
  unconditionally: the Overall cell** (`flatChipClassFor(null, null)` inside an always-rendered
  span) -> probably an empty grey chip (read from code, not seen). Otherwise blank rather than
  wrong. Its technical signals *do* work for a watchlisted ETF (Weinstein `advance` for SPY;
  BB+RSI/Warren/Liquidity nightly jobs only need price bars, so an ETF on W1-W5 gets them).
  Flag, not a blocker; independent of the page fix.

## 9. Caching design (Phase 3)

Follow the Round 1 / Insider precedent: `FundamentalsCache` + `get_or_fetch`, `fetch_fn`
trims **before** caching, `as_of` = `fetched_at`, lazy on view, keyed by the **ETF symbol**.
No new table, no migration.

| Key `(ticker, statement_type, period)` | Contents | Staleness | Measured size |
|---|---|---|---|
| `(ETF, "etf_info", "latest")` | the info object (incl. `sectorsList`) | 7 d (`cache_staleness_days`) | 1.2-2.3 KB |
| `(ETF, "etf_holdings", "latest")` | top-N slim rows (`asset,name,weightPercentage,marketValue`) + `total_rows` + `as_of` (max `updatedAt`) | **1 d** (dedicated setting) | top-100 = 4.7-11.0 KB (raw untrimmed: 11 KB-**3.3 MB**) |
| `(ETF, "etf_country", "latest")` | parsed country list | 7 d | 0.2-2.6 KB |
| ~~`etf_sector`~~ | **not needed** | -- | identical to `info.sectorsList` (5/5) |

You asked for one key per endpoint; it's three, because sector is redundant. If a fourth is
preferred for symmetry it costs one extra call per ETF for no new information.

**Trim before caching is required, not optional**: AGG's untrimmed holdings row would be
3.3 MB of JSON for a table nobody can display, and AGG isn't an outlier class (bond funds in
general). Suggested cap ~250 rows (VOO 250 rows = 91% of weight, XLK/ARKK/TQQQ ~100%, AGG 49%)
plus the true row count and a "shown covers X% of the fund" figure so the UI is honest. The
cap is a design choice, not a measurement.

**Staleness reasoning -- and what I could not measure.**
- Evidence: every holdings row and `info.updatedAt` is dated the **fetch day** (or the prior
  trading day for AGG on a weekend) -> FMP refreshes at most daily, so **1 day is the tightest
  window that can ever help**, and nothing finer is meaningful.
- **I could not measure drift**: one snapshot per fund, budget spent; measuring needs a second
  fetch on a later day. Windows below are judgment calls.
- Holdings 1 d: cheap (one call per ETF per day *viewed*, ETF pages are rarely visited) and
  active/leveraged funds (ARKK, TQQQ) really do change daily; an `as_of` caption makes any
  lag visible either way.
- Info 7 d: name/issuer/expense/inception are static; AUM/NAV drift daily but are shown with
  the as-of date and aren't decision-critical at day granularity.
- Country 7 d: coarse percentages derived from holdings; slow-moving for index funds.

**FMP disabled / cold miss:** identical to Insider/Round 1: `get_or_fetch` serves stale rows
if any, `None` on a never-cached ETF -> `as_of = null` -> "not cached yet", distinct from a
cached empty result. The `Status` page `FMP_POWERS` list gets an "ETF Data" line.

**Existing machinery:** `POST /refresh` (`clear_ticker_cache`) deletes every row for the
symbol generically, so the ETF keys clear and repopulate on next view -- needs no change,
except the score-recompute side effect in section 6. `prune_cache`, `backup_db`,
`audit_fixture_contamination`, `load_full_tracked_universe`, cron: no change (same reasoning
as Round 1).

**Prefetch:** not warranted. Round 1 measured ~1-2.5 s per call and that nothing here is
worth a nightly budget; with 3 lazy calls (~4-6 KB cached each, ~1-2.5 s cold) per ETF *viewed*
there is nothing to prefetch, and the only ETF-specific nightly concern is the opposite
one -- **stopping the wasteful ~19 empty stock-statement calls/week per viewed ETF** in
`nightly_fundamentals_fetch` (`is_etf` is known from the cached profile). That is optional
cleanup, not part of a minimal page; the numbers (1 ETF tracked today) don't justify urgency.

## 10. Size of a real build

Backend
- `clients/fmp_client.py` -- `get_etf_info`, `get_etf_holdings`, `get_etf_country_weightings`
- `data/etf_data.py` (new) -- fetch/trim/normalize (string-% parsing, `Cash & Others` rule,
  asset-blank handling), `is_etf` guard
- `core/schemas.py` -- `EtfInfoOut`, `EtfHoldingsOut` (+ row/sector/country models)
- `core/main.py` -- 2 routes; ETF-aware guard on `POST /refresh` and `GET /score` (skip the
  recompute for `is_etf`) -- **collateral, ~10-20 lines each**
- `core/config.py` -- one setting (`etf_holdings_staleness_days`)
- tests: `test_etf_data.py`, endpoint tests, the refresh/score guards

Frontend
- `lib/api/types.ts`, `lib/hooks/useEtfInfo.ts`, `lib/hooks/useEtfHoldings.ts`,
  `lib/etf.ts` (+ test: formatters, trivial-sector rule, bond/leveraged titles)
- `components/etf/EtfTickerPage.tsx`, `EtfHeader.tsx`, `EtfOverviewTab.tsx`,
  `EtfHoldingsTab.tsx`, small `BreakdownBars.tsx` (sector/country)
- `components/ticker/TickerTabsContainer.tsx` (the branch), `TickerTabs.tsx` (`tabs` prop),
  `lib/tickerTabs.ts` (ETF tab defs), `lib/metrics/config.ts` (ETF metric group),
  `components/settings/StatusSection.tsx` (one line)

Docs: a CLAUDE.md section. No migration, cron or new table.

**~16-20 files, roughly two focused sessions** -- about 2-2.5x Round 1's estimate (6-8 files,
one session). Optional, separable: nightly ETF skip, Watchlist empty-chip guard, Moat-PUT guard
for ETFs.

## 11. Does this stay "minimal"? What changes

1. **Not additive-only.** Beyond the new page, four behaviours need an ETF guard so shipping
   the page doesn't leave traps: `/score` recompute-per-view, `POST /refresh`'s stock cascade,
   the Moat PUT on ETFs, and the header replacement. The first two are real correctness/cost
   issues today, whether or not the page is built.
2. **Bond and leveraged funds are the real design cost**, not equity ETFs. Without the trim +
   name-based rows + "not applicable" sector state, AGG returns a 3.9 MB response with 13,428
   ticker-less rows and a 100% "Cash & Others" sector chart.
3. **The scope is smaller than feared on the data side**: 3 calls not 4, and Chart/Technical
   already work.
4. Data quirks to encode (each small but easy to get wrong): country % is a string; `holdingsCount`
   lies (ARKK); AUM appears fund-level for Vanguard; a negative weight exists (AGG `USD CASH`);
   private/unlisted holdings have no ticker (ARKK).

## 12. Decisions needed before building

1. **Tabs**: 4 (Overview/Holdings/Technical/Chart, recommended) vs. a single scrolling page
   vs. keeping sector/country as a separate 5th tab.
2. **Holdings cap**: ~250 rows cached, show top ~25-50 with "show more" (recommended) vs.
   smaller (top 100).
3. **Bond/leveraged funds**: show as ordinary funds with a neutral title (recommended) vs.
   detect and special-case them (`assetClass`, name heuristics) -- the latter is more work
   and `assetClass` is inconsistent.
4. **Staleness**: holdings 1 d / info 7 d / country 7 d (recommended, judgment) vs. a single
   shared window.
5. **Header content**: issuer + asset class line under the name (recommended) vs. nothing.
6. **Collateral guards**: ship the `/score`+`/refresh` ETF guards with this build
   (recommended) vs. as a separate small change first.
7. **Sector endpoint**: skip (recommended) vs. call it anyway for symmetry.

## 13. Risks / not verified

- **Not tested (budget):** a non-ETF symbol against these endpoints (frontend/backend `is_etf`
  gating makes this moot, but a stock symbol's behavior -- `[]`, 404, or 402 -- is unknown);
  a **closed-end fund** (`is_etf` = `isEtf OR isFund`, so e.g. PTY takes this page -- do the
  ETF endpoints return anything for a CEF?); a **non-US-listed ETF**; a very small/new ETF.
- Drift/staleness not measured (section 9). AUM semantics for Vanguard not independently
  verified. `updatedAt` = holdings as-of vs. FMP fetch date is undetermined.
- All "what the user sees" statements in section 5 and 8 are **read from code, not rendered**;
  the API payloads are observed. The manual checklist below covers it.
- Pre-existing, unrelated: a yfinance "No earnings dates found" warning is logged for an ETF's
  Chart request (harmless log noise). Also the earlier-flagged `safe_fetch` logs `exc` verbatim
  (httpx messages can embed the API key) -- still true, out of scope.
- The sqlite read-only harness is only as good as its swap: it replaced 31 `engine` references
  and demonstrably blocked one attempted write, but it isn't a substitute for the test suite's
  engine-isolation convention.

## 14. Manual UI checklist (no browser was available; for after a real build)

1. `/tickers/SPY`, `/tickers/VOO`: ETF page (not the stock page) loads: fund name, `SPY .
   AMEX`, price/change; **no** sector eyebrow, **no** "Next earnings", no Assessment/Moat/
   Valuation pills; tabs read Overview / Holdings / Technical / Chart.
2. Overview: description present; AUM, expense ratio (e.g. "0.09%"), inception date, NAV,
   issuer, asset class, holdings count all populated; price/perf block shows real values with
   no P/E/EPS/debt rows.
3. Holdings (`VOO`): top rows NVDA/AAPL/MSFT with sensible weights, "as of" caption, count
   ~505, sector and country bars each summing to ~100%.
4. `XLK`: sector bars show Technology ~99.8%; `ARKK`: private/unlisted rows (`OPENAI ...`)
   appear by name with no ticker; count reads 46 (not the info field's 10).
5. `AGG`: page loads quickly (no multi-MB stall); holdings show top-N **by name** (no tickers)
   with "13,4xx holdings" and a coverage note; sector panel says not applicable (not a 100%
   "Cash & Others" bar); country bars show US ~67.6% and Other.
6. `TQQQ`: holdings show "Net Other Assets (Liabilities)" and T-bills near the top; title/
   note doesn't claim "top stocks"; sector panel shows Cash & Others ~39%.
7. Technical and Chart tabs behave exactly as on a stock (Chart: dividend markers, no earnings
   markers).
8. Browser dev tools on an ETF page: **no** requests to `/financials`, `/ratios`, `/step1..5`,
   `/analyst-ratings`, `/moat`, `/speculative-growth`; and `/score` does not recompute on each
   reload (backend log: no `tickerscore` upsert per view).
9. Refresh button on an ETF: clears and refetches ETF data; no burst of stock-statement calls.
10. Add an ETF to a watchlist: row shows name/market cap/beta, no misleading grades, no empty
    grey Overall chip.
11. A normal stock (`AAPL`) still renders the full 9-tab stock page, unchanged, and shows the
    Round 1 "Held by" section if that has shipped.
12. FMP paused (`FMP_ENABLED=false`): a previously-viewed ETF shows cached data with its old
    as-of; a never-viewed ETF shows "not cached yet" (distinct from empty); Chart/Technical
    still work.
13. Status page FMP card lists the ETF data line.
