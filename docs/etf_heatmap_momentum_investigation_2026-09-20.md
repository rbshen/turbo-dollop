# Sector ETF Heatmap + ETF Momentum Ranking -- investigation (2026-09-20)

Investigation and design proposal only. No application code, no schema change, no crontab
change. Two features, both purely price-driven:

- **(A) Sector heatmap** -- the 11 SPDR sector ETFs x 7 return windows (1w, 1m, 3m, 6m, 9m,
  YTD, 1y), color-graded.
- **(B) ETF Momentum ranking** -- the existing 3/6/12-month composite (`scoring/momentum.py`)
  applied to a fixed 45-ETF universe.

Live calls used: **55 FMP** (47 x `/historical-price-eod/full`, 8 x
`/historical-price-eod/dividend-adjusted`, all HTTP 200) and **5 Yahoo batch downloads**.
Both were made with plain `httpx`/`yfinance` from scratch scripts that import only
`core.config` -- `FMPClient`/`YahooClient` were deliberately not used, because both call
`record_success()`, which writes to the real `fathom.db`. **Nothing touched the database.** All
scratch files are deleted.

## 1. Verdict in one paragraph

Both features are **fully feasible with no data blocker**. Every one of the 47 unique tickers
has clean daily data on **both** FMP and Yahoo (identical date sets, no gaps, prices agreeing to
<2 bp), all have 8+ years of history (no young-fund problem), and the existing pure momentum
engine ranks the ETF universe **unmodified** (45/45 ranked). Three findings shape the design:

1. **The combined universe is 47 tickers, not 56.** 11 sector + 45 momentum = 56, but 9 sector
   ETFs (XLF, XLE, XLK, XLV, XLY, XLI, XLP, XLU, XLC) are also in the momentum list. Only XLB and
   XLRE are sector-only.
2. **Price return vs total return is a real decision, not a footnote.** Over 1y the gap is 2.0 pp
   median and up to 5.9 pp (HYG) -- BIL shows -0.1% on price but +3.7% total. It barely changes
   the *ranking today* (Spearman 0.995, identical top 10), but it changes every displayed number
   for bond/income funds. And the stock Momentum feature already uses total return.
3. **The existing shared bars cache (`SharedBarsCache`) cannot carry total return** -- it stores
   raw OHLCV only. Combined with near-zero overlap with its current consumers, this points to a
   small dedicated store instead of extending it (section 4).

## 2. Data source and availability

### 2.1 FMP: works, no plan restriction

`/stable/historical-price-eod/full` returned 200 with data for **47/47** tickers -- equity,
bond (TLT/IEF/SHY/BIL/AGG/LQD/HYG/MBB/PFF), commodity (GLD/SLV/DBC/USO/DBA/PICK), currency
(UUP), miners (GDX/GDXJ). Each returned 429 daily bars, 2025-01-02 to 2026-09-18 (the window
requested; deeper FMP history was not probed -- 13 months is all this needs). The
dividend-adjusted endpoint (`/historical-price-eod/dividend-adjusted`, fields `adjClose` etc.)
also returned 200 for all 8 sampled tickers (BIL, HYG, TLT, USO, UUP, GLD, XLRE, SPY). Unlike
FMP intraday (402), nothing here is plan-gated. Cost to use it: **one call per ticker per
endpoint, no batch** (47, or 94 for price + adjusted).

### 2.2 Yahoo: works for every ticker, including the "niche" ones

The Yahoo batch (`auto_adjust=False`) returned real data for **47/47**, including the
short-duration/niche products flagged in the brief (BIL, SHY, PFF, UUP, DBC), with the same 429
bars and the same last bar (2026-09-18) as FMP. `auto_adjust=False` returns **both** raw `Close`
(split-adjusted) and `Adj Close` (split- and dividend-adjusted) in one download. Batch latency
for all 47: **3.2 s (2y), 4.4 s (5y)**.

### 2.3 The two sources agree

| Check | Result |
|---|---|
| FMP `close` vs Yahoo raw `Close`, 47 tickers x 429 bars | date sets identical for every ticker; max relative difference 1.8 bp; **0 bars differ by >10 bp** |
| FMP `adjClose` vs Yahoo `Adj Close`, 8 tickers | max relative difference 0.00-0.04% for 7; **TLT 0.40%** (worst) |
| Yahoo `Adj Close` from a 2y fetch vs a max-history fetch (TLT/HYG/BIL) | identical to ~1e-6 -- the adjustment does not depend on the fetch window |
| Large single-day moves (SLV 28.5%, SOXX 18.6%, ARKK 16.6%, GDXJ 13.6%, XLK 13.4%, USO 12.9%) | appear identically in both sources, so they are not provider glitches |

### 2.4 Recommendation on source: Yahoo

Yahoo matches every other price-only consumer in the app (Trend, Weinstein, Liquidity Zones,
Warren, BB+RSI, Chart, and the existing Momentum), has no kill switch (works through an
`FMP_ENABLED=false` pause, and needs no `if not settings.fmp_enabled` guard), and does the
whole universe in one 3-4 s call versus 47-94 FMP calls. FMP is a verified, working
alternative -- not needed. The one thing to remember is that the FMP price endpoint is
**price-only**; total return would need the separate dividend-adjusted endpoint (2x the calls).

### 2.5 Return basis: price vs total return

This is the substantive data question. Measured on the 2026-09-18 anchor (Yahoo `Close` vs
`Adj Close`, calendar windows):

| Window | Gap (total minus price), median across 47 | Gap, max | Largest |
|---|---|---|---|
| 1w | 0.00 pp | 0.8 pp | ITB, VYM |
| 1m | 0.00 pp | 0.8 pp | ITB, HYG |
| 3m | 0.34 pp | 1.5 pp | HYG, PFF, LQD |
| 6m | 0.90 pp | 3.0 pp | HYG, PFF, LQD |
| 9m | 1.40 pp | 4.9 pp | DBC, HYG, DBA |
| YTD | 0.88 pp | 4.0 pp | HYG, PFF, LQD |
| 1y | 2.00 pp | 5.9 pp | HYG, PFF, DBC |

- **Distribution-paying funds are materially understated on price.** 1y price -> total: BIL
  -0.1% -> +3.7%, SHY -2.0% -> +1.5%, AGG -4.3% -> -0.4%, HYG -3.3% -> +2.6%, MBB -3.9% -> +0.2%,
  XLE 43.4% -> 47.8%, XLRE 1.1% -> 4.6%, VYM 12.5% -> 16.0%. Among the sector ETFs the gap is up
  to 4.5 pp (XLE) at 1y, comparable to the spread between neighboring sectors.
- **Commodity/currency pools are mixed:** DBC (4.9 pp), DBA (3.8), UUP (3.6) pay annual
  distributions that Yahoo captures; GLD, SLV and USO are exactly 0.0 (grantor trusts / futures
  ETFs with no distribution -- USO's roll cost is already inside its price).
- **Momentum ranking is robust to the basis today**, using the existing
  `compute_momentum_ranking` unchanged on both: Spearman rank correlation **0.995**, **top-10
  identical** (USO, SOXX, DBC, XLE, XLK, GDXJ, GDX, PICK, XLV, SLV), largest single mover 4 places
  (VYM 22->18, PFF 40->36). The *composite values* still differ (BIL 0.0% vs 2.1%). This is a
  property of a regime where the spread in 3/6/12m returns dwarfs the income component; it
  would not necessarily hold when a T-bill/bond fund sits near the cut.
- **Precedent:** the stock Momentum feature (`data/momentum_data.py`) does not pass
  `auto_adjust`, so it gets `yahoo_client`'s default `True` -- i.e. it is already a
  **total-return** ranking (its own docstring says "trailing total return"). Ranking ETFs on
  price while the stock list ranks on total return would be inconsistent, and would put T-bill
  funds at ~0% structurally.
- **Conventions differ by product.** Most public sector heatmaps (Finviz/TradingView style) show
  *price* change; a ranking should be total return. So the sensible split, if wanted, is
  headline total return everywhere with the price figure available, or price on the heatmap
  and total on the ranking -- decision 1.

## 3. Return-period mechanics

- **Anchor** = the last completed daily bar in the fetch (2026-09-18 for this investigation; a
  Sunday, so Friday). No use of `helpers/trading_calendar.py` is needed for the heatmap: its
  only function, `resolve_month_end_anchor`, is the monthly-Momentum gate/anchor resolver and
  has no generic "N trading days back" helper.
- **Calendar offsets vs trading-day offsets.** Compared both on the real data (calendar =
  `pd.DateOffset`, the convention `compute_momentum_ranking` already uses, taking the last close
  on/before the target; trading-day = 5/21/63/126/189/252 bars back):

  | Window | Tickers differing >1 pp | Max difference | Worst |
  |---|---|---|---|
  | 1w, 3m, YTD | 0 | 0.0 pp | (identical on this anchor) |
  | 1m | 17 | 9.5 pp | GDXJ |
  | 6m | 9 | 7.3 pp | GDXJ |
  | 9m | 8 | 3.5 pp | USO |
  | 1y | 8 | 7.0 pp | SOXX |

  Median differences are 0.4-0.8 pp; the large ones are volatile funds where a one-day shift in
  the base bar matters. Trading-day counts drift with the holiday calendar (this 1m window
  contains Labor Day), so "21 bars" does not mean the same calendar span month to month.
  **Recommendation: calendar offsets** -- matches the existing engine, means what the column
  header says, and needs no holiday-aware helper. The 1w/3m/YTD agreement above is specific to
  this anchor, not a guarantee.
- **YTD** = last close of the prior calendar year (2025-12-31 here) as the base -- the standard
  definition; the alternative ("first close of the year") drops the first session's move.
- **Insufficient history: none.** Earliest bar per fund (Yahoo `max`): XLC **2018-06-19** (the
  youngest, 8.3y), XLRE 2015-10-08, ARKK 2014-10-31, MOAT 2012-04-25, PICK 2012-02-02, GDXJ
  2009-11-11, SOXX 2001-07-13; every other fund is older. All 47 clear 12 months by years, so no
  ticker needs special-casing today. `compute_momentum_ranking` already drops (never imputes) a
  ticker lacking a bar on/before any lookback target, so a future young ETF would be handled;
  the heatmap would need the equivalent per-cell null.
- **Partial-bar hazard (real, for any on-demand fetch).** yfinance's daily frame includes an
  in-progress bar during market hours; the stored "close" would then be a live price. Not an
  issue for a nightly job at ~3:30 UTC (~11:30 pm ET), but a manual run mid-session would need
  to drop a same-day bar (the existing `_most_recent_completed_trading_date()` in
  `clients/shared_bars_cache.py` is the ready-made check).

## 4. Reuse vs new build

### 4.1 One computation can feed both features

Both features need the same thing: daily closes for a fixed list. The heatmap's 3m/6m/1y
columns **are** the momentum composite's inputs (3/6/12 months), computed with the same calendar
convention -- so a nightly per-ticker returns table also contains everything a composite needs.

### 4.2 `SharedBarsCache` is the wrong home (recommended: not to use it)

- It stores **raw OHLCV only** (`_write_rows` writes open/high/low/close/volume); there is no
  `adj_close`, so it cannot provide total return. Its own model docstring warns that mixing
  adjusted and unadjusted rows in it reintroduces a known inconsistency.
- Adding a nullable `adj_close` column is possible (additive `_add_missing_columns`), but it
  changes a table four shipped features read/write, and Yahoo's `Adj Close` is rescaled
  retroactively at every ex-dividend date -- safe only because each nightly refetch rewrites the
  whole window, which is an invariant to police rather than one the cache enforces.
- The **sharing benefit is close to nil here**: the cache's value is overlapping consumers (Trend
  and Liquidity Zones both reading `1d`, etc.). This universe overlaps the tracked-stock universe
  at most at SPY (which is the one ETF known to be in it) and any of these ETFs a user has put on
  W1-W5 -- watchlist membership was not checked. A 47-ticker fetch is 3-4 s.

Recommendation: the job fetches directly through `yahoo_client.get_history(..., auto_adjust=
False)` (no client change needed -- it already returns the full frame including `Adj Close`
when `auto_adjust=False`) and stores **computed returns**, not bars.

### 4.3 `MomentumSnapshot` does not extend cleanly -- new table

- `moat` is a non-optional `str` (NOT NULL); ETFs have no moat, and this app's migration helper
  is additive-only (it cannot relax a constraint).
- There is no universe discriminator: `compute_and_store_momentum_snapshot` deletes by
  `as_of_date` and `get_momentum_snapshot` reads `distinct(as_of_date)`, so a second universe in
  the same table would need filters added to the shipped stock feature; `MomentumSnapshotRowOut`
  also carries stock-only `moat`/`company_name`/`overall_score`.
- What *is* reusable as-is: **`scoring/momentum.py::compute_momentum_ranking`** (pure,
  universe-agnostic -- verified: 45/45 ranked on real ETF frames), `helpers/trading_calendar.py::
  resolve_month_end_anchor` (the monthly gate), the `--force-anchor` CLI convention, the
  `cron_heartbeat` wiring, `SegmentedControl`, and the `useMomentum` hook shape.

### 4.4 UI precedent for a heatmap grid

None exists (confirmed: `components/shared` holds only AnalysisSectionCard, OutlierWarningNote,
SegmentedControl, SeriesTrendTable; `components/ui` has chart/collapsible/table). `recharts`
(^3.8) is already a dependency but offers a Treemap, not a matrix; the layout requested (11 rows
x 7 columns = 77 cells) is a plain CSS grid or the existing `Table` with a per-cell background.
Build, don't add a library: a small `HeatmapGrid` where cell color is a diverging scale off the
existing `positive`/`negative` tokens with opacity proportional to magnitude (the app already
uses `bg-positive/8`, `/16` alpha conventions), text in the existing `fmtPct`/`pnlClass`
helpers. Color-scale choice (per-column vs fixed clamp) is a small open item (decision 8).

## 5. Caching and cron design

### 5.1 Cadence

- **Heatmap: daily.** 1w and YTD change every session. Persisted, read cache-only by the
  request path (the app's normal pattern) rather than a live 3-4 s Yahoo call per page view.
- **Ranking: independent of the heatmap's cadence.** The composite uses only 3/6/12m, so the
  stock feature's monthly month-end snapshot (validated methodology, history for the
  This month/Previous month toggle) can be mirrored as-is -- **or** the ranking can be read live
  off the daily table at zero extra cost (mean of the 3m/6m/1y total returns). Decision 4.

### 5.2 Proposed structure (for the numbered decisions to confirm)

| Piece | Proposal |
|---|---|
| Universe | one static constant (ticker, display name, asset class, in-heatmap/in-ranking flags) -- ETFs are not in `TickerScore`, so names cannot be joined the way the stock table does |
| Pure math | new `scoring/etf_returns.py` (7 window returns from a close series + anchor, price and total); ranking reuses `compute_momentum_ranking` unchanged |
| Table 1 | `EtfReturns`: ticker PK, `as_of_date`, `computed_at`, 7 price + 7 total return columns (nullable), upserted latest-only nightly (~47 rows) |
| Table 2 | `EtfMomentumSnapshot`: append-only monthly, like `MomentumSnapshot` minus `moat` (~45 rows/month) |
| Jobs | `pipeline.nightly_etf_returns` (daily) and `pipeline.monthly_etf_momentum_snapshot` (gate on days 1-5, reusing `resolve_month_end_anchor`) -- or the monthly logic folded into the existing monthly job (decision 5) |
| API | `GET /api/etf-heatmap`, `GET /api/etf-momentum?period=current|previous` (empty-state shape like `MomentumOut` when no snapshot exists) |
| Frontend | `HeatmapGrid`, an ETF ranking table (variant of `MomentumTable` -- no Moat column, asset-class instead), SWR hooks; add both to `YAHOO_POWERS` on the Status page |

### 5.3 Where it plugs into cron monitoring

`core/cron_health.py::CRON_JOB_NAMES` is 16 jobs today; each new job needs (a) a
`CRON_JOB_NAMES` entry, (b) an `_EXPECTED_CADENCE_HOURS` entry (`_DAILY_HOURS` = 36,
`_MONTHLY_HOURS` = 840), (c) a `JOB_METADATA` entry, (d) `cron_heartbeat(...)` at the script's
`__main__`, and (e) a `crontab.txt` line -- `tests/test_cron_wiring.py` fails if these drift, so
the wiring is enforced. Makes zero FMP calls, so no FMP-paused guard. Free minute for the
nightly job: **3:30 AM** sits in the existing gap between Liquidity Zones (3:25) and Warren
(3:40); the job is ~5 s. The monthly job could use a free minute on days 1-5 (3:05 is taken by
the stock momentum job; 3:10 by the trend job). The live crontab must be reinstalled
(`crontab crontab.txt`) after any edit -- CLAUDE.md records that editing the file alone does
nothing. Also update `backend/OPS_RUNBOOK.md`.

### 5.4 Test-suite obligations (from repo convention)

New models/data modules must be engine-isolated in tests (the session write-guard in
`tests/conftest.py` will fail any that reach the real DB); the returns math needs
hand-checkable fixtures (window boundaries, YTD base, a fund lacking history, weekend/holiday
anchor); cron-wiring test extends automatically.

## 6. Nav and placement -- open, not decided

Options (no recommendation made, per the brief):

- **(a) One new top-level page** (e.g. "ETFs"/"Markets") holding the heatmap on top and the ETF
  ranking below.
- **(b) Keep them separate:** heatmap as its own page; the ranking as a second tab
  (Stocks | ETFs) on the existing `/momentum` page, which already has a This month/Previous
  month toggle, layout, and banner.
- **(c) Both on `/momentum`** (heatmap as a section above the tables).

Facts that bear on it: the nav's `/watchlist`, `/momentum`, `/settings` links open in a new
tab (the `Screener` link does not); `/momentum`'s footer carries a caveat ("Ad hoc external
research ... not a Fathom product feature, not investment advice") and a Moat point-in-time note
that would not apply to ETFs; the stock page shows only the top 10 of its ranking. **Dependency
to know about:** ticker links from a heatmap cell or ranking row would go to `/tickers/<ETF>`,
and per the ETF Round 2 investigation the ticker page header is still stock-shaped for an ETF
(the chart and technicals work; not re-verified here, and the minimal ETF page is not built).

## 7. Size of a real build (rough)

Backend: universe constant, returns math, 2 models, 2 data modules, 2 jobs, 2 routes, cron
wiring, runbook -- on the order of 500-700 lines including tests. Frontend: page/section,
`HeatmapGrid`, ranking table, hooks, types, Status-page entries, tests -- roughly 350-500
lines. No new dependency, no FMP calls, no change to any shipped feature.

## 8. Risks / not verified

- **Not verified on screen** (no browser, per standing rule): all UI statements are read from
  code. The color scale, cell sizing and mobile behavior are proposals only.
- **FMP history depth** beyond 2025-01-01 was not probed (irrelevant if Yahoo is the source).
- **Cross-asset ranking caveat (not a bug):** the composite is a raw return average, not
  risk-adjusted, so high-volatility funds structurally lead (USO +106% 1y is #1; ARKK, GDXJ, SOXX
  near the top) and T-bill/short bond funds sit in the middle-to-bottom. It ranks "who went up
  most," not "best risk-adjusted." Accepted as-is unless you want a per-asset-class ranking.
- **The full-universe numbers above are one anchor date (2026-09-18).** In particular the
  price-vs-total ranking stability and the calendar-vs-trading-day agreement on 1w/3m/YTD are
  properties of this regime/date, not general guarantees.
- **Display names and asset-class labels** for the 47 tickers are not sourced from any feed --
  they would be a hand-written, hand-verified constant (or fetched from FMP `/etf/info`, which
  the ETF Round 2 doc shows works, at a call per fund).
- **Yahoo reliability:** no kill switch and no SLA; a failed nightly fetch leaves the previous
  night's rows in place (the heatmap should show its own `as_of_date`, so a stale table is
  visible rather than silent).
- **Holidays:** the nightly job re-runs on weekends and market holidays and simply recomputes
  the same anchor; harmless.

## 9. Decisions needed before implementation

1. **Return basis.** Total return (Adj Close) for both features (recommended: matches the stock
   Momentum feature; needed to keep bond/T-bill/income funds honest) / price return for the
   heatmap and total for the ranking / store both and expose a toggle (cheap -- the table holds
   both).
2. **Data source.** Yahoo (recommended: one 3-4 s batch, no FMP dependency, same as every other
   price feature) / FMP (works, 47-94 calls/night, dies with an FMP pause).
3. **Storage.** Dedicated tables holding computed returns, fetching directly (recommended) /
   extend `SharedBarsCache` with an `adj_close` column and store bars.
4. **Ranking cadence.** Monthly month-end snapshot with This/Previous-month toggle, exactly like
   stock Momentum (recommended: methodology parity, preserved history) / daily rolling ranking
   read off the daily table / both.
5. **Jobs.** Two new jobs, one nightly (heatmap) and one monthly (ranking) (recommended: one
   feature per script, clean failure attribution) / a single nightly job that also writes the
   monthly snapshot on the gate day / add the ETF universe to the existing monthly stock job.
6. **Window definition.** Calendar offsets with YTD off the prior year's last close
   (recommended) / trading-day counts.
7. **Universe and presentation of the ranking.** Confirm the 47-ticker list as given; who
   writes/approves the display names and asset-class labels; show all 45 ranked ETFs (probably,
   with asset-class shown or a filter) vs the stock page's top 10; whether SPY is kept in the
   ranking as a benchmark row.
8. **Heatmap UI.** Rows = ETFs, columns = the 7 windows (as described) vs a tile/treemap;
   color scale per column vs a fixed clamp; default sort (fixed order vs by a chosen window);
   whether cells click through to `/tickers/<ETF>` given the ETF page is not built yet.
9. **Nav placement** (open by request): (a) one new top-level page, (b) heatmap page + ranking
   as an ETFs tab on `/momentum`, or (c) everything on `/momentum`.
