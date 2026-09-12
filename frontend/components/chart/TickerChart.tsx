"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, LineSeries, createSeriesMarkers, LineStyle } from "lightweight-charts";
import type { IChartApi, ISeriesApi, ISeriesMarkersPluginApi, Logical, LogicalRangeChangeEventHandler, Time } from "lightweight-charts";
import { fmtMoney } from "@/lib/format";
import type { ChartOut } from "@/lib/api/types";

// Ported from Options Tracker's PositionChart.tsx (lightweight-charts
// 5.2.0), stripped of everything position/IBKR-specific (position-anchored
// default range, the live-fetch/source:cache|live distinction, position-
// lifecycle markers, the per-user style-color Settings plumbing -- colors
// are hardcoded constants here instead, same "no end-user config UI"
// convention every other Technical-tab feature already uses) and extended
// from two stacked chart instances (price + RSI) to three (price, RSI,
// Stochastic).
//
// Originally three fully independent `createChart()` instances (one per
// pane) bridged by a hand-rolled `subscribeCrosshairMove` relay -- each
// instance computed its own bar spacing and price-scale rounding
// independently, which left a small but real crosshair/axis misalignment
// between panes no amount of tuning a shared `minimumWidth` could fully
// close (two rounds tried). Rewritten onto lightweight-charts' native
// multi-pane API (one `createChart()` call, three panes via
// `addSeries(..., paneIndex)`) so all three share a single time scale --
// axis-width equality and crosshair alignment become structural
// guarantees of the library's own per-chart layout pass instead of
// something three independent instances have to be kept in sync by hand.
const CHART_THEME = {
  background: "#09090b",
  text: "#71717a",
  border: "#27272a",
};

const COLORS = {
  upCandle: "#10b981",
  downCandle: "#ef4444",
  ema21: "#3179F5",
  sma50: "#4CAF50",
  sma200: "#F23645",
  bollinger: "#808080",
  rsi: "#808080",
  stochK: "#F23645",
  stochD: "#808080",
  // Reuses upCandle's green -- the only "up/bullish" green already defined
  // in this component, for a bullish entry-signal marker.
  marker: "#10b981",
  // Same dark gray previously used for the main pane's last-close price
  // line (since removed) -- distinct from the #808080 RSI/StochD
  // data-line gray so the static 70/30 and 80/20 reference lines read as
  // background guides, not data.
  refLine: "#52525b",
  // Liquidity Zone (LP) support/resistance overlay -- reuses the candle
  // up/down colors directly (green floor, red ceiling), per explicit
  // request. An earlier version deliberately avoided green/red here to
  // keep a support/resistance level from misreading as a bullish/
  // bearish signal the way the candles themselves use those colors --
  // superseded by this request.
  lpSupport: "#10b981",
  lpResistance: "#ef4444",
  // Warren RSI/ADX/WVF's own Blue/Yellow/Gray convention, per the
  // reference script -- distinct from BB+RSI's plain green `marker`
  // above, and reused identically for both the Up (buy) and Down (sell)
  // variant of each color (position/shape alone distinguishes direction).
  warrenBlue: "#3179F5", // same blue already used for ema21
  warrenYellow: "#f59e0b",
  warrenGray: "#a1a1aa",
};

// One entry per Warren signal_kind (see ChartMarkerOut.kind) -- color by
// Blue/Yellow/Gray, shape/position by Up (buy, below the bar) vs. Down
// (sell, above the bar).
const WARREN_MARKER_STYLE: Record<string, { color: string; shape: "arrowUp" | "arrowDown"; position: "belowBar" | "aboveBar" }> = {
  blue_up: { color: COLORS.warrenBlue, shape: "arrowUp", position: "belowBar" },
  yellow_up: { color: COLORS.warrenYellow, shape: "arrowUp", position: "belowBar" },
  gray_up: { color: COLORS.warrenGray, shape: "arrowUp", position: "belowBar" },
  blue_down: { color: COLORS.warrenBlue, shape: "arrowDown", position: "aboveBar" },
  yellow_down: { color: COLORS.warrenYellow, shape: "arrowDown", position: "aboveBar" },
  gray_down: { color: COLORS.warrenGray, shape: "arrowDown", position: "aboveBar" },
};

const RSI_OVERBOUGHT = 70;
const RSI_OVERSOLD = 30;
const STOCH_OVERBOUGHT = 80;
const STOCH_OVERSOLD = 20;

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
const BASE_RIGHT_OFFSET = 10;
const REFERENCE_D1Y_BAR_COUNT = 252;

function computeRightOffset(barCount: number): number {
  return (BASE_RIGHT_OFFSET * barCount) / REFERENCE_D1Y_BAR_COUNT;
}

// Fixed pixel heights per pane -- unchanged from the three-separate-charts
// era, just applied via Pane.setHeight() now instead of each chart's own
// `height` option.
const MAIN_PANE_HEIGHT = 520;
const RSI_PANE_HEIGHT = 120;
const STOCH_PANE_HEIGHT = 120;
// lightweight-charts' own pane-separator height (confirmed as a fixed 1px
// constant in lightweight-charts.development.mjs), which the library now
// draws natively between panes sharing one chart, replacing the old CSS
// `border-t` divider between three separate chart divs. Only used below to
// compute the RSI/Stochastic overlay labels' vertical offset -- a 1px miss
// here would be a cosmetically negligible label position, not a layout
// break, since the panes' own real heights are set directly via
// setHeight() regardless of this constant.
const PANE_SEPARATOR_HEIGHT = 1;

// Minimum price-scale (y-axis) width, purely a readability floor now (e.g.
// for a hypothetical ticker where every pane's labels happen to be very
// short) -- NOT load-bearing for cross-pane width equality the way it was
// across three independent chart instances. Now that price/RSI/Stochastic
// are three panes of one chart, lightweight-charts' own per-chart layout
// pass (ChartWidget._private__adjustSizeImpl, confirmed in
// lightweight-charts.development.mjs) takes Math.max across every pane's
// natural label width AND this floor, once, for the whole chart -- so
// every pane gets the same width structurally, not because this constant
// happens to be tuned larger than any one pane's real need.
const PRICE_SCALE_MIN_WIDTH = 70;

interface OhlcState {
  o: number;
  h: number;
  l: number;
  c: number;
}

function makeChartOptions(rightOffset: number, height: number) {
  return {
    layout: {
      background: { color: CHART_THEME.background },
      textColor: CHART_THEME.text,
      fontSize: 11,
      fontFamily: "var(--font-mono), ui-monospace, monospace",
      attributionLogo: false,
      // Static, non-resizable stacked panes -- matches the old fixed-height
      // three-separate-divs look (no user-facing pane resize handle).
      panes: { enableResize: false, separatorColor: CHART_THEME.border, separatorHoverColor: CHART_THEME.border },
    },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    handleScroll: true,
    handleScale: true,
    rightPriceScale: { borderColor: CHART_THEME.border, minimumWidth: PRICE_SCALE_MIN_WIDTH },
    // shiftVisibleRangeOnNewBar defaults to true (a "streaming chart"
    // convenience: auto-scroll to keep showing rightOffset's margin ahead
    // of a genuinely new incoming bar). This chart never streams -- every
    // range switch tears down and recreates the whole chart from data
    // fetched once -- but it DOES call series.setData() a second time
    // after the initial render, to extend LP zone lines into the
    // rightOffset margin (see extendZoneLinesToEdge below). Left at its
    // default, that second setData() is indistinguishable from "a new bar
    // arrived," so the model silently scrolls the whole visible window
    // right by the same distance instead of just filling the margin --
    // confirmed via a standalone numerical simulation of this library's
    // own TimeScale math (not just re-reading the code): the zone line's
    // extension only reached ~96% of the way to the true edge, and 10
    // bars of real history were silently cropped off the left. Set false
    // here so a later setData() only ever changes what's drawn, never
    // the visible range itself.
    //
    // One shared time axis for the whole pane stack now (previously
    // hidden per-instance on the RSI/Stochastic charts, since each had
    // its own); left visible so dates render once, at the true bottom of
    // however many panes actually exist, instead of only under the price
    // pane as before.
    //
    // fixLeftEdge: true blocks panning past the first fetched bar --
    // verified safe, no interaction with anything else in this file (it
    // only nudges rightOffset to keep the first bar in view if a pan/zoom
    // would otherwise reveal empty space to its left).
    //
    // fixRightEdge is deliberately NOT set here, even though it looks
    // like the obvious mirror of fixLeftEdge. Confirmed via the library's
    // own source AND a standalone empirical run (a real chart instance,
    // not just reading code) that fixRightEdge:true hardcodes the
    // right-edge bound to baseIndex+0 -- i.e. exactly the last real bar,
    // ZERO margin -- unconditionally, regardless of the configured
    // rightOffset above. That collapses this app's own tuned right
    // margin (computeRightOffset/BASE_RIGHT_OFFSET) to nothing on every
    // chart load, not just under user panning, and silently breaks
    // extendZoneLinesToEdge below: its synthetic future points still get
    // added, but the visible right edge stays pinned at the last real
    // bar, so they render entirely off-screen instead of visibly
    // extending an active LP zone line into the margin. Baking the
    // margin into the data itself as literal whitespace points doesn't
    // route around this either -- the same hardcoded 0 bound applies no
    // matter how the visible range is reached. See the
    // subscribeVisibleLogicalRangeChange handler in the mount effect
    // below for the equivalent right-edge bound that preserves the
    // margin instead of zeroing it.
    timeScale: {
      borderColor: CHART_THEME.border,
      timeVisible: false,
      rightOffset,
      shiftVisibleRangeOnNewBar: false,
      fixLeftEdge: true,
      // Zoom bounds. maxBarSpacing caps zoom-IN so a single candle can
      // never swallow most of the pane. minBarSpacing is a defensive
      // floor well below any real range's natural fitContent() spacing
      // (D_2Y, the densest range at ~504 bars, still fits comfortably
      // above this even on a narrow viewport) -- true zoom-OUT bounding
      // comes from fixLeftEdge plus the visible-range clamp below, which
      // together cap the visible span at "everything the range fetched,
      // plus the existing margin," so minBarSpacing here only guards
      // against a one-frame flash of over-thin bars before that clamp
      // corrects it, not the primary bound.
      minBarSpacing: 1,
      maxBarSpacing: 60,
    },
    crosshair: { mode: 1 },
    height,
  };
}

interface OverlayVisibility {
  showBbRsi: boolean;
  showWarren: boolean;
  showLpSupport: boolean;
  showLpResistance: boolean;
  showBollinger: boolean;
  showEma21: boolean;
  showSma50: boolean;
  showSma200: boolean;
}

function addMainSeries(chart: IChartApi, data: ChartOut, visibility: OverlayVisibility) {
  // No paneIndex passed -- defaults to pane 0, the main price pane.
  const candle = chart.addSeries(CandlestickSeries, {
    upColor: COLORS.upCandle,
    downColor: COLORS.downCandle,
    wickUpColor: COLORS.upCandle,
    wickDownColor: COLORS.downCandle,
    borderVisible: false,
    // Candlestick series default to priceLineVisible: true (an
    // auto-drawn horizontal line at the last bar's close, colored by the
    // last candle's own up/down color) -- confirmed via
    // SeriesOptionsCommon in typings.d.ts, not assumed. No last-close
    // line is wanted here at all -- the OHLC legend in the top-left
    // corner already shows the close value -- so this stays false; the
    // component's own separate manual last-close createPriceLine() call
    // (which duplicated this one) has been removed outright rather than
    // left disabled.
    priceLineVisible: false,
  });
  candle.setData(data.bars);

  // Overlay visibility is set at creation time via the `visible` series option (not by skipping series creation
  // outright) so a later toggle-on can flip it back via applyOptions({ visible: true }) -- see the overlayApiRef
  // effects in the component below -- without recreating the series or the chart.
  const overlayToggleForKey: Record<"ema21" | "sma50" | "sma200", boolean> = {
    ema21: visibility.showEma21,
    sma50: visibility.showSma50,
    sma200: visibility.showSma200,
  };
  const overlaySeries: { ema21: ISeriesApi<"Line"> | null; sma50: ISeriesApi<"Line"> | null; sma200: ISeriesApi<"Line"> | null } = {
    ema21: null,
    sma50: null,
    sma200: null,
  };
  for (const [key, color] of [
    ["ema21", COLORS.ema21],
    ["sma50", COLORS.sma50],
    ["sma200", COLORS.sma200],
  ] as const) {
    const pts = data[key];
    if (!pts.length) continue;
    const line = chart.addSeries(LineSeries, {
      color,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      visible: overlayToggleForKey[key],
    });
    line.setData(pts);
    overlaySeries[key] = line;
  }

  const bollingerSeries: ISeriesApi<"Line">[] = [];
  if (data.bollinger.length) {
    // Only the upper/lower bands are plotted -- the basis (middle) line is
    // computed on the backend (bb_basis, EMA(20)) and still feeds the
    // upper/lower math, but its own chart series is dropped: now that BB's
    // basis is EMA(20) and the separate trend line above is EMA(21), the
    // two read as visually near-redundant on the chart.
    for (const key of ["upper", "lower"] as const) {
      const bb = chart.addSeries(LineSeries, {
        color: COLORS.bollinger,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        visible: visibility.showBollinger,
      });
      bb.setData(data.bollinger.map((b) => ({ time: b.time, value: b[key] })));
      bollingerSeries.push(bb);
    }
  }

  // Liquidity Zone (LP) support/resistance levels -- a LineSeries per
  // zone, not createPriceLine: PriceLineOptions (confirmed via v5.2.0's
  // own typings, no partial-range option exists) has no time-bound field
  // at all, so createPriceLine always spans the full chart width
  // regardless of when the zone actually formed. A LineSeries fed only
  // the bars from formed_at onward naturally starts drawing exactly at
  // that swing point and stops at the last visible bar -- the caller
  // (see useLayoutEffect below) extends each one past the last real bar, into
  // the rightOffset margin, only AFTER fitContent() has run.
  //
  // Two distinct SeriesOptionsCommon fields govern what shows next to a
  // series, and they're independent: `lastValueVisible` is the numeric
  // last-value label on the price axis itself (what we want here, since
  // every point on a zone's line is the same price, so its "last value"
  // IS the zone's level); `title` is a text name appended next to that
  // label (left unset/empty so no "LP Support"/"LP Resistance" text
  // appears anywhere). `priceLineVisible` is a THIRD, unrelated thing --
  // an auto-drawn horizontal line spanning the whole pane at the series'
  // last value -- kept false since enabling it would reintroduce the
  // exact full-width-regardless-of-formed_at problem this LineSeries
  // switch was built to fix, just via a different mechanism.
  const zoneLines: { series: ISeriesApi<"Line">; points: { time: string; value: number }[] }[] = [];
  const lpSupportSeries: ISeriesApi<"Line">[] = [];
  const lpResistanceSeries: ISeriesApi<"Line">[] = [];
  for (const zone of data.zones) {
    const isSupport = zone.side === "support";
    const points = data.bars.filter((b) => b.time >= zone.formed_at).map((b) => ({ time: b.time, value: zone.price }));
    if (!points.length) continue;
    const zoneLine = chart.addSeries(LineSeries, {
      color: isSupport ? COLORS.lpSupport : COLORS.lpResistance,
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
      visible: isSupport ? visibility.showLpSupport : visibility.showLpResistance,
    });
    zoneLine.setData(points);
    zoneLines.push({ series: zoneLine, points });
    (isSupport ? lpSupportSeries : lpResistanceSeries).push(zoneLine);
  }

  // The plugin instance is created whenever there's data to potentially show (regardless of the current toggle
  // state) so a later toggle-on can call setMarkers() on it directly (see the showBbRsi/showWarren effects in the
  // component below) without recreating the series or the chart -- only the INITIAL markers array passed here is
  // gated on the toggle.
  let bbRsiMarkersApi: ISeriesMarkersPluginApi<Time> | null = null;
  if (data.entry_signal_markers.length > 0) {
    bbRsiMarkersApi = createSeriesMarkers(
      candle as any, // eslint-disable-line @typescript-eslint/no-explicit-any
      visibility.showBbRsi ? buildEntrySignalMarkers(data) : []
    ) as ISeriesMarkersPluginApi<Time>;
  }

  // A second, independent markers primitive on the same candle series --
  // distinct from BB+RSI's plain green arrow above, styled per
  // WARREN_MARKER_STYLE's Blue/Yellow/Gray x Up/Down convention.
  let warrenMarkersApi: ISeriesMarkersPluginApi<Time> | null = null;
  if (data.warren_signal_markers.length > 0) {
    warrenMarkersApi = createSeriesMarkers(
      candle as any, // eslint-disable-line @typescript-eslint/no-explicit-any
      visibility.showWarren ? buildWarrenMarkers(data) : []
    ) as ISeriesMarkersPluginApi<Time>;
  }

  return {
    candle,
    zoneLines,
    bbRsiMarkersApi,
    warrenMarkersApi,
    lpSupportSeries,
    lpResistanceSeries,
    bollingerSeries,
    ema21Series: overlaySeries.ema21,
    sma50Series: overlaySeries.sma50,
    sma200Series: overlaySeries.sma200,
  };
}

// Pure marker-array builders, shared between initial chart creation (addMainSeries above) and the toggle-driven
// setMarkers() calls in the component itself (see the showBbRsi/showWarren effects) -- keeps both call sites
// byte-identical instead of two hand-maintained copies of the same mapping.
function buildEntrySignalMarkers(data: ChartOut) {
  return data.entry_signal_markers.map((marker) => ({
    time: marker.time,
    position: "belowBar" as const,
    color: COLORS.marker,
    shape: "arrowUp" as const,
    text: marker.label,
    size: 1,
  }));
}

function buildWarrenMarkers(data: ChartOut) {
  return data.warren_signal_markers.map((marker) => {
    const style = WARREN_MARKER_STYLE[marker.kind] ?? WARREN_MARKER_STYLE.gray_up;
    return {
      time: marker.time,
      position: style.position,
      color: style.color,
      shape: style.shape,
      text: marker.label,
      size: 1,
    };
  });
}

// Generates `count` distinct, strictly-increasing "YYYY-MM-DD" dates after
// `lastTime`, spaced `incrementDays` apart. Used only to extend LP zone
// lines into the empty rightOffset margin -- see extendZoneLinesToEdge's
// own comment for why the actual calendar spacing between these synthetic
// dates doesn't affect how many pixels of the margin they end up
// covering (lightweight-charts spaces bars by ordinal position among
// known distinct time values, not by elapsed calendar time between them),
// so incrementDays is chosen purely so a synthetic date still LOOKS like
// a plausible next trading day/week for this timeframe, not because the
// exact gap size matters for rendering.
function futureDateStrings(lastTime: string, count: number, incrementDays: number): string[] {
  const base = new Date(`${lastTime}T00:00:00Z`);
  const out: string[] = [];
  for (let i = 1; i <= count; i++) {
    const d = new Date(base);
    d.setUTCDate(d.getUTCDate() + incrementDays * i);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

// Extends each LP zone's LineSeries from the last real bar into the
// chart's empty rightOffset margin, so an active zone visually reaches
// the pane's right edge instead of stopping short (which reads as "this
// zone ended," not "still active as of today") -- must run AFTER
// chart.timeScale().fitContent() has already been called using only the
// REAL bars/indicator series (i.e. before these synthetic points exist),
// not before or during. This ordering is load-bearing, not incidental:
// fitContent() always sets the visible right edge to (the LATEST known
// time value across every series on the chart) + rightOffset -- so if
// the synthetic extension existed BEFORE fitContent() ran, the margin
// would just get computed relative to the new, farther-out last point
// and reappear beyond it, chasing the extension forever. Calling
// fitContent() first locks in the true edge (lastBar + rightOffset,
// still a fixed number of bar-slots at this point) from the real data
// alone; only then do these zone lines grow into that already-fixed
// space. lightweight-charts' business-day time mode spaces points by
// ORDINAL position among all distinct known time values, not by real
// elapsed calendar time (this is what lets it render Friday->Monday with
// no weekend gap) -- so exactly `rightOffset` new synthetic points are
// needed for a zone line to reach `rightOffset` bar-slots further right,
// landing its last point exactly on the already-fixed edge; fewer points
// would fall short, and a single point placed far in the future would
// still only consume ONE ordinal slot next to the last real bar,
// regardless of its actual calendar date.
//
// The ordering above is necessary but NOT sufficient on its own --
// makeChartOptions' timeScale.shiftVisibleRangeOnNewBar: false is a
// required companion setting. Without it, this later setData() call
// (adding new time values past the current base index, with the last
// real bar still visible) is exactly the condition lightweight-charts'
// own model uses to detect "a new bar streamed in," and it silently
// SHIFTS the whole visible window right to keep showing rightOffset's
// margin ahead of it, rather than just filling the margin in place --
// re-introducing the same "moving target" problem the fitContent()
// ordering above was meant to solve, just one level deeper, AND cropping
// real history off the left edge in the process. Confirmed numerically
// (not just by re-reading the source): simulating this library's own
// TimeScale math for a 252-bar/900px chart, the zone line's last point
// only reached 96.2% of the way to the true edge with the default left
// on, and landed at exactly 100% with it off -- see this round's commit
// message for the full numbers.
function extendZoneLinesToEdge(
  chart: IChartApi,
  zoneLines: { series: ISeriesApi<"Line">; points: { time: string; value: number }[] }[],
  timeframe: string
) {
  const rightOffset = chart.timeScale().options().rightOffset;
  if (!rightOffset || rightOffset <= 0) return;
  // rightOffset is now a per-range-calibrated value (see
  // computeRightOffset) and can be fractional (e.g. W_4Y's ~8.29) --
  // round UP the synthetic-point count. The compensation branch in
  // updateTimeScale (shiftVisibleRangeOnNewBar: false) keeps the actual
  // locked-in right edge (baseIndex + rightOffset) EXACTLY invariant no
  // matter how many points are added, confirmed numerically: adding
  // floor(rightOffset) points reaches only ~96% of the margin (still
  // short), while ceil(rightOffset) reaches ~108% -- i.e. the last
  // synthetic point lands just past the true edge, simply clipped/
  // invisible there rather than falling short of it. Rounding up is the
  // safe direction; rounding down never is.
  const pointCount = Math.ceil(rightOffset);
  const incrementDays = timeframe === "weekly" ? 7 : 1;
  for (const { series, points } of zoneLines) {
    if (!points.length) continue;
    const last = points[points.length - 1];
    const extension = futureDateStrings(last.time, pointCount, incrementDays).map((time) => ({ time, value: last.value }));
    series.setData([...points, ...extension]);
  }
}

function addRefLine(series: ISeriesApi<"Line">, price: number) {
  // Static reference lines (not derived from data), drawn via
  // createPriceLine rather than a plotted series.
  series.createPriceLine({
    price,
    color: COLORS.refLine,
    lineWidth: 1,
    lineStyle: LineStyle.Solid,
    axisLabelVisible: true,
    title: "",
  });
}

function addRsiSeries(chart: IChartApi, data: ChartOut, paneIndex: number) {
  const series = chart.addSeries(
    LineSeries,
    { color: COLORS.rsi, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
    paneIndex
  );
  // Per-point color: lightweight-charts' LineData accepts an optional
  // `color` per point (falls back to the series' own `color` option when
  // omitted), which recolors the line segment ending at that point -- no
  // need to split this into multiple overlapping series to get
  // value-conditional coloring. Reuses downCandle's existing red rather
  // than introducing a new color for "alert".
  series.setData(
    data.rsi.map((p) => ({
      time: p.time,
      value: p.value,
      color: p.value > RSI_OVERBOUGHT || p.value < RSI_OVERSOLD ? COLORS.downCandle : COLORS.rsi,
    }))
  );
  addRefLine(series, RSI_OVERBOUGHT);
  addRefLine(series, RSI_OVERSOLD);
}

function addStochasticSeries(chart: IChartApi, data: ChartOut, paneIndex: number) {
  const kSeries = chart.addSeries(
    LineSeries,
    { color: COLORS.stochK, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
    paneIndex
  );
  const dSeries = chart.addSeries(
    LineSeries,
    { color: COLORS.stochD, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
    paneIndex
  );
  kSeries.setData(data.stochastic.map((p) => ({ time: p.time, value: p.k })));
  dSeries.setData(data.stochastic.map((p) => ({ time: p.time, value: p.d })));
  addRefLine(kSeries, STOCH_OVERBOUGHT);
  addRefLine(kSeries, STOCH_OVERSOLD);
}

// Chart-tab-only overlay visibility toggles (see ChartTab.tsx) -- purely additive over the existing series/marker
// rendering, never touching crosshair sync or pane geometry.
interface Props extends OverlayVisibility {
  data: ChartOut;
}

export function TickerChart({
  data,
  showBbRsi,
  showWarren,
  showLpSupport,
  showLpResistance,
  showBollinger,
  showEma21,
  showSma50,
  showSma200,
}: Props) {
  // Default OHLC (the latest bar) is a plain derived value, not state --
  // avoids a setState-during-effect render cascade for the common "nothing
  // hovered yet" case. hoverOhlc is real state, set only from the
  // crosshair-move event handler below (a legitimate setState-in-callback,
  // not a synchronous setState-in-effect-body).
  const lastBar = data.bars.length > 0 ? data.bars[data.bars.length - 1] : null;
  const defaultOhlc: OhlcState | null = lastBar ? { o: lastBar.open, h: lastBar.high, l: lastBar.low, c: lastBar.close } : null;
  const [hoverOhlc, setHoverOhlc] = useState<OhlcState | null>(null);
  const ohlc = hoverOhlc ?? defaultOhlc;

  const containerRef = useRef<HTMLDivElement>(null);
  const rsiLabelRef = useRef<HTMLDivElement>(null);
  const stochLabelRef = useRef<HTMLDivElement>(null);
  // Populated by the chart-creation effect below; read by the showBbRsi/showWarren toggle effects further down to
  // flip marker visibility via setMarkers() without recreating the chart.
  const markersApiRef = useRef<{ bbRsi: ISeriesMarkersPluginApi<Time> | null; warren: ISeriesMarkersPluginApi<Time> | null }>({
    bbRsi: null,
    warren: null,
  });
  // Same purpose as markersApiRef, for the plain LineSeries overlays -- toggling one calls applyOptions({ visible })
  // on every series in the relevant list/slot (see the overlay-visibility effects below), never recreating the chart.
  const overlayApiRef = useRef<{
    lpSupport: ISeriesApi<"Line">[];
    lpResistance: ISeriesApi<"Line">[];
    bollinger: ISeriesApi<"Line">[];
    ema21: ISeriesApi<"Line"> | null;
    sma50: ISeriesApi<"Line"> | null;
    sma200: ISeriesApi<"Line"> | null;
  }>({ lpSupport: [], lpResistance: [], bollinger: [], ema21: null, sma50: null, sma200: null });

  // Pane layout: main is always pane 0; RSI/Stochastic each get the next
  // free pane index only when they have data -- a thin-history ticker
  // missing one or both indicators (still too little warm-up) must not
  // leave an empty gap pane, exactly like the old conditionally-rendered
  // divs. Computed here, once per data change, so both the chart-creation
  // effect below and the overlay-label JSX stay in sync by construction
  // instead of by two hand-maintained copies of "does RSI exist."
  const hasRsi = data.rsi.length > 0;
  const hasStochastic = data.stochastic.length > 0;
  let nextPaneIndex = 1;
  const rsiPaneIndex = hasRsi ? nextPaneIndex++ : null;
  const stochPaneIndex = hasStochastic ? nextPaneIndex++ : null;

  const totalHeight =
    MAIN_PANE_HEIGHT +
    (hasRsi ? PANE_SEPARATOR_HEIGHT + RSI_PANE_HEIGHT : 0) +
    (hasStochastic ? PANE_SEPARATOR_HEIGHT + STOCH_PANE_HEIGHT : 0);
  // Pre-layout placeholder only, from the *nominal* pane-height constants -- never
  // actually visible, since the layout effect below overwrites both labels' real
  // `top` from the chart's own post-layout paneSize() before the browser paints.
  // Needed here only because these constants don't equal the chart's real rendered
  // pane heights (the chart's `height` option must also budget for the shared time
  // axis row, which these nominal sums never accounted for -- confirmed via
  // lightweight-charts.development.mjs's _private__adjustSizeImpl, which subtracts
  // timeAxisHeight from the given `height` before splitting panes), so using them
  // as a final value silently landed both labels a few px into the wrong pane.
  const rsiLabelTop = MAIN_PANE_HEIGHT + PANE_SEPARATOR_HEIGHT;
  const stochLabelTop = MAIN_PANE_HEIGHT + PANE_SEPARATOR_HEIGHT + (hasRsi ? RSI_PANE_HEIGHT + PANE_SEPARATOR_HEIGHT : 0);

  useLayoutEffect(() => {
    if (!containerRef.current) return;

    // Computed once per data change, from the currently-rendered range's
    // own real bar count -- see computeRightOffset's own comment for why
    // this alone (no live pixel/barSpacing reading) is sufficient. Passed
    // once to the one shared chart now, rather than identically to three
    // separate instances.
    const rightOffset = computeRightOffset(data.bars.length);

    const chart = createChart(containerRef.current, makeChartOptions(rightOffset, totalHeight));

    const {
      candle,
      zoneLines,
      bbRsiMarkersApi,
      warrenMarkersApi,
      lpSupportSeries,
      lpResistanceSeries,
      bollingerSeries,
      ema21Series,
      sma50Series,
      sma200Series,
    } = addMainSeries(chart, data, {
      showBbRsi,
      showWarren,
      showLpSupport,
      showLpResistance,
      showBollinger,
      showEma21,
      showSma50,
      showSma200,
    });
    markersApiRef.current = { bbRsi: bbRsiMarkersApi, warren: warrenMarkersApi };
    overlayApiRef.current = {
      lpSupport: lpSupportSeries,
      lpResistance: lpResistanceSeries,
      bollinger: bollingerSeries,
      ema21: ema21Series,
      sma50: sma50Series,
      sma200: sma200Series,
    };
    if (rsiPaneIndex !== null) addRsiSeries(chart, data, rsiPaneIndex);
    if (stochPaneIndex !== null) addStochasticSeries(chart, data, stochPaneIndex);

    // addSeries(..., paneIndex) above already created each pane on demand
    // -- setStretchFactor() here locks in the fixed pixel split (630/120/
    // 120), used as pure ratios since the chart's own `height` option
    // already fixes the total. Deliberately NOT setHeight(): confirmed via
    // lightweight-charts.development.mjs that setHeight() (ChartModel.
    // _internal_changePanesHeight) is a RELATIVE delta-redistribution --
    // each call nudges every OTHER pane's current height too, so three
    // sequential setHeight() calls compound (only the LAST pane called
    // lands exactly on target; earlier ones drift). setStretchFactor() is
    // a direct, independent assignment with no cross-pane side effects,
    // so all three panes land on their intended ratio regardless of call
    // order -- RSI and Stochastic (equal stretch factors) are guaranteed
    // pixel-identical to each other, not just approximately close.
    chart.panes()[0].setStretchFactor(MAIN_PANE_HEIGHT);
    if (rsiPaneIndex !== null) chart.panes()[rsiPaneIndex].setStretchFactor(RSI_PANE_HEIGHT);
    if (stochPaneIndex !== null) chart.panes()[stochPaneIndex].setStretchFactor(STOCH_PANE_HEIGHT);

    chart.timeScale().fitContent();
    extendZoneLinesToEdge(chart, zoneLines, data.timeframe);

    // Bounded right-edge pan/zoom -- see fixLeftEdge/fixRightEdge's own
    // comment on the timeScale options above for why this exists instead
    // of just setting fixRightEdge:true. The bound is read directly off
    // the chart's OWN visible range right after fitContent()+
    // extendZoneLinesToEdge() above (rather than recomputing
    // computeRightOffset(data.bars.length) independently), so it's
    // guaranteed to exactly match whatever margin is actually on screen
    // at that moment -- including the zone-line extension's own
    // Math.ceil() rounding -- with no risk of the two drifting apart.
    // A pan/zoom that would push the right edge past this bound is
    // translated (from and to shifted by the same amount), preserving
    // the current zoom level, matching fixLeftEdge's own left-edge
    // behavior; the subsequent left-edge check only fires if that
    // translation would then push `from` past the first bar (i.e. the
    // visible span itself is wider than all fetched data plus the
    // margin), in which case the span is shrunk instead -- this is the
    // one case fixLeftEdge can't correct on its own, since it only reacts
    // to genuine user pan/zoom input, not to a range this handler itself
    // just set via setVisibleLogicalRange (which bypasses fixLeftEdge's
    // own correction pass).
    const initialVisibleRange = chart.timeScale().getVisibleLogicalRange();
    let handleVisibleRangeChange: LogicalRangeChangeEventHandler | null = null;
    if (initialVisibleRange) {
      const maxTo = initialVisibleRange.to;
      const minFrom = initialVisibleRange.from;
      handleVisibleRangeChange = (range) => {
        if (!range) return;
        let from: number = range.from;
        let to: number = range.to;
        let needsCorrection = false;
        if (to > maxTo) {
          from -= to - maxTo;
          to = maxTo;
          needsCorrection = true;
        }
        if (from < minFrom) {
          from = minFrom;
          needsCorrection = true;
        }
        if (needsCorrection) {
          chart.timeScale().setVisibleLogicalRange({ from: from as Logical, to: to as Logical });
        }
      };
      chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
    }

    // Position the RSI/Stochastic overlay labels from the chart's own real,
    // post-layout pane geometry (IChartApi.paneSize(), "the plot surface which
    // excludes time and price scales") rather than the nominal height constants --
    // see rsiLabelTop/stochLabelTop's own comment above for why those constants
    // don't match the real rendered pane heights.
    //
    // Deferred one animation frame, NOT read synchronously here -- confirmed via
    // lightweight-charts.development.mjs that paneSize() reads a WIDGET-layer array
    // (ChartWidget._private__paneWidgets) that's only kept in sync with the model
    // by _private__syncGuiWithModel(), itself only invoked from the library's own
    // requestAnimationFrame-scheduled draw (_private__invalidateHandler). A newly
    // created pane (RSI/Stochastic, via addSeries(..., paneIndex) above) has no
    // widget yet at this point in the SAME synchronous tick -- confirmed by a real
    // crash report ("Value is undefined" from paneSize()'s own ensureDefined) --
    // pane 0 alone never crashed since it already exists from chart construction.
    // requestAnimationFrame callbacks run in registration order within a frame, and
    // the library's own sync-triggering RAF was registered earlier in this same
    // tick (as a side effect of addSeries/setStretchFactor above), so scheduling
    // ours here guarantees it runs after pane widgets actually exist. This
    // reintroduces a one-frame flash of the placeholder position -- the very thing
    // useLayoutEffect was meant to avoid -- but that's a necessary trade-off: the
    // library's own pane-widget creation is itself RAF-deferred, so there's no way
    // to read real pane geometry any earlier than this. PaneApi.getHeight() (reads
    // the model directly, so it wouldn't throw) was considered and rejected: its
    // value is written by the same RAF-deferred layout pass, so it would silently
    // return a STALE height instead of crashing -- worse, not better.
    let labelPositioningCancelled = false;
    const positionLabelsFromRealPaneGeometry = () => {
      if (labelPositioningCancelled) return;
      const mainPaneHeight = chart.paneSize(0).height;
      if (rsiLabelRef.current && rsiPaneIndex !== null) {
        rsiLabelRef.current.style.top = `${mainPaneHeight + PANE_SEPARATOR_HEIGHT}px`;
      }
      if (stochLabelRef.current && stochPaneIndex !== null) {
        const rsiPaneHeight = rsiPaneIndex !== null ? chart.paneSize(rsiPaneIndex).height : 0;
        const stochTop = mainPaneHeight + PANE_SEPARATOR_HEIGHT + (rsiPaneIndex !== null ? rsiPaneHeight + PANE_SEPARATOR_HEIGHT : 0);
        stochLabelRef.current.style.top = `${stochTop}px`;
      }
    };
    const positionLabelsRafId = requestAnimationFrame(positionLabelsFromRealPaneGeometry);

    // One shared time scale for the whole pane stack means one crosshair
    // callback already covers every pane's data for the same instant --
    // no manual setCrosshairPosition relay between separate chart
    // instances needed any more (previously ~60 lines cross-wiring up to
    // three independent charts).
    chart.subscribeCrosshairMove((params) => {
      if (params.time !== undefined) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const bar = params.seriesData.get(candle as any) as any;
        if (bar && bar.open !== undefined) {
          setHoverOhlc({ o: bar.open, h: bar.high, l: bar.low, c: bar.close });
        }
      } else {
        setHoverOhlc(null); // falls back to defaultOhlc (the latest bar) above
      }
    });

    // rightOffset (computed once above, before any of this) never needs
    // recomputing here on resize: the margin-equalization math is a pure
    // ratio of bar counts (computeRightOffset), and pane width cancels
    // out of that ratio algebraically -- confirmed numerically across a
    // wide range of widths (600-2000px) -- so the same value stays
    // correct at whatever width the container resizes to.
    const observer = new ResizeObserver(() => {
      const w = containerRef.current?.clientWidth;
      if (w) chart.applyOptions({ width: w });
    });
    if (containerRef.current) observer.observe(containerRef.current);

    return () => {
      labelPositioningCancelled = true;
      cancelAnimationFrame(positionLabelsRafId);
      observer.disconnect();
      if (handleVisibleRangeChange) chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      chart.remove();
      markersApiRef.current = { bbRsi: null, warren: null };
      overlayApiRef.current = { lpSupport: [], lpResistance: [], bollinger: [], ema21: null, sma50: null, sma200: null };
    };
    // Every showXxx toggle is intentionally excluded here: they only set the INITIAL visibility at chart creation
    // (read once, via closure); a later toggle flip is handled by the separate effects below via
    // setMarkers()/applyOptions({ visible }), without tearing down and recreating the whole chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, totalHeight, rsiPaneIndex, stochPaneIndex]);

  // Syncs marker/series visibility on a toggle flip alone -- deliberately not combined with the chart-creation
  // effect above, which would otherwise tear down and recreate the whole chart (losing crosshair state, pane
  // layout, etc.) on every toggle click. Each of these also runs once on initial mount (React runs every effect
  // after the first render), which just re-applies the same visibility addMainSeries already set -- a harmless
  // no-op.
  useEffect(() => {
    markersApiRef.current.bbRsi?.setMarkers(showBbRsi ? buildEntrySignalMarkers(data) : []);
  }, [data, showBbRsi]);

  useEffect(() => {
    markersApiRef.current.warren?.setMarkers(showWarren ? buildWarrenMarkers(data) : []);
  }, [data, showWarren]);

  useEffect(() => {
    for (const s of overlayApiRef.current.lpSupport) s.applyOptions({ visible: showLpSupport });
  }, [showLpSupport]);

  useEffect(() => {
    for (const s of overlayApiRef.current.lpResistance) s.applyOptions({ visible: showLpResistance });
  }, [showLpResistance]);

  useEffect(() => {
    for (const s of overlayApiRef.current.bollinger) s.applyOptions({ visible: showBollinger });
  }, [showBollinger]);

  useEffect(() => {
    overlayApiRef.current.ema21?.applyOptions({ visible: showEma21 });
  }, [showEma21]);

  useEffect(() => {
    overlayApiRef.current.sma50?.applyOptions({ visible: showSma50 });
  }, [showSma50]);

  useEffect(() => {
    overlayApiRef.current.sma200?.applyOptions({ visible: showSma200 });
  }, [showSma200]);

  return (
    <div className="rounded-lg border border-border-card">
      <div className="relative bg-zinc-950">
        <div className="absolute top-2 left-3 z-10 select-none pointer-events-none">
          {ohlc && (
            <div className="flex items-center gap-2.5 text-xs font-mono">
              <span className="text-zinc-500">
                O <span className="text-zinc-300">{fmtMoney(ohlc.o)}</span>
              </span>
              <span className="text-zinc-500">
                H <span className="text-emerald-400">{fmtMoney(ohlc.h)}</span>
              </span>
              <span className="text-zinc-500">
                L <span className="text-red-400">{fmtMoney(ohlc.l)}</span>
              </span>
              <span className="text-zinc-500">
                C <span className="text-zinc-200">{fmtMoney(ohlc.c)}</span>
              </span>
            </div>
          )}
        </div>

        {hasRsi && (
          <div
            ref={rsiLabelRef}
            className="absolute left-3 z-10 text-[10px] font-mono text-zinc-600 select-none pointer-events-none"
            style={{ top: rsiLabelTop }} // placeholder; corrected from real pane geometry in the layout effect above
          >
            RSI (14)
          </div>
        )}

        {hasStochastic && (
          <div
            ref={stochLabelRef}
            className="absolute left-3 z-10 text-[10px] font-mono text-zinc-600 select-none pointer-events-none"
            style={{ top: stochLabelTop }} // placeholder; corrected from real pane geometry in the layout effect above
          >
            Full Stochastic (5, 3, 3)
          </div>
        )}

        <div ref={containerRef} className="w-full" style={{ height: totalHeight }} />
      </div>
    </div>
  );
}
