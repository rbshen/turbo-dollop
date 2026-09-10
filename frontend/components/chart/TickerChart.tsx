"use client";
import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, LineSeries, createSeriesMarkers, LineStyle } from "lightweight-charts";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
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
};

const RSI_OVERBOUGHT = 70;
const RSI_OVERSOLD = 30;
const STOCH_OVERBOUGHT = 80;
const STOCH_OVERSOLD = 20;

interface OhlcState {
  o: number;
  h: number;
  l: number;
  c: number;
}

function makeChartOptions(height?: number) {
  return {
    layout: {
      background: { color: CHART_THEME.background },
      textColor: CHART_THEME.text,
      fontSize: 11,
      fontFamily: "var(--font-mono), ui-monospace, monospace",
      attributionLogo: false,
    },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    handleScroll: false,
    handleScale: false,
    rightPriceScale: { borderColor: CHART_THEME.border },
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
    timeScale: { borderColor: CHART_THEME.border, timeVisible: false, rightOffset: 10, shiftVisibleRangeOnNewBar: false },
    crosshair: { mode: 1 },
    ...(height !== undefined ? { height } : {}),
  };
}

function renderMain(chart: IChartApi, data: ChartOut) {
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
    });
    line.setData(pts);
  }

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
      });
      bb.setData(data.bollinger.map((b) => ({ time: b.time, value: b[key] })));
    }
  }

  // Liquidity Zone (LP) support/resistance levels -- a LineSeries per
  // zone, not createPriceLine: PriceLineOptions (confirmed via v5.2.0's
  // own typings, no partial-range option exists) has no time-bound field
  // at all, so createPriceLine always spans the full chart width
  // regardless of when the zone actually formed. A LineSeries fed only
  // the bars from formed_at onward naturally starts drawing exactly at
  // that swing point and stops at the last visible bar -- the caller
  // (see useEffect below) extends each one past the last real bar, into
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
    });
    zoneLine.setData(points);
    zoneLines.push({ series: zoneLine, points });
  }

  if (data.entry_signal_marker) {
    const marker = data.entry_signal_marker;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    createSeriesMarkers(candle as any, [
      {
        time: marker.time,
        position: "belowBar" as const,
        color: COLORS.marker,
        shape: "arrowUp" as const,
        text: marker.label,
        size: 1,
      },
    ]);
  }

  return { candle, zoneLines };
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
  const incrementDays = timeframe === "weekly" ? 7 : 1;
  for (const { series, points } of zoneLines) {
    if (!points.length) continue;
    const last = points[points.length - 1];
    const extension = futureDateStrings(last.time, rightOffset, incrementDays).map((time) => ({ time, value: last.value }));
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

function renderRsi(container: HTMLElement, data: ChartOut) {
  const chart = createChart(container, {
    ...makeChartOptions(120),
    timeScale: { borderColor: CHART_THEME.border, visible: false, rightOffset: 10 },
  });
  const series = chart.addSeries(LineSeries, {
    color: COLORS.rsi,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  });
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
  return { chart, series };
}

function renderStochastic(container: HTMLElement, data: ChartOut) {
  const chart = createChart(container, {
    ...makeChartOptions(120),
    timeScale: { borderColor: CHART_THEME.border, visible: false, rightOffset: 10 },
  });
  const kSeries = chart.addSeries(LineSeries, { color: COLORS.stochK, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  const dSeries = chart.addSeries(LineSeries, { color: COLORS.stochD, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  kSeries.setData(data.stochastic.map((p) => ({ time: p.time, value: p.k })));
  dSeries.setData(data.stochastic.map((p) => ({ time: p.time, value: p.d })));
  addRefLine(kSeries, STOCH_OVERBOUGHT);
  addRefLine(kSeries, STOCH_OVERSOLD);
  return { chart, series: kSeries };
}

interface Props {
  data: ChartOut;
}

export function TickerChart({ data }: Props) {
  // Default OHLC (the latest bar) is a plain derived value, not state --
  // avoids a setState-during-effect render cascade for the common "nothing
  // hovered yet" case. hoverOhlc is real state, set only from the
  // crosshair-move event handler below (a legitimate setState-in-callback,
  // not a synchronous setState-in-effect-body).
  const lastBar = data.bars.length > 0 ? data.bars[data.bars.length - 1] : null;
  const defaultOhlc: OhlcState | null = lastBar ? { o: lastBar.open, h: lastBar.high, l: lastBar.low, c: lastBar.close } : null;
  const [hoverOhlc, setHoverOhlc] = useState<OhlcState | null>(null);
  const ohlc = hoverOhlc ?? defaultOhlc;

  const mainRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const stochRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mainRef.current) return;

    const main = createChart(mainRef.current, makeChartOptions());
    const { candle, zoneLines } = renderMain(main, data);
    main.timeScale().fitContent();
    extendZoneLinesToEdge(main, zoneLines, data.timeframe);

    let rsiChart: IChartApi | null = null;
    let rsiSeries: ISeriesApi<"Line"> | null = null;
    if (data.rsi.length && rsiRef.current) {
      const result = renderRsi(rsiRef.current, data);
      rsiChart = result.chart;
      rsiSeries = result.series;
      rsiChart.timeScale().fitContent();
    }

    let stochChart: IChartApi | null = null;
    let stochSeries: ISeriesApi<"Line"> | null = null;
    if (data.stochastic.length && stochRef.current) {
      const result = renderStochastic(stochRef.current, data);
      stochChart = result.chart;
      stochSeries = result.series;
      stochChart.timeScale().fitContent();
    }

    // Cross-wire the crosshair across however many of the three panes are
    // actually mounted (RSI/Stochastic panes are conditionally rendered
    // above whenever a ticker's history is too thin for that indicator's
    // own warm-up) -- a suppress flag per pane prevents each pane's own
    // subscribeCrosshairMove from re-triggering the others in a loop.
    const panes: Array<{ chart: IChartApi; series: ISeriesApi<"Line"> }> = [];
    if (rsiChart && rsiSeries) panes.push({ chart: rsiChart, series: rsiSeries });
    if (stochChart && stochSeries) panes.push({ chart: stochChart, series: stochSeries });

    let suppress = false;
    main.subscribeCrosshairMove((params) => {
      if (params.time !== undefined) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const bar = params.seriesData.get(candle as any) as any;
        if (bar && bar.open !== undefined) {
          setHoverOhlc({ o: bar.open, h: bar.high, l: bar.low, c: bar.close });
        }
      } else {
        setHoverOhlc(null); // falls back to defaultOhlc (the latest bar) above
      }

      if (suppress) return;
      suppress = true;
      for (const pane of panes) {
        if (params.time !== undefined) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          pane.chart.setCrosshairPosition(NaN, params.time, pane.series as any);
        } else {
          pane.chart.clearCrosshairPosition();
        }
      }
      suppress = false;
    });

    for (const pane of panes) {
      pane.chart.subscribeCrosshairMove((params) => {
        if (suppress) return;
        suppress = true;
        if (params.time !== undefined) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          main.setCrosshairPosition(NaN, params.time, candle as any);
        } else {
          main.clearCrosshairPosition();
        }
        for (const other of panes) {
          if (other === pane) continue;
          if (params.time !== undefined) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            other.chart.setCrosshairPosition(NaN, params.time, other.series as any);
          } else {
            other.chart.clearCrosshairPosition();
          }
        }
        suppress = false;
      });
    }

    const observer = new ResizeObserver(() => {
      const w = mainRef.current?.clientWidth;
      if (w) {
        main.applyOptions({ width: w });
        rsiChart?.applyOptions({ width: w });
        stochChart?.applyOptions({ width: w });
      }
    });
    if (mainRef.current) observer.observe(mainRef.current);

    return () => {
      observer.disconnect();
      main.remove();
      rsiChart?.remove();
      stochChart?.remove();
    };
  }, [data]);

  return (
    <div className="rounded-lg border border-border-card">
      <div className="bg-zinc-950">
        <div className="relative">
          <div className="absolute top-2 left-3 z-10 flex flex-col gap-0.5 select-none pointer-events-none">
            <span className="text-[10px] font-mono font-semibold text-zinc-600">{data.timeframe === "weekly" ? "1W" : "1D"}</span>
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
          <div ref={mainRef} className="w-full" style={{ height: 630 }} />
        </div>

        {data.rsi.length > 0 && (
          <div className="relative border-t border-zinc-800/60">
            <div className="absolute top-1.5 left-3 z-10 text-[10px] font-mono text-zinc-600 select-none pointer-events-none">RSI (14)</div>
            <div ref={rsiRef} className="w-full" style={{ height: 120 }} />
          </div>
        )}

        {data.stochastic.length > 0 && (
          <div className="relative border-t border-zinc-800/60">
            <div className="absolute top-1.5 left-3 z-10 text-[10px] font-mono text-zinc-600 select-none pointer-events-none">
              Full Stochastic (5, 3, 3)
            </div>
            <div ref={stochRef} className="w-full" style={{ height: 120 }} />
          </div>
        )}
      </div>
    </div>
  );
}
