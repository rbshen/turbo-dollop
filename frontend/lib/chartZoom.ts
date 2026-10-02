// Pan/zoom geometry for the Chart tab, split out of components/chart/TickerChart.tsx unchanged (the file imports
// lightweight-charts, which unit tests can't load) so it can be tested directly -- including for the 2H·90D
// range, whose 252 candles equal REFERENCE_D1Y_BAR_COUNT, so every range-derived value below is the D·1Y one.

// rightOffset (the empty right-edge margin) is a bar-COUNT, not a pixel
// width -- lightweight-charts fits barSpacing to (bar count + rightOffset)
// bars across the pane's fixed pixel width, so the same rightOffset=10
// produces a visibly different pixel margin per range (D_6M's ~126 bars
// stretch each bar wider than D_2Y's ~504 bars packed into the same
// width). BASE_RIGHT_OFFSET (10) is D_1Y's own already-tuned margin;
// REFERENCE_D1Y_BAR_COUNT (252, the standard trading-days-per-year
// convention -- D_1Y's own 365-calendar-day visible window) is the bar
// count that margin was tuned against. computeRightOffset scales it by
// the CURRENTLY-rendered range's own real bar count, so every range ends
// up with the same PIXEL margin D_1Y already had -- confirmed
// algebraically (and via a standalone numerical simulation replicating
// this library's own fitContent()/setVisibleRange() math) that pane
// WIDTH cancels out of this ratio entirely: the corrected value is
// correct at every window width without re-reading anything from the
// live chart, so no resize-time recomputation is needed -- it's derived
// once from data.bars.length, before the chart is even created.
export const BASE_RIGHT_OFFSET = 10;
export const REFERENCE_D1Y_BAR_COUNT = 252;

export function computeRightOffset(barCount: number): number {
  return (BASE_RIGHT_OFFSET * barCount) / REFERENCE_D1Y_BAR_COUNT;
}

// Pan/zoom bounds, computed directly from the fetched data rather than read back off
// the timeScale. Root-cause fix for a bug where the old code called
// chart.timeScale().fitContent() and then SYNCHRONOUSLY read
// getVisibleLogicalRange() to capture these bounds: fitContent() in
// lightweight-charts 5.2.0 only queues a deferred InvalidateMask (applied on the next
// requestAnimationFrame) rather than recomputing barSpacing/rightOffset immediately,
// so that synchronous read captured the timeScale's PRE-fit state (barSpacing still
// at the library's hardcoded default of 6, not the true fitted value) -- producing a
// minFrom far to the right of the true first bar, silently clamping panning ~1-4
// months short of the true window start depending on pane width/range. Confirmed via
// a jsdom + real-library harness against live chart data, independent of LP zones and
// not zoom-level-dependent (the bad value was fixed once at mount).
//
// minFrom is always 0: the candle series is confirmed (via a live
// /api/tickers/{ticker}/chart check) to be the earliest-starting series of the bunch
// -- no indicator ever has a data point before the first candle -- so index 0 of the
// shared timeScale is always the true first bar, regardless of pane width or timing.
// maxTo mirrors exactly what fitContent() was trying to produce (last real bar +
// the configured right margin); hand-tracing _internal_setVisibleRange's math confirms
// this is self-correcting at RAF-apply time regardless of the LP zone-line
// extension's own baseIndex bump below (extendZoneLinesToEdge), since the library
// derives whatever rightOffset is needed to realize this exact {from,to} using
// whatever baseIndex is current when the queued range is actually applied.
export function computePanBounds(barCount: number): { minFrom: number; maxTo: number } {
  return { minFrom: 0, maxTo: barCount - 1 + computeRightOffset(barCount) };
}

// Shared by the pan-clamp handler (subscribeVisibleLogicalRangeChange, below) and
// the zoom-level effect: translate {from,to} left/right to bring `to` back under
// maxTo (preserving the requested width, i.e. the current zoom level/pan gesture),
// then -- only if that translation would still leave `from` short of minFrom (the
// requested span is wider than the entire fetched range plus margin) -- clamp
// `from` up to minFrom outright, which narrows the span. One shared implementation
// so pan and button-zoom can never drift into two subtly different clamp shapes.
export function clampToPanBounds(from: number, to: number, minFrom: number, maxTo: number): { from: number; to: number } {
  if (to > maxTo) {
    from -= to - maxTo;
    to = maxTo;
  }
  if (from < minFrom) {
    from = minFrom;
  }
  return { from, to };
}

// Discrete ladder of zoom levels, replacing free-form pointer zoom (wheel/
// pinch/drag-to-scale -- see makeChartOptions' handleScale:false below). Each
// multiplier scales the range's own "fit" bar spacing (paneWidth / (barCount +
// rightOffset), i.e. exactly what computePanBounds's maxTo already shows
// end-to-end) -- so level 0 is always precisely the fit level, which is why
// "zoom out" naturally has nothing left to do at index 0 (matches the requirement
// that zoom-out cannot go past the equivalent of fitContent()). Three levels
// total (one fit + two zoom-in steps), geometric rather than linear spacing --
// equal RATIOS between consecutive bar-spacing values read as equal perceived
// zoom steps (bar width is what the eye judges, and halving/doubling a width
// feels like the same-size jump whether it's 3px->6px or 30px->60px; equal
// linear increments would instead make the first click feel huge and the second
// feel trivial).
//
// The max multiplier is range-aware, not a shared constant -- a flat 4.5x for
// every range (the original design) zoomed each range to a very different
// ABSOLUTE bar density, since each range's "fit" spacing starts from a very
// different bar count (D_6M's ~126 bars vs. D_2Y's ~504): confirmed via a
// dedicated investigation that a flat 4.5x always lands at exactly 1/4.5
// (~22%) of a range's own bar count regardless of range, i.e. ~29 bars for
// D_6M (arguably already over-zoomed) vs. ~116 for D_2Y (still fairly wide).
// computeZoomLevelMultipliers instead derives the multiplier from the range's
// OWN bar count so every range converges on roughly the same ABSOLUTE
// TARGET_VISIBLE_BARS_AT_MAX_ZOOM bars visible at max zoom -- computed from
// `data.bars.length` (the real per-ticker count already used for
// computeRightOffset/computePanBounds), not a hardcoded per-range guess, so a
// thin-history ticker degrades the same way the rest of this file already
// does. Floored at 1 so a range/ticker whose bar count is already below the
// target (max zoom would otherwise be a multiplier < 1, i.e. zoomed OUT past
// fit) just gets a flat, inert ladder instead -- canZoomIn's own check
// naturally disables the button in that case since barSpacing stops
// increasing. Capped at MAX_BAR_SPACING_CAP so a still-small-bar-count range
// can't zoom in to where a single candle swallows most of the pane --
// canZoomIn's own cap-aware check (see the zoom-apply effect below) disables
// the button once a level's effective (capped) spacing stops increasing, even
// if that happens before the ladder's last index.
export const TARGET_VISIBLE_BARS_AT_MAX_ZOOM = 50;
export const MAX_BAR_SPACING_CAP = 60;

export function computeZoomLevelMultipliers(barCount: number, rightOffset: number): number[] {
  const maxMultiplier = Math.max(1, (barCount + rightOffset) / TARGET_VISIBLE_BARS_AT_MAX_ZOOM);
  return [1, Math.sqrt(maxMultiplier), maxMultiplier];
}

export function barSpacingForZoomLevel(fitBarSpacing: number, levelIndex: number, multipliers: number[]): number {
  return Math.min(fitBarSpacing * multipliers[levelIndex], MAX_BAR_SPACING_CAP);
}
