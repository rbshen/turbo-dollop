# Chart tab: price-bar fetch behavior and earnings/dividend markers

Scope: how the ticker-page Chart tab gets its bars (`backend/data/chart_data.py`) and how its
earnings/dividend markers work (`data/chart_events_data.py`, `frontend/components/chart/`,
`frontend/lib/chartEventMarkers.ts`). Indicator math (EMA21, SMA50/200, Bollinger, Full Stochastic, RSI)
is in `docs/specs/chart-indicators.md`. Liquidity Zone lines drawn on the chart are in
`docs/specs/liquidity-zones.md`.

## 1. Bar fetch: on demand, zero persistent cache for the daily ranges

The Chart tab has four fixed views (D/6M, D/1Y, D/2Y, W/4Y). Everything is computed on demand on every
request; there is no nightly cron job and no precomputed table for the bars (median ~0.14s combined
daily + weekly fetch, worst case ~0.56s in the latency investigation).

- **D/6M, D/1Y, D/2Y** call `/historical-price-eod/full` (`daily_prices` group) **live and uncached** on
  every request via `fmp_client.get_historical_price_eod` (`chart_data.py::_fetch_bars`). They bypass the
  shared bars cache and the `FundamentalsCache` entirely. The cache is deliberately not used because a flat
  24h staleness TTL with no market-close awareness locked in the prior close for up to a day whenever a row
  was fetched before a session's close, so the tab would show a stale most-recent bar. The direct call
  removes that whole class of bug, and a single-ticker no-state call is simpler than the batch/cache
  machinery built for the nightly jobs.
- **W/4Y** has no FMP weekly endpoint, so the weekly bars are the ticker's ~10y of daily bars
  (`clients/long_history_bars.py`, its **own table**, filled lazily on first view, topped up on a later
  stale view, gated on `daily_prices_long`) resampled with
  `analysis/trend_structure/weinstein.py::resample_to_weekly` (Monday labels, first/max/min/last/sum). This
  is the one place the Chart tab persists anything, and that table is refreshed close-aware, so it cannot
  show the stale-bar bug. With the group off and a stored row, that row is served (cached-only). With no
  row, or an FMP error/empty answer and no row, the chart is empty.
- **FMP is the only provider (since Phase 6b, 2026-09-26).** There is no fallback and no stale-cache
  substitute: when the needed data group is off, or FMP errors or answers empty, the bars are empty and the
  chart renders empty (`chart_available=False`). `ChartOut.source` is always `"fmp"`. Prices are FMP's split-
  AND spin-off-adjusted, **not** dividend-adjusted (~30 tickers' pre-spin-off history differs from
  split-only sources).
- **Scope of the zero-cache rule:** the Chart tab only. Liquidity Zone detection and the other nightly jobs
  read through the shared bars cache (`clients/shared_bars_cache.py`), which is close-aware; see
  `docs/specs/fmp-data-and-bar-cache.md` and `docs/specs/liquidity-zones.md`.
- Known, accepted asymmetry: W/4Y shows 4 years of price, but signal-event markers (BB+RSI/Warren) only reach
  back as far as events have actually been accumulated.

## 2. Earnings and dividend markers

Earnings-report dates ("E", cyan) and dividend ex-dates ("D", violet) on the price pane, in all 4 ranges,
each with its own toggle (`ChartTab.tsx`) and a hover tooltip (EPS actual/estimate/surprise; per-share
amount). They are drawn on a **fixed row along the price pane's floor, independent of price**
(TradingView's convention), as bare bold letters.

### Data

- **Source:** the nightly `CorporateEvent` cache (`docs/specs/corporate-events.md`). `fetch_chart_events`
  reads the cache only: no FMP call per chart request, no timeout wrapper, and it never raises. An uncached
  ticker or a read error gives `events_source=None` with empty lists, and the chart renders without
  markers. An empty stored list is a real answer (TSLA pays no dividend). The events are fetched
  concurrently with the candles and can never fail or stall them. FMP is deep for foreign issuers (HSBC: 39
  quarters of earnings). `FMPClient.get_earnings_history` (limit 40) and `get_dividends` (limit 400) were
  added for this; the existing `get_earnings` (limit 8, cached under `earnings`/`latest`) is not reused.
- **FMP data gotchas (confirmed live):**
  - `/dividends` **ignores `from`/`to`**: it always returns the full history, and `limit` is the only lever.
  - `date` is the ex-date. `dividend` is as-declared and `adjDividend` is split-adjusted. The candles are
    split-adjusted, so `adjDividend` is used (AAPL 2019: $0.77 declared vs $0.1925 adjusted).
  - `/earnings` includes the next scheduled date with null actuals, and pure ETFs (SPY) carry a decade of
    null-actual placeholder rows. Only rows with a real `epsActual`/`revenueActual` count (the same rule
    as `helpers/earnings.py`). A report whose actuals FMP hasn't back-filled yet has no marker until they
    land.
- **Both feeds are forward-looking**, unlike a recorded signal fire. `_marker_bar_time` alone would snap a
  future date onto the newest bar and present a scheduled event as one that happened, so
  `chart_data._bucket_events` drops anything after the last bar (daily) / that week's Sunday (weekly, whose
  bars are Monday-indexed), and never later than today. Events before the first visible bar are dropped by
  the same visible-window rule LP zones use. A weekend/holiday ex-date snaps to the prior trading bar (in
  the weekly view, to its Monday bar); the wire model keeps the real `event_date` alongside the bar `time`
  so the tooltip shows the true date. Two dividends in one bar sum (regular + special). Duplicate earnings
  rows keep the first.
- **Degradation:** no note is shown for either an empty or a failed fetch (the Chart tab has no "not
  tracked" note for its other overlays either), and the toggles stay. Sparse cases: ETFs have dividends
  but no earnings; non-payers and recent IPOs have earnings only; a ticker never cached by the nightly
  corporate-events job has no markers.

### Rendering (fixed-row placement, bare letters)

Drawn as plain "E"/"D" letters (no circle or square) in bold 13px (`EVENT_LABEL_FONT_PX`; the chart's own
axes are 12px). The built-in series markers cannot do this in lightweight-charts 5.2.0: every position
(aboveBar/belowBar/inBar/atPrice*) resolves through `series.priceToCoordinate`, so none is pinned to the
pane; every marker has a shape (`size: 0` hides it, but there is no "none"); and marker text is fixed at the
chart-wide `layout.fontSize`, not changeable per marker. So
`components/chart/EventLabelsPrimitive.ts` is a small custom **series primitive** (one instance per kind,
attached to the candle series, so each keeps its own toggle via `setLabels([])`) that draws in the pane's
own media-pixel space.

- **Position:** the row comes from the pane's REAL height (`mediaSize.height`), exact and not price-derived,
  via `lib/chartEventMarkers.ts::eventLabelCenterY` (letter box bottom = `EVENT_LABEL_FLOOR_PX`, 6px above
  the pane bottom). `zOrder: "top"` so a letter is never hidden behind a candle.
- **Hover:** lightweight-charts 5.2.0's `hoveredInfo`, from the existing crosshair handler, so no extra
  library. Each label carries an `id` (`earnings:<bar time>` / `dividend:<bar time>`). The primitive's own
  `hitTest` (a +/-8px-wide box around each drawn letter, recorded on every draw so it always matches the
  screen) returns the label `id` as `externalId`; the library reports it as
  `hoveredInfo.objectKind === "primitive"`, `objectId === id`, which the crosshair handler resolves via
  `describeEventMarker`. Anything else that reports an id (or none) resolves to no tooltip. The tooltip is
  placed ABOVE the cursor (`eventTooltipPlacement`) since the labels live on the pane floor (a below-cursor
  box would spill over the RSI/Stochastic panes), and it flips to the cursor's left within 200px of the
  right edge.
- **Same-bar collision** (E and D in one bar; plausible in the weekly view): both kinds share one row, so a
  dividend on the same bar as an earnings report is lifted `EVENT_LABEL_STACK_PX` (18px) above it
  (`stackSlot: 1`). This is derived from the data only and is independent of the Earnings toggle, so hiding
  earnings never makes a dividend jump.
- **No candle-scale change needed:** a letter row is ~19px tall (~37px stacked), inside the price pane's
  existing 8% (~45px) bottom margin. The BB+RSI/Warren belowBar arrows reserve their own room through the
  markers plugin's autoscale margins, and event letters no longer share a bar-relative position with those
  arrows, so there is no overlap.
- **Not a new pane, and not literally against the time axis.** The shared time axis sits under the LAST pane
  (Stochastic), so with RSI/Stochastic present the row is at the bottom of the PRICE pane, above the RSI
  pane. A dedicated ~24px 4th pane would sit against the axis but needs a 4th stretch factor, `totalHeight`,
  label offsets and a price scale in the pane; that was not done. BB+RSI/Warren arrows stay price-relative
  (design question left open).
- **Not verified on screen:** how the row looks at each zoom, the library's own hover delivery (jsdom can't
  dispatch its mouse events; the `hitTest` to `hoveredInfo` step was verified by reading the library
  source, not by running it), and the tooltip flip.
