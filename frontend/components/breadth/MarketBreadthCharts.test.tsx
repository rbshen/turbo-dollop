// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

// A daily series (weekends included -- only the ordering matters) of `n` rows ending 2026-09-24, so the
// trailing-year window is 366 rows when n > 366.
function longSeries(n: number): MarketBreadthPointOut[] {
  const end = Date.UTC(2026, 8, 24);
  return Array.from({ length: n }, (_, i) =>
    point(new Date(end - (n - 1 - i) * 86_400_000).toISOString().slice(0, 10), { net_new_highs: i % 2 ? 3 : -3 })
  );
}

function netPanel(): HTMLElement {
  return screen.getByRole("img", { name: /Net new 52-week highs/ });
}
const bars = () => netPanel().querySelectorAll(".recharts-bar-rectangle").length;
const ticks = (el: HTMLElement) => Array.from(el.querySelectorAll(".recharts-xAxis .recharts-cartesian-axis-tick-value")).map((t) => t.textContent);
const windowOf = (c: HTMLElement) => (c.firstElementChild as HTMLElement).dataset.window!;

function renderPannable(n: number) {
  const { container } = render(<MarketBreadthCharts series={longSeries(n)} />);
  const root = container.firstElementChild as HTMLElement;
  root.getBoundingClientRect = () => ({ width: 800, height: 500, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 500, toJSON() {} });
  return { container, root };
}
const drag = (root: HTMLElement, dx: number) => {
  fireEvent.pointerDown(root, { clientX: 400, button: 0, pointerId: 1 });
  fireEvent.pointerMove(root, { clientX: 400 + dx, pointerId: 1 });
  fireEvent.pointerUp(root, { pointerId: 1 });
};

// 366-bar charts re-render on every pointer move under jsdom, so these are slow.
vi.setConfig({ testTimeout: 30_000 });

describe("MarketBreadthCharts drag-to-pan", () => {
  it("opens on the trailing year and the bar panel draws a bar for every visible row (the empty-panel regression)", () => {
    const { container } = renderPannable(800);
    const [first, last] = windowOf(container).split("..");
    expect(last).toBe("2026-09-24");
    expect(first).toBe("2025-09-24");
    expect(bars()).toBe(366);
  });

  it("drag left pans to older rows, drag right pans back; both panels stay on the same slice", () => {
    const { container, root } = renderPannable(800);
    const before = windowOf(container);
    drag(root, -400); // 400px at 800px / 366 rows ~ 183 rows older
    const older = windowOf(container);
    expect(older).not.toBe(before);
    expect(older.split("..")[1] < before.split("..")[1]).toBe(true);
    expect(bars()).toBe(366);
    expect(ticks(netPanel())).toEqual(ticks(linePanel()));
    drag(root, 400);
    expect(windowOf(container)).toBe(before);
  });

  it("clamps at the oldest stored session and at now", () => {
    const { container, root } = renderPannable(800);
    drag(root, -100_000);
    expect(windowOf(container).split("..")[0]).toBe(longSeries(800)[0].as_of_date);
    expect(bars()).toBe(366);
    drag(root, 100_000);
    expect(windowOf(container).split("..")[1]).toBe("2026-09-24");
    expect(bars()).toBe(366);
  });

  it("a short-history universe shows everything and has nothing to pan", () => {
    const { container, root } = renderPannable(154);
    const before = windowOf(container);
    expect(bars()).toBe(154);
    drag(root, -500);
    drag(root, 500);
    expect(windowOf(container)).toBe(before);
    expect(bars()).toBe(154);
  });

  it("a background refresh that appends a session keeps an in-progress pan; a new universe resets", () => {
    const s = longSeries(800);
    const { container, rerender } = render(<MarketBreadthCharts series={s} />);
    const root = container.firstElementChild as HTMLElement;
    root.getBoundingClientRect = () => ({ width: 800, height: 500, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 500, toJSON() {} });
    drag(root, -400);
    const panned = windowOf(container);
    rerender(<MarketBreadthCharts series={[...s, point("2026-09-25")]} />);
    expect(windowOf(container).split("..")[0]).toBe(panned.split("..")[0]);
    rerender(<MarketBreadthCharts series={longSeries(500).map((p) => ({ ...p, as_of_date: p.as_of_date.replace("2026", "2027") }))} />);
    expect(windowOf(container).split("..")[1]).toBe("2027-09-24");
  });
});

