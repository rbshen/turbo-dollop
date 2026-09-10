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
  // Same dark gray as the main pane's last-close price line -- distinct
  // from the #808080 RSI/StochD data-line gray so the static 70/30 and
  // 80/20 reference lines read as background guides, not data.
  refLine: "#52525b",
  // Liquidity Zone (LP) support/resistance overlay -- a warm amber "floor"
  // vs. a muted purple "ceiling," deliberately not green/red (which would
  // misread as bullish/bearish the way the candles already use those
  // colors; a support level isn't itself a buy signal). Distinct from
  // every other color already on this chart.
  lpSupport: "#D4A24C",
  lpResistance: "#9C6ADE",
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
    timeScale: { borderColor: CHART_THEME.border, timeVisible: false, rightOffset: 10 },
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
  });
  candle.setData(data.bars);

  if (data.bars.length > 0) {
    const last = data.bars[data.bars.length - 1];
    candle.createPriceLine({
      price: last.close,
      color: "#52525b",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
      title: "",
    });
  }

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
  // that swing point and stops at the last visible bar -- no title/axis
  // label, so it reads as a plain flat level, not a named indicator line.
  for (const zone of data.zones) {
    const isSupport = zone.side === "support";
    const points = data.bars.filter((b) => b.time >= zone.formed_at).map((b) => ({ time: b.time, value: zone.price }));
    if (!points.length) continue;
    const zoneLine = chart.addSeries(LineSeries, {
      color: isSupport ? COLORS.lpSupport : COLORS.lpResistance,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    zoneLine.setData(points);
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

  return candle;
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
    const candle = renderMain(main, data);
    main.timeScale().fitContent();

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
