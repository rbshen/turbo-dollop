// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MarketBreadthCharts } from "@/components/breadth/MarketBreadthCharts";
import type { MarketBreadthPointOut } from "@/lib/api/types";

// jsdom has no layout, so ResponsiveContainer would render a 0x0 chart with no lines. Give it a fixed size.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) =>
      cloneElement(children, { width: 800, height: 240 }),
  };
});

afterEach(cleanup);

const point = (as_of_date: string, overrides: Partial<MarketBreadthPointOut> = {}): MarketBreadthPointOut => ({
  as_of_date, pct_above_sma20: 18, pct_above_sma50: 28, pct_above_sma200: 49, sma20_above: 90, sma50_above: 140, sma200_above: 247,
  new_highs: 5, new_lows: 29, net_new_highs: -24, constituents: 503, stale_excluded: 0, sma20_eligible: 503, sma50_eligible: 503,
  sma200_eligible: 501, hl_eligible: 500, is_backfilled: true, ...overrides,
});

const SERIES = ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"].map((d, i) =>
  point(d, { pct_above_sma20: 10 + i * 10, pct_above_sma50: 30 + i, pct_above_sma200: 50 - i })
);

function linePanel(): HTMLElement {
  return screen.getByRole("img", { name: /moving averages over time/ });
}

describe("MarketBreadthCharts", () => {
  it("draws three lines -- 20-day, 50-day, 200-day -- each in its own color", () => {
    render(<MarketBreadthCharts series={SERIES} />);
    const strokes = Array.from(linePanel().querySelectorAll("path.recharts-line-curve")).map((el) => el.getAttribute("stroke"));
    expect(strokes).toHaveLength(3);
    // Drawn slowest-first so the fastest, most volatile line sits on top.
    expect(strokes).toEqual(["var(--color-chart-2)", "var(--color-chart-4)", "var(--color-chart-1)"]);
    expect(new Set(strokes).size).toBe(3);
  });

  it("lists all three series in the legend, 20-day first, and names them in the panel subtitle", () => {
    render(<MarketBreadthCharts series={SERIES} />);
    const legend = ["Above 20-day SMA", "Above 50-day SMA", "Above 200-day SMA"].map((name) => screen.getByText(name));
    // Document order == 20, 50, 200.
    legend.slice(1).forEach((el, i) => expect(legend[i].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy());
    expect(screen.getByText(/20-, 50- and 200-day SMA/)).toBeInTheDocument();
  });

  it("keeps the dashed 50% reference line and the 0-100% axis ticks", () => {
    render(<MarketBreadthCharts series={SERIES} />);
    const panel = linePanel();
    const dashed = Array.from(panel.querySelectorAll("line")).filter((el) => el.getAttribute("stroke-dasharray") === "4 4");
    expect(dashed).toHaveLength(1);
    ["0%", "25%", "50%", "75%", "100%"].forEach((tick) => expect(panel.textContent).toContain(tick));
  });

  it("still renders the net-new-highs panel", () => {
    render(<MarketBreadthCharts series={SERIES} />);
    expect(screen.getByRole("img", { name: /Net new 52-week highs/ })).toBeInTheDocument();
  });

  it("renders when older rows have no 20-day reading yet (a gap, not a crash)", () => {
    const series = [
      point("2026-09-15", { pct_above_sma20: null, sma20_above: null, sma20_eligible: null }),
      ...SERIES.slice(1),
    ];
    render(<MarketBreadthCharts series={series} />);
    expect(linePanel().querySelectorAll("path.recharts-line-curve")).toHaveLength(3);
  });
});
