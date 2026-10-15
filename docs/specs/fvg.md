# Fair value gap (FVG) overlay on the Chart tab (D·6M only)

Scope: the shaded gap zones drawn behind the candles on the **D · 6M** range. Backend `analysis/fvg.py` (pure detection),
`data/chart_data.py::_fvg_zones` (windowing, wire format), `ChartOut.fvgs`; frontend `lib/chartFvg.ts` (geometry),
`components/chart/FvgZonesPrimitive.ts` (drawing), the "FVG" toggle in `lib/chartToggles.ts`. Decisions: `docs/decisions.md`, 2026-10-15.

## Detection (`analysis/fvg.py::detect_fvgs`)

Three candles c1, c2, c3 (c4 is the one after c3).

- **Bullish** when `low(c3) > high(c1)`: zone bottom = `high(c1)`, top = `low(c3)`.
- **Bearish** when `high(c3) < low(c1)`: zone top = `low(c1)`, bottom = `high(c3)`.
- Strict inequalities; a zero-height gap is not a gap.
- **Size filter:** kept only if height `> FVG_ATR_MULTIPLIER x ATR(14, Wilder)` at c3. `FVG_ATR_MULTIPLIER = 0.5` is a named constant in
  `analysis/fvg.py`, not a Setting. A height equal to the threshold is excluded. A missing (NaN) or non-positive ATR keeps nothing (fail
  closed; a bar before the ATR has warmed up can never be a c3: the first possible c3 is the 14th bar). ATR is `analysis/warren_signal/indicators.py::compute_atr_wilder`
  (`wilder_rma` of `_true_range`; no new math).
- **Ending:** the zone ends at the first candle after c3 whose **close** is beyond the far side (bullish: close `<` bottom; bearish: close `>` top),
  strict. A wick through the zone, or a close exactly on the boundary, never ends it. A candle that closes straight through with no earlier touch
  ends it too. The ATR filter affects detection only, never the ending.
- Overlapping zones are all kept (no merging).

## Window rule and response (`ChartOut.fvgs`)

- Detection runs on the **full fetched frame** (730 days, so the ATR is warm and an old gap's ending is known). A gap is kept only if
  **c3 is on or after `visible_start`** (the same cutoff `_filter_zones` applies to LP lines). An older still-alive gap is not shown.
- Filled **only when `range_key == "D_6M"`**; every other range answers `fvgs: []`. No cache, no job, no extra fetch. The viewer chart cache
  (`data/viewer_chart_cache.py`, keyed by ticker and range) carries the field unchanged.
- Entries (`ChartFvgOut`): `{side: "bullish" | "bearish", top, bottom, start_time, end_time | null}`, times `YYYY-MM-DD`.
  - `start_time` = c4's bar. `end_time` = the ending bar, or `null` while the zone is open.
  - **Projected case (wire format):** when c3 is the last bar there is no c4. The entry has `end_time: null` **and** `start_time` = the next
    weekday after the last bar (a placeholder date, not a real bar; holidays are not skipped). So `end_time == null && start_time > last bar time`
    means "no c4 yet". The client draws it one bar wide, one bar to the right of the last bar.

## Drawing (`FvgZonesPrimitive`, attached to the candle series, price pane only)

- `zOrder: "bottom"` (behind the candles). X from `timeScale().logicalToCoordinate` at the bar **edges** (a bar's center is logical `i`, edges
  `i -+ 0.5`), y from `series.priceToCoordinate`; a zone with any null coordinate is skipped. No `autoscaleInfo`, so it never changes the price scale.
- Span (`lib/chartFvg.ts::fvgSpan`): from **c4's left edge** to the **ending bar's right edge**; an open zone to the **last bar's right edge**;
  a zone that ends on c4 is a one-bar-wide sliver; the projected case spans `[n - 0.5, n + 0.5]` (n = bar count), inside the right margin.
  A start or end time that is not a bar is skipped.
- Each zone: a filled rectangle at 14% alpha plus 1px dashed top and bottom edge lines at 58% alpha (`withAlpha`), no price-axis tag.
- Colors: `chart-fvg-bullish` `#0891B2` and `chart-fvg-bearish` `#F472B6` (`docs/design-system-charts.md`). Not the candle green/red.

## Toggle

"FVG" in `lib/chartToggles.ts`, after LP Resistance, **default on**, offered on D · 6M only (`FVG_TOGGLE_RANGE`, an explicit branch in `isToggleOffered`),
forced off in what the chart is told elsewhere, the saved value never touched (the Stage precedent). Same shared `fathom-chart-signal-toggles`
key; an object saved before the key existed loads with FVG on. The backend always computes; the toggle only controls visibility.
