# Sector Heatmap (`/sectors`)

The 11 SPDR sector ETFs (XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC) × 8 trailing-return
windows (1d/1w/1m/3m/6m/9m/YTD/1y), color-graded. Price-only, zero FMP *fundamentals* calls,
independent of Step 1-5/Overall Assessment scoring. This was Round 1 of a two-feature
investigation (2026-09-20) that also scoped a
companion **ETF Momentum ranking** (the existing 3/6/12-month stock-momentum composite applied
to a fixed 45-ETF universe) — that second feature is **not built**; this document covers only
what shipped.

## Data source and basis

Bars come from FMP, through `SharedBarsCache` (`get_or_fetch_bars_batch`) — the same shared
cache Trend/Weinstein, Liquidity Zones, and Market Breadth read from. `data/sector_heatmap_data.py`
reads the cache's `close` column directly: **split-adjusted, not dividend-adjusted** (not total
return). This was a deliberate decision, not an oversight: the app is used for options trading,
not holding the underlying, so dividend-adjusted/total-return pricing isn't the relevant basis
for this feature — a departure from the original feasibility investigation's own recommendation
(below), made after the investigation was written. The cost is that bond/income-heavy funds read
up to ~6pp lower over 1y than the original total-return design (XLE 1y was +47.8% total vs
+43.4% price).

*(Historical note: the original feasibility investigation, run before the FMP daily-bar
migration, evaluated Yahoo as the data source, at which point Yahoo was the app's price-only
provider for everything else. FMP became the sole data source for this feature the same way it
did for every other price-bar consumer — see `docs/specs/fmp-data-and-bar-cache.md` and the
removal record in `docs/archive/claude-md-history-fmp-migration.md`. The 2026-09-25 divergence
investigation below confirmed live that this job had already moved onto FMP.)*

## Windows and universe

`scoring/etf_returns.py::WINDOWS = ("1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y")` — 8 windows
(1d was added after the original 7-window design). Calendar offsets back from the anchor date
(1d = 1 day, 1w = 7 days, 1m/3m/6m/9m/1y = `pd.DateOffset`), base = the last close on/before the
target, so a weekend/holiday target uses the prior session; YTD's base is the last close on/before
Dec 31 of the prior year. A window with no bar on/before its target (a young fund) is `None`,
never imputed; a fund whose latest bar is more than 5 days behind the anchor
(`MAX_STALE_DAYS`) is all-`None`.

**Calendar offsets over trading-day counts was a deliberate choice**, checked against the real
data before shipping: at 1m/6m/9m/1y, a trading-day-offset convention (e.g. "21 bars back")
disagreed from the calendar convention by up to several percentage points on volatile funds, and
drifts with the holiday calendar so "21 bars" doesn't mean the same calendar span month to
month. Calendar offsets match the existing stock-Momentum engine's own convention and mean
exactly what the column header says.

**Anchor** (`data/sector_heatmap_data.py::_resolve_anchor`): the latest bar date across the
fetched funds that is ≤ the last completed session (`_most_recent_completed_trading_date`). The
cap drops an in-progress same-day bar; taking it from the data (not the weekday-only helper
directly) makes a market holiday anchor to the real last trading day.

## Storage and job

`SectorEtfReturn`, long format `(ticker, return_window, as_of_date)` unique, plus `base_date`,
`return_pct` (percentage POINTS — 4.25 == +4.25%, unlike `MomentumSnapshot`'s fractions),
`computed_at`. The column is `return_window` because WINDOW is reserved in SQLite. Upserted, so a
weekend/holiday re-run is idempotent; a rolling year of daily snapshots is kept (~88 rows/session
at 8 windows × 11 funds) and the API reads only the latest `as_of_date`. It is **not**
`SharedBarsCache` (that cache holds raw per-bar data, not return rows) and **not** `MomentumSnapshot` (required `moat`, no
universe discriminator).

**Retention**: the same job, after storing tonight's rows, deletes `SectorEtfReturn` rows whose
`as_of_date` is more than `RETENTION_DAYS` (370) before the newest snapshot just written
(`data/sector_heatmap_data.py::prune_sector_etf_returns`; a row exactly 370 days old is kept).
Measured from that snapshot, not the wall clock, and only reached after a successful compute, so a
failed run never prunes. Steady state is ~255 trading-day snapshots × 88 rows ≈ 22k rows
(weekend/holiday re-runs upsert onto the same anchor; the original 7-window design was ~77
rows/session, ~20k). Backend-only: no past-date UI exists; this just keeps the data one would
need. Two things worth knowing: (1) every snapshot row already carries its own 1d..1y/YTD
returns, so the *current* heatmap's 1Y/YTD columns never depend on retention — it only decides how
far back a *past* snapshot can be read; (2) history starts 2026-09-18, so a full year of
snapshots doesn't exist until Sep 2027. 370 (originally 366, widened 2026-09-21) is so a "same
date one year ago" lookup still finds its row: when that date lands on a weekend/holiday it
resolves to the prior session, up to 369-370 days back.

`pipeline.nightly_sector_heatmap`, 12:35 AM — after Warren (12:25) and before Market Breadth (12:40), one 11-ticker batch (~1-4s). Raises (heartbeat "failure") only if NOTHING
computed; one failed fund is logged and shows blank under the new as-of date rather than a stale
number under a fresh date. The job is wired into `CRON_JOB_NAMES`/`_EXPECTED_CADENCE_HOURS`/
`JOB_METADATA`/`crontab.txt`/`OPS_RUNBOOK.md`; a `crontab.txt` edit alone changes nothing on the
box (reinstall with `crontab crontab.txt` from `backend/` and check `crontab -l`). The first live
run and crontab install are recorded in `docs/archive/claude-md-history-technical-signals.md`.

## API

`GET /api/sector-heatmap` → `{as_of_date, computed_at, windows, rows:[{ticker, name,
cells:{<window>:{return_pct, base_date}}}]}`, fixed universe order; before any run,
`as_of_date: null, rows: []` (never a 404). Display names are a hand-written constant
(`SECTOR_ETFS`).

## UI

`app/sectors/page.tsx`, `components/sectors/SectorHeatmapGrid.tsx`, `lib/sectorHeatmap.ts`. Plain
CSS grid (not a chart library), ETFs as rows, windows as columns. These UI choices were left to
judgment and are open to revision. Color scale is **per
column** (each window's own largest |return| sets that column's intensity ceiling, floored at
1pp so a flat column doesn't paint noise at full saturation) — tints are therefore not
comparable across columns, stated on the page footnote; a fixed per-window clamp was the
considered alternative. Default sort is 3M descending; header clicks re-sort client-side, blank
cells always sink. ETF labels are **not** links — `/tickers/<ETF>` still renders the
stock-shaped page (there is no dedicated ETF ticker-page layout; a companion investigation for
one was never shipped). The nav item "Sectors" opens in a new tab like Momentum/Watchlist/
Settings. Layout, tint legibility and narrow-width behavior were never verified on screen (no
browser was available).

## Why the app's ETF returns differ from a published sector index (2026-09-25 investigation)

A user-reported divergence between Fathom's heatmap and TradingView's GICS sector indices for
several sector ETFs turned out to be **no bug**. Fathom's own numbers reproduce exactly from two
independent sources (FMP direct, Yahoo direct) using the same two anchor dates — the gap to
TradingView is a difference in *what's being measured* (an ETF vs. the underlying GICS index),
not a calculation, date, ticker-mapping, or adjustment fault.

**Likely mechanism (a hypothesis, not independently verified)**: the Select Sector SPDR funds
cap single-name weights (roughly 20-25% for a single name / 50% for the sum of positions above
4.8%), while the S&P 500 GICS sector indices are uncapped cap-weighted. The two sectors where a
few mega-caps dominate the index showed the largest divergence in the investigation's sample,
which fits the capping mechanism; two control sectors with no such concentration tracked the
published index closely, also consistent with it. Dividends don't explain the gap — total return
would shift these numbers by well under 1 percentage point on the control sectors, nowhere near
the several-percentage-point gaps found on the concentrated ones.

## ETF Momentum ranking — investigated, not built

The same 2026-09-20 investigation also scoped a companion feature: applying the existing
3/6/12-month stock-Momentum composite (`scoring/momentum.py::compute_momentum_ranking`,
confirmed universe-agnostic and unmodified-reusable) to a fixed 45-ETF universe (9 of the 11
sector ETFs overlap with it; XLB and XLRE are sector-only). Found fully feasible — both FMP and
Yahoo returned clean data for all 47 combined tickers with no young-fund problem — but never
implemented. Open decisions the investigation left unresolved (return basis, storage shape, a
new `EtfMomentumSnapshot` table since `MomentumSnapshot`'s `moat` column is non-optional and
can't be relaxed by this app's additive-only migration tooling, nav placement) would need
revisiting against the app's current (FMP-only) price-data architecture before this is picked
back up, since the investigation's own source-selection reasoning (recommending Yahoo, at the
time the app's price-only provider) predates the FMP migration and Yahoo's later full removal
(see `docs/archive/claude-md-history-fmp-migration.md`, "Phase 6b").
