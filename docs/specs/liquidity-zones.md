# Liquidity Zone (LP) detection (Technical)

A fourth, fully independent technical-analysis lens on the ticker page's Technical tab: unbreached
swing-low **support** and swing-high **resistance** levels, clustered into zones, on both a **Daily**
(trailing 1yr) and a **Weekly** (4yr, resampled from the same fetched daily frame) timeframe. Like the
swing/BOS engine, A/D Bullish Divergence, SMA position tracking, Weinstein Stage Analysis and BB+RSI entry
signals, it never touches Step 1-5 / Overall Assessment scoring or any other lens; it is a second,
parallel read on price structure.

`analysis/liquidity_zones/engine.py`'s module docstring is the source of truth for the rules below. Its
rules follow the reference "Left Precedence" Pine script (verified line by line: swing detection, breach
timing, clustering walk, cap priority, kept-breached rule). The rules were aligned to that script on
2026-09-25, which superseded the earlier "later swing only" breach semantics, the 2026-09-17
most-recently-breached tracking rule and the per-timeframe settings (all kept as history in
`docs/archive/claude-md-history-technical-signals.md`).

## Engine (`backend/analysis/liquidity_zones/`)

Pure functions/dataclasses, no DB or HTTP. Fractal swing-low/swing-high detection runs on **Low/High**
(not Close, unlike `trend_structure/swings.py`, which is Close-only and hardcoded to N=5) with a
caller-configurable window, so it is a small independent implementation using the same vectorized shift
technique. The engine recomputes from scratch on every nightly run (the same shape as the Warren signal
engine, not `trend_structure`'s incremental state machine), and `swings.py::annotate_swings` computes
`breach_pos` for every swing whether or not it is still valid, so the full breach history is available in
memory on every run.

- **Breach = ANY later bar** whose Low (support) / High (resistance) crosses the level, strictly. Once
  breached, always breached (`swings.py::annotate_swings`). A swing low becomes a support LP once it is
  confirmed and stays valid until a later bar's Low trades below it; resistance is symmetric.
- **Clustering.** Consecutive valid zones within `cluster_pct`% collapse into one. A cluster's
  representative is the price at which the *whole zone* is genuinely broken: support clusters collapse to
  their **lowest** member (price must sink below the deepest point before the zone is truly gone, so the
  lowest price is the conservative "last line of defense"), resistance clusters to their **highest** member
  (price must clear the highest point before the zone is truly broken through).
  `analysis/liquidity_zones/clustering.py::cluster_prices` is one shared, direction-parameterized function
  (`representative: "min" | "max"`), not two copies.
- **Cap.** After clustering, at most `max_lps_per_side` valid zones are kept per side: the nearest to the
  last close (`nearest_price`) or the most recently formed (`most_recent`), per `over_cap_priority`. The
  order is cluster then cap. The wrong-side-of-price filter (a "support" above today's price, or a
  "resistance" below it) is now only a guard: with any-bar breach a valid support can never sit above the
  last close, nor a valid resistance below it.
- **Kept-broken level (one per side, optional).** Threshold = the best RAW valid swing price on that side
  (highest support / lowest resistance, before clustering and the cap, per the Pine `findKeptBreached`).
  Candidates are breached swings beyond it (support price > threshold, resistance price < threshold; all
  qualify if there is no valid zone), optionally only those breached within `breach_recency_bars` of the
  last bar (measured from the BREACH bar, inclusive). The one closest to the threshold (lowest support /
  highest resistance) wins. Ties on price prefer the later breach, then the later formation. Breached
  candidates are never clustered, so at most one `BrokenZone` exists per side per timeframe. Cosmetic Pine
  inputs were not ported.

## Settings

One shared, runtime-editable block for Daily and Weekly: table `LiquidityZoneSettings` (singleton `key`-PK
row, lazy-seeded get-or-create like `MoatScoreConfig`/`ReitDividendYieldConfig`, via
`helpers/liquidity_zone_config.py`), edited through `GET/PUT /api/config/liquidity-zones` and the
`/settings` section (`LiquidityZoneSettingsForm.tsx`).

| Field | Fresh-seed default (`helpers/liquidity_zone_config.py`) |
|---|---|
| `swing_bars_each_side` | 2 |
| `cluster_pct` | 0.0 |
| `max_lps_per_side` | 3 |
| `over_cap_priority` | `nearest_price` (or `most_recent`) |
| `keep_last_breached_support` / `keep_last_breached_resistance` | true / true |
| `only_keep_if_breached_recently` | true |
| `breach_recency_bars` | 5 |

The 2026-09-25 alignment seeded `cluster_pct` 2.0 and `max_lps_per_side` 10; the code defaults above
reflect a later change (commit `159753a`, "new max-zones default"), so read the helper for the live
values. The table replaced the per-timeframe `LiquidityZoneConfig` table, which is orphaned on disk (a new
table because `_add_missing_columns` cannot relax its NOT NULL columns); old tuned values were not carried
over. A settings change takes effect on the **next nightly run**, not retroactively. This feature has no
live-recompute path the way Step 3's discount rate does. BB+RSI's own thresholds (`RSI_LENGTH`, `BB_STD`,
etc.) remain hardcoded constants with no settings UI; this feature was the first Technical-tab lens with
DB-backed settings.

## Data source

FMP daily bars (`daily_prices` group), read through the shared bars cache (`clients/shared_bars_cache.py`,
interval `"1d"`, ~4yr = `LOOKBACK_DAYS` in `data/liquidity_zone_data.py`). Trend/Weinstein read the same
row at a narrower (2y) width, so whichever nightly job runs first does the one live fetch per overlapping
ticker and the other reads it back. FMP has no native weekly feed (`/historical-chart/1week` returns 404),
so Weekly bars are always derived by resampling Daily, reusing
`analysis/trend_structure/weinstein.py::resample_to_weekly`. A single fetch per ticker serves both
timeframes: `data/liquidity_zone_data.py` slices the trailing 1yr (`DAILY_LOOKBACK`) for Daily and
resamples the full frame for Weekly. Each stored row's `source` is always `"fmp"`. (The old
`daily_price_sources.py` module was deleted 2026-09-19 when the shared bars cache took over.)

**Freshness.** A cached bar row is trusted only if its own last bar matches the most recently completed
session (`shared_bars_cache._most_recent_completed_trading_date`: US/Eastern, weekday-aware, deliberately
NOT holiday-aware); otherwise a live refetch is forced regardless of the flat staleness window. The nightly
job originally missed this: because it fetches tickers sequentially at a fixed wall-clock time, whether a
row looked "stale" depended on run-speed jitter, leaving some rows 1-3 nights stale. The cache is kept for
this job (one fetch per ticker per night, so a warm and genuinely current row still means zero live FMP
calls).

## Data model

`LiquidityZoneAnalysis`, composite PK `(ticker, timeframe)`, so Daily and Weekly coexist as independent rows
(the precedent is `TechnicalEntrySignal`'s composite-PK table, not `TrendAnalysis`'s ticker-only wide
table). `support_zones_json` / `resistance_zones_json` are plain-string JSON columns holding a list of
`{price, cluster_size, formed_at}` objects, this codebase's convention for JSON-shaped fields (not a native
JSON column type). `broken_support_json` / `broken_resistance_json` are nullable single-object JSON columns
(`{price, formed_at, breached_at}` or `NULL`), matching `TrendAnalysis.last_confirmed_swing_json`'s
single-object convention since at most one broken zone exists per side per timeframe.
`sweep_stale_liquidity_zones` clears a stale row's zone lists to `"[]"` and both broken columns to `NULL`.
`ZoneOut.distance_pct` is derived at read time from the zone's price and the timeframe's own `last_price`,
never stored.

## Nightly job

`pipeline/nightly_liquidity_zone_calculation.py`, **12:15 AM** server time (UTC), a dedicated job rather than
part of `nightly_entry_signal_calculation.py`, even though both are scoped to the same deduped W1-W5
watchlist union (`data/watchlists.py::list_tickers_across_watchlists`). It is separate because every
pipeline script maps 1:1 to one feature, because it needs a different data group (`daily_prices`, versus
BB+RSI's `intraday_bars`), and because separate `cron_heartbeat` names keep failure attribution clean (an
FMP outage affecting Liquidity Zones must not read as a BB+RSI health failure or vice versa). It sits right after the
12:05 trend job (whose bar-cache fill it reads warm) and before BB+RSI (12:20); `backup_db` runs at 3:30 (see
`backend/crontab.txt` for the current slots), since this job can make live FMP calls on a cold cache. It is registered in `core/cron_health.py`'s `CRON_JOB_NAMES` /
`_EXPECTED_CADENCE_HOURS` as `pipeline.nightly_liquidity_zone_calculation`. The job is skipped while the
`daily_prices` group is off. After the per-ticker loop it sweeps rows whose `computed_at` is older than
`STALE_AFTER_DAYS` (7), e.g. a ticker dropped from every W1-W5 list, clearing rather than deleting them.
Tickers on none of W1-W5 have no row at all.

## API and UI

- `GET /api/tickers/{ticker}/liquidity-zones` returns the Daily and Weekly zones (`None` if the ticker was
  never computed).
- **`LiquidityZonesCard`** (`frontend/components/technical/`) on the Technical tab, fetched independently
  (`useLiquidityZones`, not gated on the trend-analysis load state, same convention as `useEntrySignal`).
  Daily and Weekly sit side by side, each with its nearest resistance zones (above price), a current-price
  divider, and nearest support zones (below price). Each zone row shows price, distance from last price,
  cluster size ("N swings merged", omitted for a single-swing zone), and when it formed. The ladder is sized
  to the most zones any side has (capped), not the cap itself.
- **Empty-zone behavior (explicitly decided):** a side with zero currently-valid zones for a timeframe
  (sparse/early history, or price hasn't pulled back far enough to form one) shows a plain "No confirmed
  support/resistance levels yet" line while the rest of the card renders normally. A ticker never computed
  (on none of W1-W5, or not yet processed) renders the same "Not tracked" shape `BbRsiEntrySignalCard`
  uses, explaining the W1-W5-only scoping, rather than four empty sections.
- **Broken-zone row.** When `broken_support` / `broken_resistance` is non-null, a dashed "Broken" row
  (`BrokenZoneRow`, same colors as the chart, kept in sync manually) renders for that side. It is placed
  immediately adjacent to the current-price divider: appended after the regular resistance ladder and
  prepended before the regular support ladder. That follows from the engine's positional rule (a kept
  broken zone always sits closer to price than every remaining valid zone on its side). It sits outside the
  `numSlots`-capped, blank-padded ladder (`ZoneList` takes an optional `broken` prop) so it never consumes
  one of the fixed Daily/Weekly alignment slots.
- **Chart display.** `ChartZoneOut` has a `broken: bool` field; `chart_data.py::_filter_zones` emits at most
  one broken-zone entry per side, subject to the same visible-window `formed_at` cutoff active zones use (a
  zone formed before the visible window has no bar to anchor a line start). `TickerChart.tsx` reuses the
  same `LineSeries` / `extendZoneLinesToEdge` mechanism as an active zone (extends to today's edge, not
  truncated at the breach bar). Only the color differs: `#FF9800` (`chartZoneBrokenSupport`) for a broken
  support and `#E040FB` (`chartZoneBrokenResistance`) for a broken resistance, versus green/red for active
  zones (`frontend/lib/chartTokens.ts`). They are grouped into the existing `showLpSupport` /
  `showLpResistance` visibility toggles by side, so there is no separate toggle.
