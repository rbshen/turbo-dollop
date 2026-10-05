"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, LineSeries, createSeriesMarkers, LineStyle } from "lightweight-charts";
import type { BarPrice, IChartApi, IPriceLine, ISeriesApi, ISeriesMarkersPluginApi, Logical, LogicalRangeChangeEventHandler, SeriesType, Time } from "lightweight-charts";
import { fmtMoney } from "@/lib/format";
import { buildDividendLabels, buildEarningsLabels, describeEventMarker, eventTooltipPlacement } from "@/lib/chartEventMarkers";
import type { TooltipPlacement } from "@/lib/chartEventMarkers";
import { EventLabelsPrimitive } from "./EventLabelsPrimitive";
import { PaneMidLabelPrimitive } from "./PaneMidLabelPrimitive";
import { TooltipCard } from "@/components/ui/tooltip";
import type { ChartOut } from "@/lib/api/types";
import { buildStageColoredBars, WEINSTEIN_MA_COLOR } from "@/lib/chartWeinstein";
import { readChartColors } from "@/lib/chartTokens";
import { etIsoToFakeUtc, fakeUtcToEtIso, formatCandleLegendTime } from "@/lib/chartTime";
import {
  axisLayout,
  DEFAULT_AXIS_OPTIONS,
  formatAxisPrice,
  overlapClearancePx,
  readMonoFontFamily,
  tickLabelsHidingOverlap,
  tickMarkDensity,
} from "@/lib/chartAxis";
import type { AxisOptions } from "@/lib/chartAxis";
import {
  drawnRsiLevels,
  extendAutoscale,
  MAIN_PANE_HEIGHT,
  nominalLabelTops,
  PANE_SEPARATOR_HEIGHT,
  subPaneSpecs,
  SUB_PANE_SCALE_MARGINS_2H,
  totalChartHeight,
} from "@/lib/chartPanes";
import type { PaneSpec } from "@/lib/chartPanes";
import { zoneExtensionPoints, zoneLinePoints } from "@/lib/chartZoneLines";
import type { ZonePoint } from "@/lib/chartZoneLines";
import {
  barSpacingForZoomLevel,
  clampToPanBounds,
  computePanBounds,
  computeRightOffset,
  computeZoomLevelMultipliers,
  MAX_BAR_SPACING_CAP,
} from "@/lib/chartZoom";
import type { ChartColors } from "@/lib/chartTokens";

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
// Chart canvas background/axis-text/axis-border chrome -- resolved once per chart creation from the design
// system's page/text-secondary/border-card tokens (see the mount effect below), same as every data-series color.

// Every data-series/marker color below is resolved at chart-creation time from the design system's named
// --fathom-chart-*/--fathom-stage-* tokens (see lib/chartTokens.ts::readChartColors) -- this file no longer holds
// any of its own raw hex for them. See that module's own comment for the token->fallback mapping, and this
// session's report for the full before/after table.

// One entry per Warren signal_kind (see ChartMarkerOut.kind) -- color by Blue/Yellow/Gray, shape/position by Up
// (buy, below the bar) vs. Down (sell, above the bar). A function (not a module-level constant) since it depends
// on the resolved ChartColors, which are only known once the chart-creation effect has run.
function warrenMarkerStyle(
  colors: ChartColors
): Record<string, { color: string; shape: "arrowUp" | "arrowDown"; position: "belowBar" | "aboveBar" }> {
  return {
    blue_up: { color: colors.chartEma21, shape: "arrowUp", position: "belowBar" }, // same blue already used for ema21
    yellow_up: { color: colors.chartWarrenYellow, shape: "arrowUp", position: "belowBar" },
    gray_up: { color: colors.chartWarrenGray, shape: "arrowUp", position: "belowBar" },
    blue_down: { color: colors.chartEma21, shape: "arrowDown", position: "aboveBar" },
    yellow_down: { color: colors.chartWarrenYellow, shape: "arrowDown", position: "aboveBar" },
    gray_down: { color: colors.chartWarrenGray, shape: "arrowDown", position: "aboveBar" },
  };
}

const RSI_OVERBOUGHT = 70;
const RSI_OVERSOLD = 30;
const STOCH_OVERBOUGHT = 80;
const STOCH_OVERSOLD = 20;

// Pane heights (MAIN_PANE_HEIGHT, the per-pane sub-pane height, PANE_SEPARATOR_HEIGHT -- lightweight-charts' fixed 1px
// pane separator, which the library draws natively between panes sharing one chart) and the per-range sub-pane list
// live in lib/chartPanes.ts; they are applied below via setStretchFactor().

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

// Main (price) pane's own scaleMargins, applied explicitly -- left unset, every
// pane's price scale falls back to the library default `{ top: 0.2, bottom: 0.1 }`
// (confirmed in this library's own typings), reserving 30% of the pane's height as
// blank space above/below the candles regardless of the pane's own fixed pixel
// height. Deliberately scoped to the main pane only, via chart.priceScale('right',
// 0) below -- the RSI/Stochastic panes keep the library default unchanged, since
// their own 0-100-ish value range and OB/OS reference lines already sit close to
// each pane's top/bottom edge and were left untouched per explicit request.
const PRICE_PANE_SCALE_MARGINS = { top: 0.08, bottom: 0.08 };


interface OhlcState {
  o: number;
  h: number;
  l: number;
  c: number;
}

function makeChartOptions(rightOffset: number, height: number, colors: ChartColors, intraday: boolean, axisOptions: AxisOptions) {
  const axis = axisLayout(axisOptions, colors.textSecondary, readMonoFontFamily());
  return {
    layout: {
      background: { color: colors.page },
      // Axis (price-scale/time-scale) label color, size (bumped from 11 to 12 for readability) and font, chart-wide.
      // Exactly the original values unless an Axis option is on (lib/chartAxis.ts::axisLayout).
      textColor: axis.textColor,
      fontSize: axis.fontSize,
      fontFamily: axis.fontFamily,
      attributionLogo: false,
      // Static, non-resizable stacked panes -- matches the old fixed-height
      // three-separate-divs look (no user-facing pane resize handle).
      panes: { enableResize: false, separatorColor: colors.borderCard, separatorHoverColor: colors.borderCard },
    },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    // Click-drag panning stays on (handleScroll); free-form zoom (wheel, pinch,
    // drag-on-axis-to-scale) is off -- zoom is now exclusively the discrete
    // Zoom in/out buttons in ChartTab.tsx, stepping through computeZoomLevelMultipliers's ladder.
    // Same handleScale:false convention already used in the sibling options_tracker
    // project's PositionChart.tsx.
    handleScroll: true,
    handleScale: false,
    rightPriceScale: { borderColor: colors.borderCard, minimumWidth: PRICE_SCALE_MIN_WIDTH },
    // shiftVisibleRangeOnNewBar defaults to true (a "streaming chart"
    // convenience: auto-scroll to keep showing rightOffset's margin ahead
    // of a genuinely new incoming bar). This chart never streams -- every
    // range switch tears down and recreates the whole chart from data
    // fetched once -- but it DOES call series.setData() a second time
    // after the initial view is set, to extend LP zone lines into the
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
      borderColor: colors.borderCard,
      // The 2H·90D range's UTCTimestamp times (fake-UTC ET wall-clock, see lib/chartTime.ts) show HH:MM on the axis
      // and crosshair; the daily/weekly business-day strings stay date-only.
      timeVisible: intraday,
      rightOffset,
      shiftVisibleRangeOnNewBar: false,
      fixLeftEdge: true,
      // Defensive floor/ceiling only now that zoom is exclusively button-driven
      // (see computeZoomLevelMultipliers/MAX_BAR_SPACING_CAP above) -- the discrete
      // ladder never asks for a barSpacing outside this range by construction, but
      // these stay as a backstop against the library's own default-barSpacing
      // state (6) ever being visible for a frame before the ladder is applied.
      minBarSpacing: 1,
      maxBarSpacing: MAX_BAR_SPACING_CAP,
    },
    crosshair: { mode: 1 },
    height,
  };
}

interface OverlayVisibility {
  showBbRsi: boolean;
  showWarren: boolean;
  showEarnings: boolean;
  showDividends: boolean;
  showLpSupport: boolean;
  showLpResistance: boolean;
  showBollinger: boolean;
  showEma21: boolean;
  showSma50: boolean;
  showSma200: boolean;
  /** W/4Y only -- the Weinstein "Stage" toggle: white MA line + stage-colored candles. */
  showStage?: boolean;
}

// 2H·90D times arrive as naive-ET ISO strings and become fake-UTC UTCTimestamps (lib/chartTime.ts); every other range
// keeps its "YYYY-MM-DD" strings untouched (the identity mapping, same array instances).
function isIntraday(data: Pick<ChartOut, "timeframe">): boolean {
  return data.timeframe === "2h";
}

function timeMapper(data: Pick<ChartOut, "timeframe">): (t: string) => Time {
  return isIntraday(data) ? etIsoToFakeUtc : (t) => t as Time;
}

function retime<P extends { time: string }>(points: P[], data: Pick<ChartOut, "timeframe">): P[] {
  if (!isIntraday(data)) return points;
  return points.map((p) => ({ ...p, time: etIsoToFakeUtc(p.time) })) as unknown as P[];
}

// One LP zone's line: its series, the points it was fed (they start at the swing candle) and its level.
interface ZoneLine {
  series: ISeriesApi<"Line">;
  points: ZonePoint[];
  price: number;
}

function addMainSeries(chart: IChartApi, data: ChartOut, visibility: OverlayVisibility, colors: ChartColors) {
  // No paneIndex passed -- defaults to pane 0, the main price pane.
  const candle = chart.addSeries(CandlestickSeries, {
    upColor: colors.chartUp,
    downColor: colors.chartDown,
    wickUpColor: colors.chartUp,
    wickDownColor: colors.chartDown,
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
  candle.setData(retime(data.bars, data));

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
    ["ema21", colors.chartEma21],
    ["sma50", colors.chartSma50],
    ["sma200", colors.chartSma200],
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
    line.setData(retime(pts, data));
    overlaySeries[key] = line;
  }

  // Weinstein MA (W/4Y only, data-driven: the daily ranges carry an empty weinstein_ma). Always created when there is
  // data and shown/hidden via applyOptions like the other overlays; the title puts the live-config label ("EMA30")
  // on the price axis.
  let stageMaSeries: ISeriesApi<"Line"> | null = null;
  if (data.weinstein_ma?.length) {
    stageMaSeries = chart.addSeries(LineSeries, {
      color: WEINSTEIN_MA_COLOR,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
      title: data.weinstein_ma_label ?? "",
      crosshairMarkerVisible: false,
      visible: !!visibility.showStage,
    });
    stageMaSeries.setData(retime(data.weinstein_ma, data));
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
        color: colors.chartBand,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        visible: visibility.showBollinger,
      });
      bb.setData(retime(data.bollinger, data).map((b) => ({ time: b.time, value: b[key] })));
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
  const zoneLines: ZoneLine[] = [];
  const lpSupportSeries: ISeriesApi<"Line">[] = [];
  const lpResistanceSeries: ISeriesApi<"Line">[] = [];
  for (const zone of data.zones) {
    const isSupport = zone.side === "support";
    // Numeric (fake-UTC) comparison on the 2H·90D range, string comparison on daily/weekly -- see
    // lib/chartZoneLines.ts. The zone starts at its swing candle either way.
    const toTime = timeMapper(data);
    const points = zoneLinePoints(data.bars.map((b) => ({ time: toTime(b.time) as string | number })), toTime(zone.formed_at) as string | number, zone.price);
    if (!points.length) continue;
    const color = zone.broken
      ? isSupport
        ? colors.chartZoneBrokenSupport
        : colors.chartZoneBrokenResistance
      : isSupport
        ? colors.chartUp
        : colors.chartDown;
    const zoneLine = chart.addSeries(LineSeries, {
      color,
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
      visible: isSupport ? visibility.showLpSupport : visibility.showLpResistance,
    });
    zoneLine.setData(points as { time: Time; value: number }[]);
    zoneLines.push({ series: zoneLine, points, price: zone.price });
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
      visibility.showBbRsi ? buildEntrySignalMarkers(data, colors.chartUp) : []
    ) as ISeriesMarkersPluginApi<Time>;
  }

  // A second, independent markers primitive on the same candle series --
  // distinct from BB+RSI's plain green arrow above, styled per
  // WARREN_MARKER_STYLE's Blue/Yellow/Gray x Up/Down convention.
  let warrenMarkersApi: ISeriesMarkersPluginApi<Time> | null = null;
  if (data.warren_signal_markers.length > 0) {
    warrenMarkersApi = createSeriesMarkers(
      candle as any, // eslint-disable-line @typescript-eslint/no-explicit-any
      visibility.showWarren ? buildWarrenMarkers(data, colors) : []
    ) as ISeriesMarkersPluginApi<Time>;
  }

  // Earnings/dividend letters on a fixed row along the price pane's floor, independent of price (TradingView's
  // convention). Custom primitives on the candle series rather than series markers, which can't do this in
  // lightweight-charts 5.2.0 (see lib/chartEventMarkers.ts's header). One primitive per kind so each keeps its
  // own toggle; same "create whenever there's data, gate only the initial labels on the toggle" convention as
  // the signal markers above. Both draw at the pane's floor, so the candle scale's own margins are untouched.
  let earningsLabelsApi: EventLabelsPrimitive | null = null;
  if (data.earnings_markers.length > 0) {
    earningsLabelsApi = new EventLabelsPrimitive();
    candle.attachPrimitive(earningsLabelsApi);
    earningsLabelsApi.setLabels(visibility.showEarnings ? buildEarningsLabels(data.earnings_markers, colors.chartEventEarnings) : []);
  }
  let dividendLabelsApi: EventLabelsPrimitive | null = null;
  if (data.dividend_markers.length > 0) {
    dividendLabelsApi = new EventLabelsPrimitive();
    candle.attachPrimitive(dividendLabelsApi);
    dividendLabelsApi.setLabels(
      visibility.showDividends ? buildDividendLabels(data.dividend_markers, colors.chartEventDividend, data.earnings_markers) : []
    );
  }

  return {
    candle,
    zoneLines,
    bbRsiMarkersApi,
    warrenMarkersApi,
    earningsLabelsApi,
    dividendLabelsApi,
    lpSupportSeries,
    lpResistanceSeries,
    bollingerSeries,
    ema21Series: overlaySeries.ema21,
    sma50Series: overlaySeries.sma50,
    sma200Series: overlaySeries.sma200,
    stageMaSeries,
  };
}

// Pure marker-array builders, shared between initial chart creation (addMainSeries above) and the toggle-driven
// setMarkers() calls in the component itself (see the showBbRsi/showWarren effects) -- keeps both call sites
// byte-identical instead of two hand-maintained copies of the same mapping.
function buildEntrySignalMarkers(data: ChartOut, color: string) {
  const toTime = timeMapper(data);
  return data.entry_signal_markers.map((marker) => ({
    time: toTime(marker.time),
    position: "belowBar" as const,
    color,
    shape: "arrowUp" as const,
    text: marker.label,
    size: 1,
  }));
}

function buildWarrenMarkers(data: ChartOut, colors: ChartColors) {
  const styles = warrenMarkerStyle(colors);
  const toTime = timeMapper(data);
  return data.warren_signal_markers.map((marker) => {
    const style = styles[marker.kind] ?? styles.gray_up;
    return {
      time: toTime(marker.time),
      position: style.position,
      color: style.color,
      shape: style.shape,
      text: marker.label,
      size: 1,
    };
  });
}

// Extends each LP zone's LineSeries from the last real bar into the
// chart's empty rightOffset margin, so an active zone visually reaches
// the pane's right edge instead of stopping short (which reads as "this
// zone ended," not "still active as of today") -- must run AFTER the
// chart's initial view has already been set (via setVisibleLogicalRange in the
// mount effect, using the REAL bars/indicator series, i.e. before these synthetic
// points exist), not before or during. `rightOffset` is passed in as the same
// value the caller already computed from data.bars.length (computeRightOffset) --
// deliberately NOT read back from chart.timeScale().options() here, so this
// function has no dependency on the chart's own (RAF-deferred) state either.
// This ordering is load-bearing, not incidental: setting the visible range
// locks in the true edge (lastBar + rightOffset, a fixed number of bar-slots)
// from the real data alone; only then do these zone lines grow into that
// already-fixed space -- if the synthetic extension existed first, the edge
// would be computed relative to the new, farther-out last point and the
// extension would chase it forever. lightweight-charts' business-day time mode
// spaces points by ORDINAL position among all distinct known time values, not by
// real elapsed calendar time (this is what lets it render Friday->Monday with
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
// re-introducing the same "moving target" problem the ordering above was
// meant to solve, just one level deeper, AND cropping real history off the
// left edge in the process. Confirmed numerically (not just by re-reading
// the source): simulating this library's own TimeScale math for a
// 252-bar/900px chart, the zone line's last point only reached 96.2% of the
// way to the true edge with the default left on, and landed at exactly 100%
// with it off -- see this round's commit message for the full numbers.
function extendZoneLinesToEdge(
  zoneLines: ZoneLine[],
  timeframe: string,
  rightOffset: number
) {
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
  // The synthetic margin points (lib/chartZoneLines.ts::zoneExtensionPoints): `ceil(rightOffset)` of them, as future
  // date strings on the daily/weekly ranges (unchanged) and as numeric timestamps 2h apart on the 2H·90D range.
  for (const { series, points } of zoneLines) {
    const extension = zoneExtensionPoints(points, rightOffset, timeframe);
    if (!extension.length) continue;
    series.setData([...points, ...extension] as { time: Time; value: number }[]);
  }
}

function addRefLine(series: ISeriesApi<"Line">, price: number, color: string, opts: { dashed?: boolean; axisLabel?: boolean } = {}): IPriceLine {
  // Static reference lines (not derived from data), drawn via
  // createPriceLine rather than a plotted series.
  return series.createPriceLine({
    price,
    color,
    lineWidth: 1,
    lineStyle: opts.dashed ? LineStyle.Dashed : LineStyle.Solid,
    axisLabelVisible: opts.axisLabel ?? true,
    title: "",
  });
}

function addRsiSeries(chart: IChartApi, data: ChartOut, paneIndex: number, colors: ChartColors) {
  const series = chart.addSeries(
    LineSeries,
    { color: colors.chartBand, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
    paneIndex
  );
  // Per-point color: lightweight-charts' LineData accepts an optional
  // `color` per point (falls back to the series' own `color` option when
  // omitted), which recolors the line segment ending at that point -- no
  // need to split this into multiple overlapping series to get
  // value-conditional coloring. Reuses chart-down's existing red rather
  // than introducing a new color for "alert".
  series.setData(
    data.rsi.map((p) => ({
      time: p.time,
      value: p.value,
      color: p.value > RSI_OVERBOUGHT || p.value < RSI_OVERSOLD ? colors.chartDown : colors.chartBand,
    }))
  );
  addRefLine(series, RSI_OVERBOUGHT, colors.chartRefline);
  addRefLine(series, RSI_OVERSOLD, colors.chartRefline);
}

function addStochasticSeries(chart: IChartApi, data: ChartOut, paneIndex: number, colors: ChartColors) {
  const kSeries = chart.addSeries(
    LineSeries,
    { color: colors.chartStochK, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
    paneIndex
  );
  const dSeries = chart.addSeries(
    LineSeries,
    { color: colors.chartBand, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
    paneIndex
  );
  kSeries.setData(data.stochastic.map((p) => ({ time: p.time, value: p.k })));
  dSeries.setData(data.stochastic.map((p) => ({ time: p.time, value: p.d })));
  addRefLine(kSeries, STOCH_OVERBOUGHT, colors.chartRefline);
  addRefLine(kSeries, STOCH_OVERSOLD, colors.chartRefline);
}

// --- 2H·90D sub-panes: the Warren engine's own series (ChartOut.warren_*), never the daily rsi/stochastic fields ---
//
// Colors reuse the existing chart tokens (no new ones): RSI keeps the daily RSI pane's grey line with red beyond
// 30/70; ADX is the blue (chart-ema21) line alone (+DI/-DI are not plotted); WVF the Warren amber
// (chart-warren-yellow). Reference lines are chart-refline, all dashed: the Warren-specific thresholds (RSI
// 12/80.81/84.75, ADX 40, WVF 0.40); the classic RSI 30/70 lines are not drawn. Price-axis labels are drawn only where
// they cannot collide (RSI 12, ADX 40, WVF 0.40) -- 80.81 and 84.75 sit about 3px apart on a 100px pane -- and the
// pane's own label lists every drawn level instead. Each series' autoscale is widened to include its levels, so a line
// is always inside the scale, and the pane keeps SUB_PANE_SCALE_MARGINS_2H of headroom at the top for its label.

function addWarrenSubPane(chart: IChartApi, spec: PaneSpec, data: ChartOut, paneIndex: number, colors: ChartColors): AxisPane | null {
  const levels = data.warren_levels;
  const lineOpts = { lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false };
  const withLevels = (values: number[], clamp?: { min?: number; max?: number }) => ({
    autoscaleInfoProvider: (original: () => ReturnType<typeof extendAutoscale>) => extendAutoscale(original(), values, clamp),
  });
  let owner: ISeriesApi<SeriesType> | null = null;
  let tagPrices: number[] = [];
  // Every dotted reference line with the axis tag it is drawn with, so "Clean sub-pane axes" can remove and restore the tags.
  const refLines: RefLineTag[] = [];
  const addLevel = (series: ISeriesApi<"Line">, level: number, axisLabel: boolean) =>
    refLines.push({ line: addRefLine(series, level, colors.chartRefline, { dashed: true, axisLabel }), axisLabel });

  if (spec.id === "warren-rsi") {
    // The classic 30/70 lines are not drawn (drawnRsiLevels). The line is one color: no red beyond 30/70 on this range
    // (the daily RSI pane keeps its red).
    const rsiLevels = drawnRsiLevels(levels?.rsi ?? []);
    const series = chart.addSeries(LineSeries, { color: colors.chartBand, ...lineOpts, ...withLevels(rsiLevels, { min: 0, max: 100 }) }, paneIndex);
    series.setData(retime(data.warren_rsi, data) as { time: Time; value: number }[]);
    for (const level of rsiLevels) addLevel(series, level, level === 12);
    owner = series;
    tagPrices = rsiLevels.filter((level) => level === 12);
  } else if (spec.id === "warren-adx") {
    // The ADX line only: +DI/-DI are not plotted.
    const adxLevels = levels?.adx ?? [];
    const adx = chart.addSeries(LineSeries, { color: colors.chartEma21, ...lineOpts, ...withLevels(adxLevels) }, paneIndex);
    adx.setData(retime(data.warren_adx, data) as { time: Time; value: number }[]);
    for (const level of adxLevels) addLevel(adx, level, true);
    owner = adx;
    tagPrices = adxLevels;
  } else if (spec.id === "warren-wvf") {
    const wvfLevels = levels?.wvf ?? [];
    const series = chart.addSeries(LineSeries, { color: colors.chartWarrenYellow, ...lineOpts, ...withLevels(wvfLevels) }, paneIndex);
    series.setData(retime(data.warren_wvf, data) as { time: Time; value: number }[]);
    for (const level of wvfLevels) addLevel(series, level, true);
    owner = series;
    tagPrices = wvfLevels;
  }
  // After the pane's series exist: addSeries(..., paneIndex) is what creates the pane, and the library rejects
  // price-scale options for a pane that does not exist yet. The margins reserve top headroom for the pane label.
  chart.priceScale("right", paneIndex).applyOptions({ scaleMargins: SUB_PANE_SCALE_MARGINS_2H });
  // The axis options (lib/chartAxis.ts) act on this pane's price scale; its drawn axis tags are the reference lines
  // added with axisLabel above (every level except RSI's 80.81/84.75, which sit too close to label).
  return owner ? { paneIndex, owner, tags: () => tagPrices, format: "default", subPane: true, refLines, midLabel: null } : null;
}

// Returns the pane's AxisPane when the axis options reach it. Only the 2H Warren panes are wired so far; the daily /
// weekly RSI and Stochastic panes return null (their axes are never touched).
function addSubPane(chart: IChartApi, spec: PaneSpec, data: ChartOut, paneIndex: number, colors: ChartColors): AxisPane | null {
  if (spec.id === "rsi") addRsiSeries(chart, data, paneIndex, colors);
  else if (spec.id === "stochastic") addStochasticSeries(chart, data, paneIndex, colors);
  else return addWarrenSubPane(chart, spec, data, paneIndex, colors);
  return null;
}

// --- Axis options (lib/chartAxis.ts) ---------------------------------------------------------------------------
//
// One dotted reference line and whether it is drawn with an axis tag when the pane is not cleaned.
interface RefLineTag {
  line: IPriceLine;
  axisLabel: boolean;
}

// How a pane's tick labels are formatted: the library default, with overlapping labels blanked, or all blank (the clean
// sub-pane axis, whose only label is the middle one).
type FormatMode = "default" | "overlap" | "blank";

// One AxisPane per price scale the options act on. `owner` is the pane's first series: lightweight-charts formats a
// scale's tick labels with its lowest-z-order series' priceFormat, so that series carries the overlap/blank formatter.
// `tags()` are the prices of the axis tags drawn on that scale right now.
interface AxisPane {
  paneIndex: number;
  owner: ISeriesApi<SeriesType>;
  tags: () => number[];
  /** The priceFormat currently installed on `owner`, so turning an option off restores the library default. */
  format: FormatMode;
  /** A Warren sub-pane: the only kind "Clean sub-pane axes" acts on. */
  subPane: boolean;
  refLines: RefLineTag[];
  /** The clean axis' middle label while attached (null otherwise). */
  midLabel: PaneMidLabelPrimitive | null;
}

// The library's own default series priceFormat, restored when overlap hiding goes off.
const DEFAULT_PRICE_FORMAT = { type: "price" as const, precision: 2, minMove: 0.01 };

function installPriceFormat(chart: IChartApi, pane: AxisPane, mode: FormatMode) {
  if (mode === "default") {
    if (pane.format !== "default") pane.owner.applyOptions({ priceFormat: DEFAULT_PRICE_FORMAT });
    pane.format = "default";
    return;
  }
  // Same two-decimal text as the default format (formatAxisPrice). "overlap" additionally blanks any tick whose y is
  // within the tag clearance of a drawn tag (y from the live scale, priceToCoordinate, so it is the pixel position the
  // labels are drawn at); "blank" blanks every tick.
  pane.owner.applyOptions({
    priceFormat: {
      type: "custom",
      minMove: 0.01,
      formatter: formatAxisPrice,
      tickmarksFormatter: (prices: BarPrice[]) =>
        mode === "blank"
          ? prices.map(() => "")
          : tickLabelsHidingOverlap(
              prices as number[],
              (price) => pane.owner.priceToCoordinate(price),
              pane.tags(),
              overlapClearancePx(chart.options().layout.fontSize)
            ),
    },
  });
  pane.format = mode;
}

// "Clean sub-pane axes": the dotted reference lines lose their axis tags (the lines stay), and one label is drawn at the
// pane's middle instead of the regular ticks (those are blanked by the "blank" format mode). Off restores each tag.
function setCleanSubPane(chart: IChartApi, pane: AxisPane, clean: boolean, pageColor: string) {
  for (const { line, axisLabel } of pane.refLines) line.applyOptions({ axisLabelVisible: clean ? false : axisLabel });
  if (clean && !pane.midLabel) {
    pane.midLabel = new PaneMidLabelPrimitive(
      () => chart.options().layout.textColor,
      () => pageColor
    );
    pane.owner.attachPrimitive(pane.midLabel);
  } else if (!clean && pane.midLabel) {
    pane.owner.detachPrimitive(pane.midLabel);
    pane.midLabel = null;
  }
}

function applyAxisOptions(chart: IChartApi, panes: AxisPane[], options: AxisOptions, baseTextColor: string, pageColor: string) {
  // Layout first: the price-scale applyOptions below is what invalidates each scale's cached tick marks, so they
  // are rebuilt with the new font.
  chart.applyOptions({ layout: axisLayout(options, baseTextColor, readMonoFontFamily()) });
  for (const pane of panes) {
    const clean = pane.subPane && options.cleanSubPanes;
    chart.priceScale("right", pane.paneIndex).applyOptions({ tickMarkDensity: tickMarkDensity(options) });
    installPriceFormat(chart, pane, clean ? "blank" : options.hideOverlap ? "overlap" : "default");
    if (pane.subPane) setCleanSubPane(chart, pane, clean, pageColor);
  }
}

export interface ZoomBounds {
  canZoomIn: boolean;
  canZoomOut: boolean;
}

// Chart-tab-only overlay visibility toggles (see ChartTab.tsx) -- purely additive over the existing series/marker
// rendering, never touching crosshair sync or pane geometry.
interface Props extends OverlayVisibility {
  data: ChartOut;
  /** The ticker's quote_currency (TickerSummaryOut) -- OHLC prices are
   * quote-domain, must match the header's own price currency. Defaults to
   * "USD" so an omitted prop stays byte-identical. */
  quoteCurrency?: string;
  // Fully controlled from ChartTab.tsx -- an index into computeZoomLevelMultipliers's ladder, 0 =
  // the fitContent()-equivalent fit level. TickerChart owns no zoom state of its
  // own (no ref/imperative API): this codebase has no existing forwardRef/
  // useImperativeHandle usage, and a plain controlled-prop pattern is simpler here
  // since the only cross-component need is "step the index" / "know the bounds."
  zoomIndex: number;
  onZoomBoundsChange: (bounds: ZoomBounds) => void;
  /** Axis readability options (lib/chartAxis.ts), already narrowed to the current range by the caller. Omitted = all
   * off = the axes exactly as they have always been drawn. */
  axisOptions?: AxisOptions;
}

export function TickerChart({
  data,
  quoteCurrency = "USD",
  showBbRsi,
  showWarren,
  showEarnings,
  showDividends,
  showLpSupport,
  showLpResistance,
  showBollinger,
  showEma21,
  showSma50,
  showSma200,
  showStage = false,
  zoomIndex,
  onZoomBoundsChange,
  axisOptions = DEFAULT_AXIS_OPTIONS,
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
  // 2H·90D only: the hovered candle's naive-ET start (ISO), shown in the legend with its full window. Like hoverOhlc,
  // set only from the crosshair handler; null falls back to the latest candle.
  const intraday = isIntraday(data);
  const [hoverTime, setHoverTime] = useState<string | null>(null);
  const legendTime = intraday ? (hoverTime ?? lastBar?.time ?? null) : null;

  const containerRef = useRef<HTMLDivElement>(null);
  // One label per sub-pane, in pane order (see paneSpecs below); positioned from the chart's real pane geometry.
  const labelRefs = useRef<(HTMLDivElement | null)[]>([]);
  // Populated by the chart-creation effect below; read by the showBbRsi/showWarren toggle effects further down to
  // flip marker visibility via setMarkers() without recreating the chart.
  const markersApiRef = useRef<{
    bbRsi: ISeriesMarkersPluginApi<Time> | null;
    warren: ISeriesMarkersPluginApi<Time> | null;
    earnings: EventLabelsPrimitive | null;
    dividends: EventLabelsPrimitive | null;
  }>({
    bbRsi: null,
    warren: null,
    earnings: null,
    dividends: null,
  });
  // The earnings/dividend marker currently under the cursor (resolved from lightweight-charts' hoveredInfo in
  // the crosshair handler below). Holds only the id + tooltip placement -- the tooltip text is derived at render
  // time from the CURRENT data/quoteCurrency props, so it can never go stale against a closure captured when
  // the chart-creation effect last ran.
  const [hoveredEvent, setHoveredEvent] = useState<({ id: string } & TooltipPlacement) | null>(null);
  // Same purpose as markersApiRef, for the plain LineSeries overlays -- toggling one calls applyOptions({ visible })
  // on every series in the relevant list/slot (see the overlay-visibility effects below), never recreating the chart.
  const overlayApiRef = useRef<{
    lpSupport: ISeriesApi<"Line">[];
    lpResistance: ISeriesApi<"Line">[];
    bollinger: ISeriesApi<"Line">[];
    ema21: ISeriesApi<"Line"> | null;
    sma50: ISeriesApi<"Line"> | null;
    sma200: ISeriesApi<"Line"> | null;
    stageMa: ISeriesApi<"Line"> | null;
  }>({ lpSupport: [], lpResistance: [], bollinger: [], ema21: null, sma50: null, sma200: null, stageMa: null });
  // Populated by the chart-creation effect below with everything the zoom-level
  // effect (further down) needs to apply a discrete zoom level without recreating
  // the chart: the chart instance itself, and the analytic pan bounds computed
  // once from data.bars.length (see computePanBounds's own comment for why these
  // are never read back off the timeScale).
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const chartStateRef = useRef<{ chart: IChartApi; minFrom: number; maxTo: number } | null>(null);
  // Resolved once per chart creation (see the mount effect below) from the design system's named tokens (see
  // lib/chartTokens.ts) -- read here by the toggle effects further down so a marker/label rebuild after the
  // initial mount uses the same resolved colors, not a fresh (cheap, but unnecessary) re-read.
  const colorsRef = useRef<ChartColors | null>(null);
  // The price scales the Axis options act on (main pane + the 2H Warren panes), set by the chart-creation effect.
  // `axisHideOverlapRef` mirrors the option for the pan handler, which must re-run the main pane's overlap test (the
  // current-price tag follows the last visible bar) without being re-subscribed.
  const axisPanesRef = useRef<AxisPane[]>([]);
  const axisHideOverlapRef = useRef(false);

  // Pane layout: main is always pane 0; the sub-panes come from the range's pane-spec list (lib/chartPanes.ts) --
  // RSI/Stochastic (each only when it has data) on the daily/weekly ranges, Warren RSI/ADX/WVF on 2H·90D -- so a
  // thin-history ticker missing an indicator never leaves an empty gap pane. Computed here, once per data change,
  // so the chart-creation effect below and the overlay-label JSX stay in sync by construction.
  const paneSpecs = subPaneSpecs(data);
  const paneKey = paneSpecs.map((spec) => spec.id).join(",");
  const totalHeight = totalChartHeight(paneSpecs);
  // Pre-layout placeholder tops only, from the *nominal* pane heights -- never actually visible, since the layout
  // effect below overwrites every label's real `top` from the chart's own post-layout paneSize() before paint.
  // (The chart's `height` option must also budget for the shared time axis row, which these nominal sums never
  // accounted for -- confirmed via lightweight-charts.development.mjs's _private__adjustSizeImpl, which subtracts
  // timeAxisHeight from the given `height` before splitting panes -- so they are not a final value.)
  const nominalTops = nominalLabelTops(paneSpecs);

  useLayoutEffect(() => {
    if (!containerRef.current) return;

    // Computed once per data change, from the currently-rendered range's
    // own real bar count -- see computeRightOffset's own comment for why
    // this alone (no live pixel/barSpacing reading) is sufficient. Passed
    // once to the one shared chart now, rather than identically to three
    // separate instances.
    const rightOffset = computeRightOffset(data.bars.length);
    const colors = readChartColors();
    colorsRef.current = colors;

    const chart = createChart(containerRef.current, makeChartOptions(rightOffset, totalHeight, colors, intraday, axisOptions));

    const {
      candle,
      zoneLines,
      bbRsiMarkersApi,
      warrenMarkersApi,
      earningsLabelsApi,
      dividendLabelsApi,
      lpSupportSeries,
      lpResistanceSeries,
      bollingerSeries,
      ema21Series,
      sma50Series,
      sma200Series,
      stageMaSeries,
    } = addMainSeries(
      chart,
      data,
      {
        showBbRsi,
        showWarren,
        showEarnings,
        showDividends,
        showLpSupport,
        showLpResistance,
        showBollinger,
        showEma21,
        showSma50,
        showSma200,
        showStage,
      },
      colors
    );
    chart.priceScale("right", 0).applyOptions({ scaleMargins: PRICE_PANE_SCALE_MARGINS });
    markersApiRef.current = { bbRsi: bbRsiMarkersApi, warren: warrenMarkersApi, earnings: earningsLabelsApi, dividends: dividendLabelsApi };
    overlayApiRef.current = {
      lpSupport: lpSupportSeries,
      lpResistance: lpResistanceSeries,
      bollinger: bollingerSeries,
      ema21: ema21Series,
      sma50: sma50Series,
      sma200: sma200Series,
      stageMa: stageMaSeries,
    };
    candleSeriesRef.current = candle;
    const subPaneAxes = paneSpecs.map((spec, i) => addSubPane(chart, spec, data, i + 1, colors));

    // Axis options: the price scales they act on. Only the 2H range's panes are listed with options on, but the main
    // pane is always registered so the same list serves every range once its sub-panes are wired (lib/chartAxis.ts).
    const barIndexByTime = new Map(retime(data.bars, data).map((b, i) => [b.time as string | number, i]));
    axisPanesRef.current = [
      {
        paneIndex: 0,
        owner: candle,
        // The tags on the price axis: the last visible bar's close (the candle series' last-value label) and each
        // visible LP zone's level whose line has started by the last visible bar.
        tags: () => {
          const lastBar = data.bars.length - 1;
          if (lastBar < 0) return [];
          const to = chart.timeScale().getVisibleLogicalRange()?.to ?? lastBar;
          const lastVisible = Math.min(lastBar, Math.max(0, Math.floor(to)));
          const prices = [data.bars[lastVisible].close];
          for (const zone of zoneLines) {
            if (!zone.series.options().visible) continue;
            const start = barIndexByTime.get(zone.points[0].time as string | number) ?? 0;
            if (start <= lastVisible) prices.push(zone.price);
          }
          return prices;
        },
        format: "default",
        subPane: false,
        refLines: [],
        midLabel: null,
      },
      ...subPaneAxes.filter((pane): pane is AxisPane => pane !== null),
    ];

    // addSeries(..., paneIndex) above already created each pane on demand
    // -- setStretchFactor() here locks in the fixed pixel split (580/100/
    // 100), used as pure ratios since the chart's own `height` option
    // already fixes the total. Deliberately NOT setHeight(): confirmed via
    // lightweight-charts.development.mjs that setHeight() (ChartModel.
    // _internal_changePanesHeight) is a RELATIVE delta-redistribution --
    // each call nudges every OTHER pane's current height too, so three
    // sequential setHeight() calls compound (only the LAST pane called
    // lands exactly on target; earlier ones drift). setStretchFactor() is
    // a direct, independent assignment with no cross-pane side effects,
    // so all three panes land on their intended ratio regardless of call
    // order -- RSI and Stochastic (equal stretch factors) are guaranteed
    // pixel-identical to each other, not just approximately close (the three 2H·90D sub-panes likewise).
    chart.panes()[0].setStretchFactor(MAIN_PANE_HEIGHT);
    paneSpecs.forEach((spec, i) => chart.panes()[i + 1].setStretchFactor(spec.height));

    // Analytic pan bounds -- computed directly from data.bars.length/rightOffset,
    // never read back off the timeScale. See computePanBounds's own comment for
    // the full root-cause history (a synchronous getVisibleLogicalRange() read
    // right after fitContent() used to capture the timeScale's pre-fit state,
    // silently clamping the left edge months short of the true window start).
    const { minFrom, maxTo } = computePanBounds(data.bars.length);
    chart.timeScale().setVisibleLogicalRange({ from: minFrom as Logical, to: maxTo as Logical });
    extendZoneLinesToEdge(zoneLines, data.timeframe, rightOffset);
    chartStateRef.current = { chart, minFrom, maxTo };

    // Bounded right-edge pan/zoom -- see fixLeftEdge/fixRightEdge's own
    // comment on the timeScale options above for why this exists instead
    // of just setting fixRightEdge:true. minFrom/maxTo are the same analytic
    // bounds set above, guaranteed correct at any pane width or zoom level
    // (no live-read timing dependency -- see computePanBounds). A pan/zoom
    // that would push the right edge past this bound is translated (from and
    // to shifted by the same amount), preserving the current zoom level,
    // matching fixLeftEdge's own left-edge behavior; the subsequent left-edge
    // check only fires if that translation would then push `from` past the
    // first bar (i.e. the visible span itself is wider than all fetched data
    // plus the margin), in which case the span is shrunk instead -- this is
    // the one case fixLeftEdge can't correct on its own, since it only reacts
    // to genuine user pan/zoom input, not to a range this handler itself
    // just set via setVisibleLogicalRange (which bypasses fixLeftEdge's
    // own correction pass). The zoom-level effect further down (which
    // applies the button-driven computeZoomLevelMultipliers ladder) reuses this
    // exact same translate-then-shrink shape to stay consistent with pan.
    const handleVisibleRangeChange: LogicalRangeChangeEventHandler = (range) => {
      if (!range) return;
      const clamped = clampToPanBounds(range.from, range.to, minFrom, maxTo);
      if (clamped.from !== range.from || clamped.to !== range.to) {
        chart.timeScale().setVisibleLogicalRange({ from: clamped.from as Logical, to: clamped.to as Logical });
      }
      // The price tag follows the last visible bar, so a pan can change which tick labels it overlaps.
      if (axisHideOverlapRef.current) {
        const main = axisPanesRef.current[0];
        if (main) installPriceFormat(chart, main, "overlap");
      }
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);

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
      // Label k sits at the top of sub-pane k: the heights of every pane above it plus a separator per boundary.
      // Only panes < k are measured, all of which exist by this frame.
      let top = 0;
      paneSpecs.forEach((_, i) => {
        top += chart.paneSize(i).height + PANE_SEPARATOR_HEIGHT;
        const label = labelRefs.current[i];
        if (label) label.style.top = `${top}px`;
      });
    };
    const positionLabelsRafId = requestAnimationFrame(positionLabelsFromRealPaneGeometry);

    // One shared time scale for the whole pane stack means one crosshair
    // callback already covers every pane's data for the same instant --
    // no manual setCrosshairPosition relay between separate chart
    // instances needed any more (previously ~60 lines cross-wiring up to
    // three independent charts).
    chart.subscribeCrosshairMove((params) => {
      if (params.time !== undefined) {
        setHoverTime(typeof params.time === "number" ? fakeUtcToEtIso(params.time) : null);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const bar = params.seriesData.get(candle as any) as any;
        if (bar && bar.open !== undefined) {
          setHoverOhlc({ o: bar.open, h: bar.high, l: bar.low, c: bar.close });
        }
      } else {
        setHoverOhlc(null); // falls back to defaultOhlc (the latest bar) above
        setHoverTime(null);
      }

      // Event-label hover: lightweight-charts 5.2.0 reports a custom primitive's hit via hoveredInfo (objectKind
      // "primitive", objectId === the externalId EventLabelsPrimitive.hitTest returned, i.e. the label's `id`).
      // Anything else that reports an id resolves to no tooltip in describeEventMarker.
      const hovered = params.hoveredInfo;
      if (hovered?.objectKind === "primitive" && typeof hovered.objectId === "string" && hovered.objectId !== "" && params.point) {
        // Decided here (an event handler), not at render: reading the container's width during render would
        // mean reading a ref there.
        const width = containerRef.current?.clientWidth ?? 0;
        setHoveredEvent({ id: hovered.objectId, ...eventTooltipPlacement(params.point.x, params.point.y, width) });
      } else {
        setHoveredEvent(null); // no-op (same value) when already null
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
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      chart.remove();
      markersApiRef.current = { bbRsi: null, warren: null, earnings: null, dividends: null };
      overlayApiRef.current = { lpSupport: [], lpResistance: [], bollinger: [], ema21: null, sma50: null, sma200: null, stageMa: null };
      candleSeriesRef.current = null;
      chartStateRef.current = null;
      colorsRef.current = null;
      axisPanesRef.current = [];
    };
    // Every showXxx toggle is intentionally excluded here: they only set the INITIAL visibility at chart creation
    // (read once, via closure); a later toggle flip is handled by the separate effects below via
    // setMarkers()/applyOptions({ visible }), without tearing down and recreating the whole chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, totalHeight, paneKey]);

  // Applies the button-driven discrete zoom level (see computeZoomLevelMultipliers) --
  // deliberately a separate, lightweight effect from the chart-creation one above
  // (same "don't recreate the whole chart" reasoning as the showXxx toggle effects
  // below), keyed on `data` too so it correctly reapplies the CURRENT zoomIndex to
  // a freshly (re)created chart -- e.g. a background SWR refetch that leaves
  // zoomIndex untouched still needs this to run against the new chart instance
  // chartStateRef now points at. Recomputing the multiplier ladder here too
  // (rather than reading it once at mount) is deliberate: `data` is already a
  // dependency for the reasons above, and the ladder is cheap to derive, so
  // there's no separate state/memo to keep in sync with the chart-creation
  // effect's own barCount/rightOffset read.
  useEffect(() => {
    const state = chartStateRef.current;
    if (!state) return;
    const { chart, minFrom, maxTo } = state;
    const paneWidth = chart.timeScale().width();
    if (!paneWidth) return;

    const barCount = data.bars.length;
    const rightOffset = computeRightOffset(barCount);
    const fitBarSpacing = paneWidth / (barCount + rightOffset);
    const multipliers = computeZoomLevelMultipliers(barCount, rightOffset);
    const lastIndex = multipliers.length - 1;
    const clampedIndex = Math.min(Math.max(zoomIndex, 0), lastIndex);
    const barSpacing = barSpacingForZoomLevel(fitBarSpacing, clampedIndex, multipliers);
    const visibleBarCount = paneWidth / barSpacing;

    // Anchor every zoom-level change to the RIGHT edge (`to = maxTo`, the same
    // last-real-bar + rightOffset margin the initial view and pan clamp already
    // use), NOT the current pan position -- a deliberate change from this file's
    // previous behavior (recenter on wherever the user was panned to), which was
    // the actual bug being fixed here: the dominant case is "looking at the most
    // recent bars, then zoom," and recentering silently moved the right edge out
    // of view, forcing an immediate re-pan right just to see today's bar again.
    // Always anchoring right is the simplest, most predictable rule -- one
    // behavior, no "was the user close enough to the edge to count as still
    // there" threshold -- and matches the right edge's existing role as this
    // chart's canonical resting position (the initial view already opens there).
    // The tradeoff: a user who deliberately panned left to inspect older history
    // and then clicks zoom will jump back to the latest bars rather than keep
    // their scrolled-away position centered -- accepted as the less common case.
    const { from, to } = clampToPanBounds(maxTo - visibleBarCount, maxTo, minFrom, maxTo);
    chart.timeScale().setVisibleLogicalRange({ from: from as Logical, to: to as Logical });

    const canZoomOut = clampedIndex > 0;
    const nextIndex = clampedIndex + 1;
    const canZoomIn = nextIndex <= lastIndex && barSpacingForZoomLevel(fitBarSpacing, nextIndex, multipliers) > barSpacing;
    onZoomBoundsChange({ canZoomIn, canZoomOut });
  }, [data, zoomIndex, onZoomBoundsChange]);

  // Syncs marker/series visibility on a toggle flip alone -- deliberately not combined with the chart-creation
  // effect above, which would otherwise tear down and recreate the whole chart (losing crosshair state, pane
  // layout, etc.) on every toggle click. Each of these also runs once on initial mount (React runs every effect
  // after the first render), which just re-applies the same visibility addMainSeries already set -- a harmless
  // no-op.
  useEffect(() => {
    const colors = colorsRef.current;
    if (!colors) return;
    markersApiRef.current.bbRsi?.setMarkers(showBbRsi ? buildEntrySignalMarkers(data, colors.chartUp) : []);
  }, [data, showBbRsi]);

  useEffect(() => {
    const colors = colorsRef.current;
    if (!colors) return;
    markersApiRef.current.warren?.setMarkers(showWarren ? buildWarrenMarkers(data, colors) : []);
  }, [data, showWarren]);

  useEffect(() => {
    const colors = colorsRef.current;
    if (!colors) return;
    markersApiRef.current.earnings?.setLabels(showEarnings ? buildEarningsLabels(data.earnings_markers, colors.chartEventEarnings) : []);
  }, [data, showEarnings]);

  useEffect(() => {
    const colors = colorsRef.current;
    if (!colors) return;
    markersApiRef.current.dividends?.setLabels(
      showDividends ? buildDividendLabels(data.dividend_markers, colors.chartEventDividend, data.earnings_markers) : []
    );
  }, [data, showDividends]);

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

  // Stage toggle: MA line visibility + candle recolor. Recoloring is a setData on the existing candle series (no chart
  // recreation); off restores the plain data.bars, byte-identical to the non-Stage rendering.
  useEffect(() => {
    overlayApiRef.current.stageMa?.applyOptions({ visible: showStage });
    const candle = candleSeriesRef.current;
    if (!candle) return;
    const staged = showStage && data.weinstein_stages?.length > 0;
    if (!staged) {
      candle.setData(retime(data.bars, data));
      return;
    }
    const colors = colorsRef.current;
    const stagePalette = colors
      ? { base: colors.stageBase, advance: colors.stageAdvance, top: colors.stageTop, decline: colors.stageDecline }
      : undefined;
    candle.setData(buildStageColoredBars(data.bars, data.weinstein_stages, stagePalette));
  }, [showStage, data]);

  // Axis options: applied to the live chart on a change, never recreating it. After the LP visibility effects above
  // because the overlap test reads which LP lines are visible. Also runs once after creation, where all-off is a no-op.
  useEffect(() => {
    const chart = chartStateRef.current?.chart;
    const colors = colorsRef.current;
    if (!chart || !colors) return;
    axisHideOverlapRef.current = axisOptions.hideOverlap;
    applyAxisOptions(chart, axisPanesRef.current, axisOptions, colors.textSecondary, colors.page);
  }, [data, axisOptions, showLpSupport, showLpResistance]);

  // Derived at render time from current props (see hoveredEvent's comment above).
  const eventTooltip = hoveredEvent
    ? describeEventMarker(hoveredEvent.id, data.earnings_markers, data.dividend_markers, quoteCurrency)
    : null;

  return (
    <div className="rounded-lg border border-border-card">
      <div className="relative bg-page">
        <div className="absolute top-2 left-3 z-10 select-none pointer-events-none">
          {ohlc && (
            <div className="flex items-center gap-2.5 text-xs font-mono">
              {legendTime && <span className="text-text-secondary">{formatCandleLegendTime(legendTime)}</span>}
              <span className="text-text-tertiary">
                O <span className="text-text-secondary">{fmtMoney(ohlc.o, quoteCurrency)}</span>
              </span>
              <span className="text-text-tertiary">
                H <span className="text-chart-up">{fmtMoney(ohlc.h, quoteCurrency)}</span>
              </span>
              <span className="text-text-tertiary">
                L <span className="text-chart-down">{fmtMoney(ohlc.l, quoteCurrency)}</span>
              </span>
              <span className="text-text-tertiary">
                C <span className="text-text-primary">{fmtMoney(ohlc.c, quoteCurrency)}</span>
              </span>
            </div>
          )}
        </div>

        {paneSpecs.map((spec, i) => (
          <div
            key={spec.id}
            ref={(el) => {
              labelRefs.current[i] = el;
            }}
            className="absolute left-3 z-10 text-[10px] font-mono text-text-tertiary select-none pointer-events-none"
            style={{ top: nominalTops[i] }} // placeholder; corrected from real pane geometry in the layout effect above
          >
            {spec.label}
            {spec.legend?.map((item) => (
              <span key={item.text} className={`ml-1.5 ${item.className}`}>
                {item.text}
              </span>
            ))}
          </div>
        ))}

        <div ref={containerRef} className="w-full" style={{ height: totalHeight }} />

        {eventTooltip && hoveredEvent && (
          <div
            className="absolute z-20 pointer-events-none select-none text-xs font-mono"
            // Above the cursor (the event row is on the pane floor), flipped left near the right edge --
            // see eventTooltipPlacement.
            style={{ left: hoveredEvent.left, top: hoveredEvent.top, transform: hoveredEvent.transform }}
          >
            {/* TooltipCard is the shared floating-card surface look -- see components/ui/tooltip.tsx. Title reads
                as the tooltip's "label" (what/when), the EPS/dividend lines as its "value" content. */}
            <TooltipCard>
              <div className="text-text-secondary">{eventTooltip.title}</div>
              {eventTooltip.lines.map((line) => (
                <div key={line} className="text-text-primary">
                  {line}
                </div>
              ))}
            </TooltipCard>
          </div>
        )}
      </div>
    </div>
  );
}
