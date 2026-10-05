# Chart tab: price-bar fetch behavior and earnings/dividend markers

Scope: how the ticker-page Chart tab gets its bars (`backend/data/chart_data.py`) and how its
earnings/dividend markers work (`data/chart_events_data.py`, `frontend/components/chart/`,
`frontend/lib/chartEventMarkers.ts`), plus the fifth, intraday **2H·90D** range (section 3). Indicator math (EMA21, SMA50/200, Bollinger, Full Stochastic, RSI)
is in `docs/specs/chart-indicators.md`. Liquidity Zone lines drawn on the chart are in
`docs/specs/liquidity-zones.md`.

## 1. Bar fetch: on demand, zero persistent cache for the daily ranges

The Chart tab has five fixed views (2H·90D, D/6M, D/1Y, D/2Y, W/4Y; the default stays D/6M). The four daily/weekly
views are described in this section; 2H·90D has its own pipeline (section 3). Everything is computed on demand on every
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
- **Scope of the zero-cache rule:** the four daily/weekly ranges only. **2H·90D is the one range that reads the
  shared bars cache** (for a ticker that already has `60m` rows there, i.e. the monitored ones; any other ticker is
  live-fetched without writing anything, see section 3). Liquidity Zone detection and the other nightly jobs
  read through the shared bars cache (`clients/shared_bars_cache.py`), which is close-aware; see
  `docs/specs/fmp-data-and-bar-cache.md` and `docs/specs/liquidity-zones.md`.
- Known, accepted asymmetry: W/4Y shows 4 years of price, but signal-event markers (BB+RSI/Warren) only reach
  back as far as events have actually been accumulated.

## 2. Earnings and dividend markers

Earnings-report dates ("E", cyan) and dividend ex-dates ("D", violet) on the price pane, in the four daily/weekly ranges
(not 2H·90D, which skips the corporate-events read and hides both toggles),
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
  corporate-events job has no markers. (The job is disabled since 2026-10-01, so the markers are frozen at its last
  run, 10-01 02:47: see `docs/specs/corporate-events.md`.)

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

## 3. The 2H·90D range (2026-10-02)

The last 90 calendar days of **2-hour session candles**, with BB+RSI and Warren signals, Liquidity Zones and Warren's
three indicator panes **computed on demand for any ticker** (monitored or not). Backend: `data/chart_data.py::
_get_chart_data_2h` (`range=2H_90D`, `timeframe="2h"`); frontend: `components/ticker/ChartTab.tsx`, `components/chart/
TickerChart.tsx`, `lib/chartTime.ts`, `chartPanes.ts`, `chartToggles.ts`, `chartZoneLines.ts`, `chartZoom.ts`.

### Bars and candles

- **Source: FMP `/historical-chart/1hour`** (`intraday_bars` group; Yahoo is gone since Phase 6b), 60m bars resampled
  into the app's 2h candles: 09:30-11:30, 11:30-13:30, 13:30-15:30 and the short 15:30-16:00, regular session only, aligned
  to the 09:30 ET open. Built by `analysis/entry_signal/resample.py::build_2h_session_candles_fast`, a vectorised
  equivalent of the nightly jobs' `build_2h_session_candles` (bit-identical on all 108 cached tickers; ~100x faster,
  ~9 ms against ~0.85 s). The old function is untouched (BB+RSI and Warren's nightly jobs use it).
- **Cached tickers read the shared bars cache** (`get_or_fetch_bars_batch`, interval `60m`, 730 days, close-aware: warm = a DB read,
  stale = one incremental FMP call that also tops the cache up). **Every other ticker is fetched live and uncached**:
  the 730 days split into 9 parallel 90-day windows (~1.1-2 s; the sequential paging the nightly source uses is ~6 s),
  all-or-nothing (any failed window means no chart), nothing written, so a browsed ticker never gets cache rows from it.
  With `intraday_bars` off, a cached ticker serves its cached bars and any other ticker has none.
  **This deliberately differs from the zero-cache rule of section 1**, which stays true for the four daily/weekly ranges.
- **Window:** the response carries only the last 90 calendar days (~252 candles, which equals the `D·1Y` reference bar
  count, so `computePanBounds`/zoom need no per-range change), but every indicator is computed on the full 730-day series first.
- **Candle time = the window start** (09:30 / 11:30 / 13:30 / 15:30), naive-ET `"YYYY-MM-DDTHH:MM:SS"` strings, for bars, markers,
  zones and the Warren series. (The nightly jobs index a candle by its last 1h bar, 10:30/12:30/14:30/15:30, so a stored `fired_at`
  reads an hour later than the chart's candle.) The frontend turns them into "fake UTC" `UTCTimestamp`s (ET wall-clock
  encoded as UTC), so axis and crosshair read ET and DST switch dates cannot shift anything; only this range sets
  `timeVisible`. The OHLC legend shows the candle's date and full window, e.g. `Tue Sep 29 · 11:30-13:30 ET`
  (an early-close day's last candle still reads 13:30; the wire carries no end time).
- **The forming candle is dropped from display and from every computation** (`drop_forming_candles`, before any indicator runs;
  otherwise Warren would fire arrows that vanish when the candle completes). Only candles dated today (US/Eastern) can be forming;
  one is kept only when **both** the clock (now is at or after the window end 11:30/13:30/15:30/16:00; 13:00 on an early-close day) and the
  data (its last bar is the window's final 60m bar: 10:30/12:30/14:30/15:30) say it is complete.
- **Non-US tickers have no 60m bars**, so the chart is unavailable for them on this range (`chart_available=false`, the frontend's
  existing "No chart data available" state plus a one-line hint); the range button stays, and switching to another range recovers.

### Signals, zones and panes

- **Warren** replays the whole 730-day series (from `today-729d`, the nightly job's own window and `LOOKBACK_DAYS`; a test pins them equal) and
  only then slices to 90 days; replaying just the visible window gives different arrows. The panes' RSI/ADX/WVF are **the very
  series the state machine read** (`replay_with_series`, `ChartOut.warren_rsi/adx/wvf`; the response still carries `warren_plus_di`/`warren_minus_di`, which the chart no longer plots), plus `warren_levels`
  read from the engine constants (RSI 12/30/70/80.81/84.75, ADX 40, WVF 0.40; RSI 12, the ANY-TICKER Blue trigger, is omitted for SPY/QQQ/TQQQ/TECL, which have their own Blue profile, `docs/specs/warren-signal.md`). The existing `rsi` field (EWM RSI) is not reused. For SPY/QQQ/TQQQ/TECL the replay reads volume-guarded candles (`data/warren_signal_data.py::signal_candles`, the same step the nightly store uses; daily volume from the cached 1d bars, else one uncached FMP daily fetch): the candles the chart displays are unchanged and the response has no volume field (`docs/specs/warren-signal.md`, "Volume guard").
- **BB+RSI** markers: `check_buy_signal` on every visible candle, **one marker per firing candle** (no first-per-day/week bucketing as on
  the daily ranges). Warren markers: one per (candle, kind), as before. Arrows are drawn without text on every range ("Signal arrows" below).
- **LP:** computed over the full 730-day 2h series with the shared settings, **except `breach_recency_bars`, hardcoded to 20 candles (5 sessions)** for
  2h only (`LP_2H_BREACH_RECENCY_BARS`; no Settings UI), then **filtered to zones whose swing candle is inside the 90-day window**
  (cap, then filter, as on the daily chart; zone lines start at the swing candle). Because it is a live recompute it uses the **current
  settings immediately**, unlike the nightly Daily/Weekly rows (see `docs/specs/liquidity-zones.md`).
- **Availability flags** (`entry_signal_available`, `warren_signal_available`, `zones_available`) mean only **"bars exist"** on this range, not "monitored".
  Nothing in this range's UI says "not tracked" or "monitored".
- **Sub-panes** (replacing RSI and Stochastic, same 580 main / 100 px sub-pane stretch factors): Warren RSI, Warren ADX, Warren WVF.
  Lines reuse existing chart tokens: RSI `chart-band` grey, **one color on this range (no red beyond 30/70; the daily RSI pane keeps its per-point red)**, ADX `chart-ema21` blue
  (**the ADX line only: +DI and -DI are not plotted, and have no legend entry or header text**), WVF `chart-warren-yellow` (pure yellow `#FFFF00` since 2026-10-05, see "Signal arrows" below). Reference lines are `chart-refline`, all dashed:
  RSI 12, 80.81 and 84.75; ADX 40; WVF 0.40. **The classic RSI 30/70 lines are not drawn** (no line, no axis tag, not in the pane label;
  `lib/chartPanes.ts::drawnRsiLevels` filters them out of `warren_levels.rsi`, which the backend still reports unchanged). **Every dashed line has a price-axis tag** (RSI 12, 80.81, 84.75; ADX 40; WVF 0.40), and each pane's own header text lists all its drawn levels.
  80.81 and 84.75 are only about 4 px apart on the 100 px pane, so their two tags would overlap: those two lines are drawn without a library tag and `components/chart/LevelTagsPrimitive.ts`
  draws their tags instead, nudging the **upper (84.75) tag up and the lower (80.81) tag down by half the shortfall each**, the minimum that stops them overlapping (`lib/chartAxis.ts::nudgeTagYs`; see "Axis options"). The lines stay at their true levels. Each series' autoscale is widened to include its levels
  and the pane keeps 22% top headroom, so a pane label can never sit on a reference line (`lib/chartPanes.ts`).
- **Toggles** in this range: BB+RSI, Warren, LP Support, LP Resistance only. Every other toggle is hidden and forced off in what the chart is told,
  and the saved values in `fathom-chart-signal-toggles` are never touched, so switching back restores them (the Stage-toggle precedent).

### Measured (2026-10-02)

Warm monitored ticker ~100 ms (170 ms first call); uncached ticker 1.4-2.1 s; payload ~94 KB. No cache is needed. Component costs, the
vectorised-builder equivalence, and the consistency check against stored events (Warren latest state 105/105; stored-only events and the BB+RSI tie-break
differences) are in `docs/specs/warren-signal.md`.

### Axis options (every range)

Chart-level axis settings in `lib/chartAxis.ts`, applied by `TickerChart` on **all five ranges** (2H·90D, D·6M, D·1Y, D·2Y, W·4Y).

**Permanent (no toggle, no storage):**
- **Brighter:** axis text color `#e5e8ec` (the text-primary token; it was `#9499a0`). Color only: the axis font size stays 12 px.
- **Fewer ticks:** `tickMarkDensity` 5 (`AXIS_TICK_MARK_DENSITY` = the library's 2.5 x `FEWER_TICKS_FACTOR` 2) on the **price pane's** scale: twice the minimum pixel gap between tick labels. A density rule, not a price step: the
  library snaps the step to its 1/2/2.5/5/10 ladder, so $5 becomes $10 on a price pane of this height at any price level. The sub-panes keep the library default density, which is moot because they draw no tick labels (next bullet).
- **No regular tick labels on any sub-pane** (Warren RSI/ADX/WVF on 2H·90D; the RSI and Stochastic panes on D·6M, D·1Y, D·2Y, W·4Y). Only the axis tags of the level lines remain: Warren RSI 12, 80.81 and 84.75 (the pair nudged, see below), ADX 40, WVF 0.40; daily/weekly RSI 70 and 30; Stochastic 80 and 20.
  The library has no "tags without ticks" option, so each sub-pane's first series gets a `custom` priceFormat whose `tickmarksFormatter` returns empty labels (`addSubPane`); its `formatter` is the default two-decimal one, so the level tags and the crosshair label read as before. The pane layout and
  heights are unchanged; the shared axis width is now set by the price pane's labels (and the 70 px floor). The price pane and the time axis are unaffected.
- **Tabular numerals:** the axis font is the page's concrete monospace family (`readMonoFontFamily`, the next/font `--font-mono` value plus `ui-monospace, monospace`). A canvas font cannot take `font-variant-numeric`, so
  equal-width digits means a monospace face; the previous stack named `var(--font-mono)`, which a canvas `font` string may not resolve, so this also guarantees the face actually reaching the canvas.
- Brighter and Tabular are the chart's single `layout` (lightweight-charts has no per-axis font), so they also colour/face the time axis and the marker text, if any. The E/D letters (own 13 px font) and the pane header text (DOM) are unaffected.
  History: these replace the first-version toggles ("Brighter and larger" 14 px, "Fewer ticks", "Tabular numerals"); "Clean sub-pane axes" and its middle-label primitive were tried and removed the same day.

**The one toggle: Hide overlapping labels, ON by default on every range**, in an **Axis** dropdown in the Chart toolbar (`components/chart/ChartAxisMenu.tsx`, left of Zoom out, shown on every range; button "Axis (n)" with n toggles on, so
**"Axis (1)" by default** and "Axis" with it off). Browser-session state only (`sessionStorage` key `fathom-chart-axis-options`, holding `{hideOverlap}`; nothing in the DB, nothing in `fathom-chart-signal-toggles`). **A stored boolean overrides the default, both ways:**
once a user (or an earlier build, back when the default was off) has stored `{hideOverlap:false}`, it stays off for the rest of that browser session; a stored `true` stays on. No entry, no `hideOverlap` field or junk falls back to the default (on); extra fields from older builds are ignored.
Only a new browser session (empty sessionStorage) shows the new default. When on, a regular **price-pane** tick label is blanked when its y is within `overlapClearancePx(fontSize)` (fontSize + 4 px, center to center) of a price tag on the price axis. Done by giving the candle series a `custom`
priceFormat whose `tickmarksFormatter` blanks those labels and otherwise prints the default two-decimal text (`formatAxisPrice`); off restores the library default `price` format. The tags, the crosshair label and the pane header text are untouched. The price-pane tags (`AxisPane.tags`):
the last visible bar's close (the candle's last-value tag, which follows panning); each LP zone level whose line is visible (its LP toggle on) and has started by the last visible bar; and, on W·4Y while the Stage line is shown, the Weinstein MA's value at the last visible bar (its
last-value tag). It re-tests on every pan and on an LP or Stage toggle. (The sub-panes have no tick labels, so the toggle has nothing to hide there; the earlier per-sub-pane tag lists were removed.)

**Nudging the RSI 80.81 / 84.75 tags** (`LevelTagsPrimitive` + `nudgeTagYs`, read at draw time so it follows autoscale and panning): a tag is `axisTagHeightPx(fontSize)` tall (the font plus the library's padding: 17 px at 12 px). Each tag's y starts at its
line's y (`priceToCoordinate`). Only when two tags are closer than one tag height are they separated, symmetrically: the upper tag moves up and the lower tag down by half the shortfall each (so the pair ends exactly one tag height apart, the
minimum), clamped inside the pane. Tags already clear of each other do not move. The tags are placed with `fixedCoordinate`, which the library never moves itself, so each stays tied to its own line (its text is its own level). With the pane ~1 px per
RSI point, 80.81 and 84.75 sit about 4 px apart, so each tag moves about 6.5 px. The library's own overlap fix would have pushed only the upper tag, by the whole shortfall.

**Not verified on screen** (no browser in the build environment): the exact pixel clearance at which a tag and a tick label touch (derived from the font size, not measured); the look of the nudged tags (the primitive's text color is white on the
`chart-refline` fill, approximating the library's own tag contrast color); the rendered monospace face; the price pane's tick count under the density rule; and that the blank-tick sub-pane scales still lay out the shared axis width as expected. Pinned by tests instead: the permanent layout and
density, the blank sub-pane formatters on every range, the surviving level tags, the toggle's default and its formatter, the price-pane tag lists (including the W·4Y MA and the LP toggle), and the nudge geometry.

### Signal arrows (every range)

The BB+RSI and Warren arrows are **glyphs only**: the markers are built without `text`, so no label ("BB+RSI", "Blue Up", "Yellow Down", "Gray Down", ...) is drawn next to an arrow on any range. The marker `label`/`kind` still travel in the response
(`ChartOut.*_markers`) and are used elsewhere (Technical tab, Screener); the chart ignores `label`. The E/D letter row (section 2) is not an arrow label and is unchanged. Nothing else read the marker text: no chart tooltip uses it (the only chart tooltip is the E/D one).

Warren yellow arrows (and the WVF line, which shares the token) are `chart-warren-yellow`, **`#FFFF00`** (TOS `Color.YELLOW`) since 2026-10-05; it was `#F59E0B` (Tailwind amber-500), which reads orange. The yellow stop line is not drawn on the chart, so there was nothing else to change.
