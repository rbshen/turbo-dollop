// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { LineStyle } from "lightweight-charts";
import type { IChartApi, ISeriesApi, SeriesType } from "lightweight-charts";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { TickerChart } from "@/components/chart/TickerChart";
import type { ChartOut } from "@/lib/api/types";
import { AXIS_TEXT_COLOR } from "@/lib/chartAxis";
import { etIsoToFakeUtc } from "@/lib/chartTime";
import { computeRightOffset } from "@/lib/chartZoom";

// Mounts the REAL TickerChart (lightweight-charts under jsdom, with a no-op canvas context -- jsdom has no layout, so
// pixel geometry and the zoom effect are not exercised here) and inspects the chart it created: pane count, stretch
// factors, time-axis options, and that nothing throws on 2h data (this caught a price-scale-before-pane-exists bug).
let created: IChartApi | null = null;
let allSeries: ISeriesApi<SeriesType>[] = [];
// Every marker array handed to createSeriesMarkers (BB+RSI and Warren each create one plugin).
let markerSets: Record<string, unknown>[][] = [];
vi.mock("lightweight-charts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("lightweight-charts")>();
  return {
    ...actual,
    createSeriesMarkers: (...args: Parameters<typeof actual.createSeriesMarkers>) => {
      markerSets.push(args[1] as unknown as Record<string, unknown>[]);
      return actual.createSeriesMarkers(...args);
    },
    createChart: (...args: Parameters<typeof actual.createChart>) => {
      const chart = actual.createChart(...args);
      const addSeries = chart.addSeries.bind(chart) as (...a: unknown[]) => ISeriesApi<SeriesType>;
      (chart as unknown as { addSeries: unknown }).addSeries = (...a: unknown[]) => {
        const series = addSeries(...a);
        allSeries.push(series);
        return series;
      };
      created = chart;
      return chart;
    },
  };
});

beforeAll(() => {
  const ctx: unknown = new Proxy({}, { get: (_t, k) => (k === "measureText" ? () => ({ width: 10 }) : k === "canvas" ? document.createElement("canvas") : () => ctx), set: () => true });
  HTMLCanvasElement.prototype.getContext = (() => ctx) as never;
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
});
afterEach(() => {
  cleanup();
  created = null;
  allSeries = [];
  markerSets = [];
});

const SESSION_TIMES = ["09:30", "11:30", "13:30", "15:30"];

function intradayBars(sessions = 40) {
  const bars: { time: string; open: number; high: number; low: number; close: number }[] = [];
  const line: { time: string; value: number }[] = [];
  let price = 100;
  for (let d = 0; d < sessions; d++) {
    const day = new Date(Date.UTC(2026, 6, 6 + d + Math.floor(d / 5) * 2)).toISOString().slice(0, 10);
    for (const t of SESSION_TIMES) {
      price += Math.sin(bars.length / 5);
      bars.push({ time: `${day}T${t}:00`, open: price, high: price + 1, low: price - 1, close: price + 0.2 });
      line.push({ time: `${day}T${t}:00`, value: 50 + 20 * Math.sin(bars.length / 7) });
    }
  }
  return { bars, line };
}

function base(): Omit<ChartOut, "range" | "timeframe" | "bars"> {
  return {
    ema21: [], sma50: [], sma200: [], bollinger: [], stochastic: [], rsi: [],
    entry_signal_markers: [], entry_signal_available: true, weinstein_ma: [], weinstein_ma_label: null, weinstein_stages: [],
    warren_signal_markers: [], warren_signal_available: true, zones: [], zones_available: true,
    earnings_markers: [], dividend_markers: [], events_source: null,
    warren_rsi: [], warren_adx: [], warren_plus_di: [], warren_minus_di: [], warren_wvf: [], warren_levels: null, warren_instruction: null,
    source: "fmp", chart_available: true,
  } as unknown as Omit<ChartOut, "range" | "timeframe" | "bars">;
}

function twoHData(): ChartOut {
  const { bars, line } = intradayBars();
  return {
    ...base(),
    range: "2H_90D",
    timeframe: "2h",
    bars,
    entry_signal_markers: [{ time: bars[10].time, label: "BB+RSI", kind: "bb_rsi" }],
    warren_signal_markers: [
      { time: bars[20].time, label: "Blue Up", kind: "blue_up" },
      { time: bars[20].time, label: "Yellow Up", kind: "yellow_up" }, // two arrows on one candle
    ],
    zones: [
      { side: "support", price: 95, formed_at: bars[30].time, broken: false },
      { side: "resistance", price: 110, formed_at: bars[5].time, broken: true },
    ],
    warren_rsi: line, warren_adx: line, warren_plus_di: line, warren_minus_di: line,
    warren_wvf: line.map((p) => ({ ...p, value: 2 })),
    warren_levels: { rsi: [12, 30, 70, 80.81, 84.75], adx: [40], wvf: [0.4] },
  } as ChartOut;
}

const props = {
  showBbRsi: true, showWarren: true, showEarnings: false, showDividends: false, showLpSupport: true, showLpResistance: true,
  showBollinger: false, showEma21: false, showSma50: false, showSma200: false, zoomIndex: 0, onZoomBoundsChange: () => {},
};

it("2H·90D: mounts with main + three Warren sub-panes (stretch 580/100/100/100), HH:MM axis, window legend", () => {
  const { getByText, container } = render(<TickerChart data={twoHData()} {...props} />);
  expect(created).not.toBeNull();
  const panes = created!.panes();
  expect(panes).toHaveLength(4);
  expect(panes.map((p) => p.getStretchFactor())).toEqual([580, 100, 100, 100]);
  expect(created!.options().timeScale.timeVisible).toBe(true);
  expect(getByText(/Warren RSI \(14\) · 12 · 80\.81 · 84\.75/)).toBeInTheDocument(); // no 30/70: those lines are gone
  expect(getByText(/Warren ADX \(14\) · 40/)).toBeInTheDocument();
  expect(getByText(/Warren WVF \(22\) · 0\.40/)).toBeInTheDocument();
  expect(container.textContent).toMatch(/15:30–16:00 ET/); // the latest candle's full window in the legend
});

it("2H·90D: candles, sub-pane lines and zone lines use fake-UTC numeric times; zones start at the swing candle", () => {
  const data = twoHData();
  render(<TickerChart data={data} {...props} />);
  const fake = (iso: string) => etIsoToFakeUtc(iso) as number;

  const candle = allSeries.find((s) => s.seriesType() === "Candlestick")!;
  const candleTimes = candle.data().map((d) => d.time as number);
  expect(candleTimes).toEqual(data.bars.map((b) => fake(b.time)));
  expect(candleTimes.every((t) => typeof t === "number")).toBe(true);

  // Zone lines: LineSeries whose points are all one constant price -- one per zone, 95 (support) and 110 (broken resistance).
  const zoneLines = allSeries.filter((s) => s.seriesType() === "Line" && new Set(s.data().map((d) => (d as { value: number }).value)).size === 1 && [95, 110].includes((s.data()[0] as { value: number }).value));
  expect(zoneLines).toHaveLength(2);
  for (const line of zoneLines) {
    const times = line.data().map((d) => d.time as number);
    const price = (line.data()[0] as { value: number }).value;
    const swing = fake((data.zones.find((z) => z.price === price)!).formed_at);
    expect(times[0]).toBe(swing); // starts exactly at the swing candle
    const real = candleTimes.filter((t) => t >= swing);
    expect(times.slice(0, real.length)).toEqual(real);
    const extension = times.slice(real.length);
    expect(extension).toHaveLength(Math.ceil(computeRightOffset(candleTimes.length))); // ceil(rightOffset) numeric margin points, strictly increasing past the last candle
    expect(extension[0]).toBeGreaterThan(candleTimes.at(-1)!);
    expect(extension).toEqual([...extension].sort((a, b) => a - b));
  }

  // The three Warren sub-pane series (RSI; ADX alone, no +DI/-DI; WVF) carry numeric times too.
  const subPaneLines = allSeries.filter((s) => s.getPane().paneIndex() > 0);
  expect(subPaneLines).toHaveLength(3);
  for (const s of subPaneLines) expect(s.data().every((d) => typeof d.time === "number")).toBe(true);
  expect(subPaneLines.map((s) => s.getPane().paneIndex())).toEqual([1, 2, 3]);
});

it("2H·90D: toggling overlays after mount does not throw (markers, zone lines)", () => {
  const data = twoHData();
  const { rerender } = render(<TickerChart data={data} {...props} />);
  rerender(<TickerChart data={data} {...props} showWarren={false} showBbRsi={false} showLpSupport={false} showLpResistance={false} zoomIndex={2} />);
  rerender(<TickerChart data={data} {...props} />);
  expect(created!.panes()).toHaveLength(4);
});

it("daily ranges keep their date-only axis and the two RSI/Stochastic panes (580/100/100)", () => {
  const dates = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"];
  const data = {
    ...base(),
    range: "D_6M",
    timeframe: "daily",
    bars: dates.map((time, i) => ({ time, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i })),
    rsi: dates.map((time, i) => ({ time, value: 40 + i })),
    stochastic: dates.map((time, i) => ({ time, k: 30 + i, d: 31 + i })),
  } as ChartOut;
  const { getByText } = render(<TickerChart data={data} {...props} />);
  expect(created!.panes().map((p) => p.getStretchFactor())).toEqual([580, 100, 100]);
  expect(created!.options().timeScale.timeVisible).toBe(false);
  expect(getByText("RSI (14)")).toBeInTheDocument();
  expect(getByText("Full Stochastic (5, 3, 3) EMA")).toBeInTheDocument();
  // Daily bars keep their business-day strings untouched.
  expect(allSeries.find((s) => s.seriesType() === "Candlestick")!.data().map((d) => d.time)).toEqual(dates);
});

// --- Warren pane reference lines ---

const tagsOf = (pane: number) =>
  allSeries.filter((s) => s.getPane().paneIndex() === pane).flatMap((s) => s.priceLines().map((l) => [l.options().price, l.options().axisLabelVisible]));

it("2H·90D: the RSI pane draws only the dashed 12, 80.81 and 84.75 lines; ADX only the dashed 40; WVF only 0.40", () => {
  render(<TickerChart data={twoHData()} {...props} />);
  const styles = (pane: number) => allSeries.filter((s) => s.getPane().paneIndex() === pane).flatMap((s) => s.priceLines().map((l) => l.options().lineStyle));
  expect(tagsOf(1).map(([price]) => price)).toEqual([12, 80.81, 84.75]);
  expect(tagsOf(2).map(([price]) => price)).toEqual([40]);
  expect(tagsOf(3).map(([price]) => price)).toEqual([0.4]);
  for (const pane of [1, 2, 3]) expect(styles(pane).every((st) => st === LineStyle.Dashed)).toBe(true);
});

it("2H·90D: every dotted line has an axis tag; RSI's close pair is tagged by the nudging primitive instead of the library", () => {
  render(<TickerChart data={twoHData()} {...props} />);
  expect(tagsOf(1)).toEqual([[12, true], [80.81, false], [84.75, false]]); // 80.81 / 84.75: LevelTagsPrimitive draws these two
  expect(tagsOf(2)).toEqual([[40, true]]);
  expect(tagsOf(3)).toEqual([[0.4, true]]);
});

// --- Permanent axis settings (every range) ---

const layoutOf = () => created!.options().layout;
const densityOf = (pane: number) => created!.priceScale("right", pane).options().tickMarkDensity;
const formatOf = (pane: number) => allSeries.filter((s) => s.getPane().paneIndex() === pane)[0].options().priceFormat;

function dailyData(range: "D_6M" | "W_4Y" = "D_6M"): ChartOut {
  const dates = ["2026-07-06", "2026-07-13", "2026-07-20", "2026-07-27", "2026-08-03"];
  return {
    ...base(), range, timeframe: range === "W_4Y" ? "weekly" : "daily",
    bars: dates.map((time, i) => ({ time, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i })),
    rsi: dates.map((time, i) => ({ time, value: i === 1 ? 85 : 50 })),
    stochastic: dates.map((time, i) => ({ time, k: 30 + i, d: 31 + i })),
  } as ChartOut;
}

it("every range: brighter color at the unchanged 12 px and the monospace face; fewer ticks on the PRICE scale only", () => {
  render(<TickerChart data={twoHData()} {...props} />);
  expect(layoutOf().textColor).toBe(AXIS_TEXT_COLOR);
  expect(layoutOf().fontSize).toBe(12);
  expect(layoutOf().fontFamily).not.toContain("var(");
  expect(densityOf(0)).toBe(5);
  for (const pane of [1, 2, 3]) expect(densityOf(pane)).toBe(2.5); // sub-panes draw no tick labels: density is moot, left at the default
  cleanup();
  render(<TickerChart data={dailyData()} {...props} />); // daily: price + RSI + Stochastic
  expect(layoutOf().textColor).toBe(AXIS_TEXT_COLOR);
  expect(layoutOf().fontSize).toBe(12);
  expect(layoutOf().fontFamily).not.toContain("var(");
  expect(created!.panes()).toHaveLength(3);
  expect(densityOf(0)).toBe(5);
  for (const pane of [1, 2]) expect(densityOf(pane)).toBe(2.5);
});

// --- Sub-panes: no regular tick labels, level tags kept ---

const blankTicksOf = (pane: number) => {
  const fmt = formatOf(pane) as unknown as { tickmarksFormatter?: (p: number[]) => string[]; formatter?: (p: number) => string };
  return { ticks: fmt.tickmarksFormatter?.([10, 20.5, 50, 84.75]), tag: fmt.formatter?.(84.75) };
};

it("every sub-pane draws no regular tick labels (Warren RSI/ADX/WVF, and daily + weekly RSI/Stochastic), with the toggle on or off; the level tags still format normally", () => {
  const cases: [string, ChartOut, number[]][] = [
    ["2H", twoHData(), [1, 2, 3]],
    ["D_6M", dailyData(), [1, 2]],
    ["W_4Y", dailyData("W_4Y"), [1, 2]],
  ];
  for (const [, data, panes] of cases) {
    for (const axisOptions of [{ hideOverlap: true }, { hideOverlap: false }]) {
      render(<TickerChart data={data} {...props} axisOptions={axisOptions} />);
      for (const pane of panes) expect(blankTicksOf(pane)).toEqual({ ticks: ["", "", "", ""], tag: "84.75" });
      cleanup();
      allSeries = [];
    }
  }
});

it("the level-line tags stay on every sub-pane (Warren 12 / 80.81 / 84.75, 40, 0.40; RSI 70/30; Stochastic 80/20)", () => {
  render(<TickerChart data={twoHData()} {...props} />);
  expect(tagsOf(1)).toEqual([[12, true], [80.81, false], [84.75, false]]); // 80.81 / 84.75: tagged by LevelTagsPrimitive
  expect(tagsOf(2)).toEqual([[40, true]]);
  expect(tagsOf(3)).toEqual([[0.4, true]]);
  cleanup();
  allSeries = [];
  render(<TickerChart data={dailyData()} {...props} />);
  expect(tagsOf(1)).toEqual([[70, true], [30, true]]);
  expect(tagsOf(2)).toEqual([[80, true], [20, true]]);
});

// --- Hide overlapping labels (the one toggle, on by default) ---

it("hide overlapping labels is ON by default on every range: the price pane carries the overlap formatter; off restores the library default; on again re-installs it", () => {
  for (const data of [twoHData(), dailyData(), dailyData("W_4Y")]) {
    const { rerender } = render(<TickerChart data={data} {...props} />);
    expect(formatOf(0).type).toBe("custom"); // default on
    rerender(<TickerChart data={data} {...props} axisOptions={{ hideOverlap: false }} />);
    expect(formatOf(0)).toMatchObject({ type: "price", precision: 2, minMove: 0.01 });
    expect(created!.panes().length).toBeGreaterThan(1); // applied to the live chart, not a rebuild
    rerender(<TickerChart data={data} {...props} axisOptions={{ hideOverlap: true }} />);
    expect(formatOf(0).type).toBe("custom");
    cleanup();
    allSeries = [];
  }
});

// With the series' y mapping stubbed to the identity, the overlap formatter blanks exactly the ticks within the tag clearance.
function tickLabels(pane: number, prices: number[]) {
  const owner = allSeries.filter((s) => s.getPane().paneIndex() === pane)[0];
  owner.priceToCoordinate = ((p: number) => p) as typeof owner.priceToCoordinate;
  const fmt = owner.options().priceFormat as unknown as { tickmarksFormatter: (p: number[]) => string[] };
  return fmt.tickmarksFormatter(prices);
}

it("hide overlapping labels: the W·4Y Weinstein MA's last value is a price tag (only while the Stage line is shown)", () => {
  const data = {
    ...dailyData("W_4Y"),
    weinstein_ma: ["2026-07-06", "2026-07-13", "2026-07-20", "2026-07-27", "2026-08-03"].map((time, i) => ({ time, value: 150 + i })),
    weinstein_ma_label: "EMA30", weinstein_stages: [],
  } as unknown as ChartOut;
  const { rerender } = render(<TickerChart data={data} {...props} showStage />);
  // The tags are the last close (105) and the MA at the last bar (154); ticks within 16px of either are blanked.
  expect(tickLabels(0, [100, 105, 154, 200])).toEqual(["", "", "", "200.00"]);
  rerender(<TickerChart data={data} {...props} showStage={false} />);
  expect(tickLabels(0, [100, 105, 154, 200])).toEqual(["", "", "154.00", "200.00"]); // MA hidden: its tag is gone
});

it("hide overlapping labels: LP levels are tags only while their LP toggle is on", () => {
  const base2h = twoHData();
  // Zones far from the candles (~100), so only the zone's own tag can hide a tick at its level.
  const data = { ...base2h, zones: [{ side: "support", price: 300, formed_at: base2h.bars[30].time, broken: false }] } as ChartOut;
  const { rerender } = render(<TickerChart data={data} {...props} />);
  expect(tickLabels(0, [300, 600])).toEqual(["", "600.00"]); // the support level is a tag while LP Support is on
  rerender(<TickerChart data={data} {...props} showLpSupport={false} />);
  expect(tickLabels(0, [300, 600])).toEqual(["300.00", "600.00"]);
});

// --- RSI line color ---

it("2H·90D: the Warren RSI line is one color (no red beyond 30/70); the daily RSI pane keeps its per-point red", () => {
  render(<TickerChart data={twoHData()} {...props} />);
  const rsi2h = allSeries.find((s) => s.getPane().paneIndex() === 1)!;
  expect(rsi2h.data().some((d) => "color" in d)).toBe(false);
  cleanup();
  allSeries = [];
  render(<TickerChart data={dailyData()} {...props} />);
  const rsiDaily = allSeries.find((s) => s.getPane().paneIndex() === 1)!;
  expect(rsiDaily.data().every((d) => "color" in d)).toBe(true);
});

// --- Arrow text ---

it("signal arrows carry no text, on 2H·90D and on the daily ranges (BB+RSI and Warren)", () => {
  const twoH = twoHData();
  render(<TickerChart data={twoH} {...props} />);
  expect(markerSets.flat().length).toBe(twoH.entry_signal_markers.length + twoH.warren_signal_markers.length);
  expect(markerSets.flat().every((m) => !("text" in m) && typeof m.shape === "string")).toBe(true);
  cleanup();
  markerSets = [];
  const daily = {
    ...dailyData(),
    entry_signal_markers: [{ time: "2026-07-13", label: "BB+RSI", kind: "bb_rsi" }],
    warren_signal_markers: [{ time: "2026-07-20", label: "Gray Down", kind: "gray_down" }],
  } as ChartOut;
  render(<TickerChart data={daily} {...props} />);
  expect(markerSets.flat()).toHaveLength(2);
  expect(markerSets.flat().every((m) => !("text" in m))).toBe(true);
});

// --- Warren action text (2H·90D legend second line) ---

const instruction = (over: Partial<NonNullable<ChartOut["warren_instruction"]>> = {}): ChartOut["warren_instruction"] => ({
  type: 2, kind: "blue_up", text: "BLUE UP = ENTRY, NO STOP", tone: "blue", time: "2026-08-10T09:30:00", bars_since: 3, bars_left: 27, ...over,
});

it("2H·90D legend: the Warren action text is a second line, prefixed and coloured by tone, wrapped not truncated", () => {
  const tones = { red: "text-chart-down", gray: "text-chart-warren-gray", yellow: "text-chart-warren-yellow", blue: "text-chart-ema21" } as const;
  for (const [tone, cls] of Object.entries(tones)) {
    const { getByTestId } = render(
      <TickerChart data={{ ...twoHData(), warren_instruction: instruction({ tone: tone as "red", text: `TEXT ${tone}` }) }} {...props} />
    );
    const line = getByTestId("warren-instruction");
    expect(line.textContent).toBe(`Warren: TEXT ${tone}`);
    expect(line.className).toContain(cls);
    expect(line.className).not.toMatch(/truncate|whitespace-nowrap|overflow-hidden/);
    // inside the pointer-events-none legend block, under the OHLC row
    expect(line.parentElement!.className).toContain("pointer-events-none");
    expect(line.previousElementSibling!.textContent).toMatch(/O .*H .*L .*C /);
    cleanup();
  }
});

it("2H·90D legend: no instruction renders nothing", () => {
  const { queryByTestId, container } = render(<TickerChart data={twoHData()} {...props} />);
  expect(queryByTestId("warren-instruction")).toBeNull();
  expect(container.textContent).not.toContain("Warren:");
});

it("2H·90D legend: the Warren toggle off hides the text, and on shows it again", () => {
  const data = { ...twoHData(), warren_instruction: instruction() };
  const { queryByTestId, rerender } = render(<TickerChart data={data} {...props} showWarren={false} />);
  expect(queryByTestId("warren-instruction")).toBeNull();
  rerender(<TickerChart data={data} {...props} showWarren />);
  expect(queryByTestId("warren-instruction")).not.toBeNull();
});

it("a daily range never shows the text, even if a response carried one", () => {
  const data = { ...dailyData(), warren_instruction: instruction() } as ChartOut;
  const { queryByTestId } = render(<TickerChart data={data} {...props} />);
  expect(queryByTestId("warren-instruction")).toBeNull();
});
