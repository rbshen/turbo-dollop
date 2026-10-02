// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChartTab } from "@/components/ticker/ChartTab";
import type { ZoomBounds } from "@/components/chart/TickerChart";

// The chart itself (lightweight-charts) is replaced by a probe that records the props ChartTab hands it, so each
// control is pinned by what it changes: the range requested from the hook and the show*/zoom props of the chart.
type ChartProps = Record<string, unknown> & { onZoomBoundsChange: (b: ZoomBounds) => void };
let chartProps: ChartProps;
const chartRanges: string[] = [];
let chartData: { chart_available: boolean } | undefined;
// Optional per-range override of what the hook returns (so a test can make one range unavailable).
const chartDataByRange: Record<string, { chart_available: boolean }> = {};

vi.mock("@/components/chart/TickerChart", () => ({
  TickerChart: (props: ChartProps) => {
    chartProps = props;
    return <div data-testid="chart" />;
  },
}));
vi.mock("@/lib/hooks/useTickerChart", () => ({
  useTickerChart: (_ticker: string, range: string) => {
    chartRanges.push(range);
    return { data: chartDataByRange[range] ?? chartData, error: undefined, isLoading: false };
  },
}));
vi.mock("@/lib/hooks/useTickerSummary", () => ({ useTickerSummary: () => ({ data: { quote_currency: "USD" } }) }));

const STORAGE_KEY = "fathom-chart-signal-toggles";

// label -> the TickerChart prop it drives
const TOGGLES: [string, string][] = [
  ["BB+RSI", "showBbRsi"],
  ["Warren", "showWarren"],
  ["Earnings", "showEarnings"],
  ["Dividends", "showDividends"],
  ["LP Support", "showLpSupport"],
  ["LP Resistance", "showLpResistance"],
  ["BB", "showBollinger"],
  ["EMA 21", "showEma21"],
  ["SMA 50", "showSma50"],
  ["SMA 200", "showSma200"],
];

beforeEach(() => {
  window.localStorage.clear();
  chartRanges.length = 0;
  chartData = { chart_available: true };
  for (const k of Object.keys(chartDataByRange)) delete chartDataByRange[k];
});
afterEach(cleanup);

// How a toggle or a range segment shows that it is on: aria-pressed (the range buttons had none before the
// migration and drew a surface-2 fill instead).
function isOn(btn: HTMLElement): boolean {
  return btn.getAttribute("aria-pressed") === "true";
}

function btn(name: string) {
  return screen.getByRole("button", { name });
}

describe("ChartTab: the range buttons", () => {
  it("offers the five ranges, 2H · 90D leftmost, and starts on D · 6M", () => {
    render(<ChartTab ticker="AAPL" />);
    const group = screen.getByRole("group", { name: "Chart range" });
    const labels = Array.from(group.querySelectorAll("button")).map((b) => b.textContent);
    expect(labels).toEqual(["2H · 90D", "D · 6M", "D · 1Y", "D · 2Y", "W · 4Y"]);
    expect(chartRanges[0]).toBe("D_6M");
    expect(isOn(btn("D · 6M"))).toBe(true);
    expect(isOn(btn("2H · 90D"))).toBe(false);
  });

  it("requests the 2H range from the chart hook when 2H · 90D is clicked", () => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("2H · 90D"));
    expect(chartRanges.at(-1)).toBe("2H_90D");
    expect(isOn(btn("2H · 90D"))).toBe(true);
  });

  it("is one segmented group named 'Chart range', with the selected range pressed", () => {
    render(<ChartTab ticker="AAPL" />);
    expect(screen.getByRole("group", { name: "Chart range" })).toBeInTheDocument();
    expect(isOn(btn("D · 6M"))).toBe(true);
    expect(isOn(btn("D · 1Y"))).toBe(false);
    fireEvent.click(btn("D · 1Y"));
    expect(isOn(btn("D · 1Y"))).toBe(true);
    expect(isOn(btn("D · 6M"))).toBe(false);
    expect(btn("D · 1Y")).toHaveClass("data-[pressed]:bg-surface-2");
  });

  it("requests the clicked range from the chart hook", () => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("D · 2Y"));
    expect(chartRanges.at(-1)).toBe("D_2Y");
    fireEvent.click(btn("W · 4Y"));
    expect(chartRanges.at(-1)).toBe("W_4Y");
    fireEvent.click(btn("D · 6M"));
    expect(chartRanges.at(-1)).toBe("D_6M");
  });

  it("clicking the range that is already selected keeps it selected", () => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("D · 1Y"));
    fireEvent.click(btn("D · 1Y"));
    expect(chartRanges.at(-1)).toBe("D_1Y");
    expect(isOn(btn("D · 1Y"))).toBe(true);
  });

  it("clicking the selected range no longer resets the zoom (the kit control ignores a re-click; the old button reset it)", () => {
    render(<ChartTab ticker="AAPL" />);
    act(() => chartProps.onZoomBoundsChange({ canZoomIn: true, canZoomOut: true }));
    fireEvent.click(btn("Zoom in"));
    fireEvent.click(btn("D · 6M"));
    expect(chartProps.zoomIndex).toBe(1);
  });

  it("starts the zoom over when the range changes", () => {
    render(<ChartTab ticker="AAPL" />);
    act(() => chartProps.onZoomBoundsChange({ canZoomIn: true, canZoomOut: true }));
    fireEvent.click(btn("Zoom in"));
    expect(chartProps.zoomIndex).toBe(1);
    fireEvent.click(btn("D · 1Y"));
    expect(chartProps.zoomIndex).toBe(0);
  });
});

describe("ChartTab: the overlay toggles", () => {
  it("draws each toggle as an outline Button, neutral when on, and never brand blue", () => {
    render(<ChartTab ticker="AAPL" />);
    const on = btn("Warren");
    expect(on).toHaveClass("border", "border-border-input", "h-8", "bg-surface-2", "text-text-primary");
    expect(on.className).not.toMatch(/bg-brand|text-brand/);
    fireEvent.click(on);
    expect(btn("Warren")).not.toHaveClass("bg-surface-2");
    expect(btn("Warren")).toHaveClass("text-text-secondary");
  });

  it("shows ten toggles at the daily ranges, all on", () => {
    render(<ChartTab ticker="AAPL" />);
    for (const [label, prop] of TOGGLES) {
      expect(isOn(btn(label))).toBe(true);
      expect(chartProps[prop]).toBe(true);
    }
    expect(screen.queryByRole("button", { name: "Stage" })).not.toBeInTheDocument();
    expect(chartProps.showStage).toBe(false);
  });

  it.each(TOGGLES)("%s flips its own overlay and no other", (label, prop) => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn(label));
    expect(isOn(btn(label))).toBe(false);
    expect(chartProps[prop]).toBe(false);
    for (const [other, otherProp] of TOGGLES) {
      if (other !== label) expect(chartProps[otherProp]).toBe(true);
    }
    fireEvent.click(btn(label));
    expect(isOn(btn(label))).toBe(true);
    expect(chartProps[prop]).toBe(true);
  });

  it("offers Stage only on the weekly range, off by default, and drives showStage there", () => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("W · 4Y"));
    expect(isOn(btn("Stage"))).toBe(false);
    expect(chartProps.showStage).toBe(false);
    fireEvent.click(btn("Stage"));
    expect(isOn(btn("Stage"))).toBe(true);
    expect(chartProps.showStage).toBe(true);
    fireEvent.click(btn("D · 1Y"));
    expect(screen.queryByRole("button", { name: "Stage" })).not.toBeInTheDocument();
    expect(chartProps.showStage).toBe(false); // remembered as on, but never applied off the weekly view
    fireEvent.click(btn("W · 4Y"));
    expect(isOn(btn("Stage"))).toBe(true);
  });

  it("saves every change to localStorage under one key", () => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("Warren"));
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(saved.warren).toBe(false);
    expect(saved.bbRsi).toBe(true);
    expect(saved.stage).toBe(false);
  });

  it("restores a saved state on mount, and ignores values that are not booleans", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ bbRsi: false, ema21: "no", stage: true }));
    render(<ChartTab ticker="AAPL" />);
    expect(isOn(btn("BB+RSI"))).toBe(false);
    expect(chartProps.showBbRsi).toBe(false);
    expect(isOn(btn("EMA 21"))).toBe(true); // "no" is not a boolean, so the default (on) stands
  });

  it("falls back to the defaults when the saved text is not JSON", () => {
    window.localStorage.setItem(STORAGE_KEY, "{nope");
    render(<ChartTab ticker="AAPL" />);
    expect(TOGGLES.every(([label]) => isOn(btn(label)))).toBe(true);
  });
});

describe("ChartTab: zoom and states", () => {
  it("disables Zoom out until the chart reports room, and steps the index on each click", () => {
    render(<ChartTab ticker="AAPL" />);
    expect(btn("Zoom out")).toBeDisabled();
    expect(btn("Zoom in")).toBeEnabled();
    act(() => chartProps.onZoomBoundsChange({ canZoomIn: true, canZoomOut: true }));
    fireEvent.click(btn("Zoom in"));
    fireEvent.click(btn("Zoom in"));
    expect(chartProps.zoomIndex).toBe(2);
    fireEvent.click(btn("Zoom out"));
    expect(chartProps.zoomIndex).toBe(1);
  });

  it("draws Zoom in and Zoom out as outline sm Buttons with their words, matching the toggles beside them", () => {
    render(<ChartTab ticker="AAPL" />);
    for (const name of ["Zoom in", "Zoom out"]) {
      expect(btn(name)).toHaveClass("border", "border-border-input", "h-8", "text-xs");
      expect(btn(name)).toHaveAttribute("type", "button");
    }
    expect(btn("Zoom out")).toHaveClass("disabled:opacity-45");
  });

  it("disables Zoom in when the chart says it cannot zoom further", () => {
    render(<ChartTab ticker="AAPL" />);
    act(() => chartProps.onZoomBoundsChange({ canZoomIn: false, canZoomOut: true }));
    expect(btn("Zoom in")).toBeDisabled();
  });

  it("says so when there is no chart for the ticker", () => {
    chartData = { chart_available: false };
    render(<ChartTab ticker="AAPL" />);
    expect(screen.getByText("No chart data available for AAPL.")).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });
});

describe("ChartTab: on an ETF page", () => {
  it("hides the Earnings toggle (a fund has no earnings) and forces the overlay off, keeping every other toggle", () => {
    render(<ChartTab ticker="QQQ" isEtf />);
    expect(screen.queryByRole("button", { name: "Earnings" })).not.toBeInTheDocument();
    expect(chartProps.showEarnings).toBe(false);
    for (const [label, prop] of TOGGLES.filter(([l]) => l !== "Earnings")) {
      expect(btn(label)).toBeInTheDocument();
      expect(chartProps[prop]).toBe(true);
    }
  });

  it("a stock keeps the Earnings toggle, on by default", () => {
    render(<ChartTab ticker="AAPL" />);
    expect(isOn(btn("Earnings"))).toBe(true);
    expect(chartProps.showEarnings).toBe(true);
  });
});


describe("ChartTab: the 2H · 90D range", () => {
  const OFFERED = ["BB+RSI", "Warren", "LP Support", "LP Resistance"];
  const HIDDEN: [string, string][] = [
    ["Earnings", "showEarnings"],
    ["Dividends", "showDividends"],
    ["BB", "showBollinger"],
    ["EMA 21", "showEma21"],
    ["SMA 50", "showSma50"],
    ["SMA 200", "showSma200"],
  ];

  it("shows only BB+RSI, Warren, LP Support and LP Resistance, all on by default", () => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("2H · 90D"));
    for (const label of OFFERED) expect(isOn(btn(label))).toBe(true);
    for (const [label] of HIDDEN) expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stage" })).not.toBeInTheDocument();
    expect(chartProps).toMatchObject({ showBbRsi: true, showWarren: true, showLpSupport: true, showLpResistance: true });
  });

  it("forces every hidden overlay off in what the chart is told, even when saved on", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ stage: true }));
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("2H · 90D"));
    for (const [, prop] of HIDDEN) expect(chartProps[prop]).toBe(false);
    expect(chartProps.showStage).toBe(false);
  });

  it("never overwrites saved values for the hidden toggles, and switching back restores them", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ema21: false, sma200: false, bollinger: true }));
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("2H · 90D"));
    fireEvent.click(btn("Warren")); // writes the whole object: the hidden values must ride along untouched
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(saved).toMatchObject({ warren: false, ema21: false, sma200: false, bollinger: true });
    fireEvent.click(btn("D · 6M"));
    expect(isOn(btn("EMA 21"))).toBe(false);
    expect(isOn(btn("SMA 200"))).toBe(false);
    expect(isOn(btn("BB"))).toBe(true);
    expect(chartProps).toMatchObject({ showEma21: false, showSma200: false, showBollinger: true, showWarren: false });
  });

  it("an offered toggle still flips only its own overlay", () => {
    render(<ChartTab ticker="AAPL" />);
    fireEvent.click(btn("2H · 90D"));
    fireEvent.click(btn("LP Support"));
    expect(chartProps).toMatchObject({ showLpSupport: false, showLpResistance: true, showBbRsi: true, showWarren: true });
  });

  it("shows no descriptive text under the Chart heading, on any range", () => {
    render(<ChartTab ticker="AAPL" />);
    expect(screen.getByRole("heading", { name: "Chart" })).toBeInTheDocument();
    expect(screen.queryByText(/Bollinger Bands/)).not.toBeInTheDocument();
    fireEvent.click(btn("2H · 90D"));
    expect(screen.queryByText(/2-hour candles/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Informational only/)).not.toBeInTheDocument();
  });

  it("an unavailable 2H chart shows the unavailable state, keeps every range button, and disables zoom", () => {
    chartDataByRange["2H_90D"] = { chart_available: false };
    render(<ChartTab ticker="9988.HK" />);
    fireEvent.click(btn("2H · 90D"));
    expect(screen.getByText("No chart data available for 9988.HK.")).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
    for (const label of ["2H · 90D", "D · 6M", "D · 1Y", "D · 2Y", "W · 4Y"]) expect(btn(label)).toBeInTheDocument();
    expect(btn("Zoom in")).toBeDisabled();
    expect(btn("Zoom out")).toBeDisabled();
  });

  it("switching from an unavailable 2H view to another range recovers cleanly (chart back, zoom usable, bounds reset)", () => {
    chartDataByRange["2H_90D"] = { chart_available: false };
    render(<ChartTab ticker="9988.HK" />);
    fireEvent.click(btn("2H · 90D"));
    fireEvent.click(btn("D · 1Y"));
    expect(screen.queryByText(/No chart data available/)).not.toBeInTheDocument();
    expect(screen.getByTestId("chart")).toBeInTheDocument();
    expect(btn("Zoom in")).toBeEnabled();
    expect(btn("Zoom out")).toBeDisabled(); // fresh bounds: nothing to zoom out of yet
    expect(chartProps.zoomIndex).toBe(0);
    fireEvent.click(btn("2H · 90D")); // and back again
    expect(screen.getByText(/No chart data available/)).toBeInTheDocument();
  });

  it("the ETF Earnings guard is unaffected on the daily ranges while 2H hides it for everyone", () => {
    render(<ChartTab ticker="QQQ" isEtf />);
    expect(screen.queryByRole("button", { name: "Earnings" })).not.toBeInTheDocument();
    fireEvent.click(btn("2H · 90D"));
    expect(chartProps.showEarnings).toBe(false);
    expect(OFFERED.every((l) => isOn(btn(l)))).toBe(true);
  });
});
