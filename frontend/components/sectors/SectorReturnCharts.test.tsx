// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SectorReturnCharts } from "@/components/sectors/SectorReturnCharts";
import type { SectorHeatmapRowOut } from "@/lib/api/types";
import { ZERO_MAX, ZERO_MIN } from "@/lib/sectorReturns";

afterEach(cleanup);

const WINDOWS = ["1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y"];

function makeRow(ticker: string, byWindow: Record<string, number | null>): SectorHeatmapRowOut {
  return {
    ticker,
    name: ticker,
    cells: Object.fromEntries(WINDOWS.map((w) => [w, { return_pct: byWindow[w] ?? null, base_date: byWindow[w] == null ? null : "2025-12-31" }])),
  };
}

// 1d small mixed; 1w all positive; 1m mixed, mostly negative; 3m all negative; 6m all n/a; 9m all zero; ytd positive-heavy; 1y wide mixed.
const ROWS = [
  makeRow("XLK", { "1d": -0.4, "1w": 2, "1m": -9, "3m": -3, "9m": 0, ytd: 25, "1y": 40 }),
  makeRow("XLE", { "1d": 1.8, "1w": 4, "1m": 1, "3m": -1, "9m": 0, ytd: -2, "1y": -12 }),
  makeRow("XLC", { "1d": 0.7, "1w": 1, "1m": -2, "3m": -8, "9m": 0, ytd: 10, "1y": null }),
];

const charts = () => screen.getAllByRole("region");
const zeroLefts = () => charts().map((c) => parseFloat(within(c).getAllByTestId("zero-line")[0].style.left));
const choose = (n: number, w: string) => fireEvent.change(screen.getByLabelText(`Return window, chart ${n}`), { target: { value: w } });
const ticksOf = (chart: HTMLElement) => Array.from(within(chart).getByTestId("axis").querySelectorAll("[data-tick]")).map((el) => Number(el.getAttribute("data-tick")));
const barsOf = (chart: HTMLElement) => within(chart).queryAllByRole("img");

function expectAligned() {
  const [a, b, c] = zeroLefts();
  expect(b).toBeCloseTo(a, 9);
  expect(c).toBeCloseTo(a, 9);
  expect(a).toBeGreaterThanOrEqual(ZERO_MIN * 100 - 1e-9);
  expect(a).toBeLessThanOrEqual(ZERO_MAX * 100 + 1e-9);
  return a;
}

describe("SectorReturnCharts: shared zero", () => {
  it("aligns the zero line across the three charts by default (mixed-sign + all-positive + mixed)", () => {
    render(<SectorReturnCharts rows={ROWS} />);
    expectAligned();
  });

  const COMBOS: Array<[string, string, string]> = [
    ["1d", "1w", "1m"],
    ["1w", "1w", "1w"], // all positive
    ["3m", "3m", "3m"], // all negative
    ["6m", "1d", "1y"], // an all-n/a chart
    ["9m", "9m", "9m"], // all zero
    ["6m", "6m", "6m"], // nothing at all
    ["ytd", "3m", "1y"],
  ];
  it.each(COMBOS)("keeps one zero position for %s / %s / %s, with no NaN", (w1, w2, w3) => {
    render(<SectorReturnCharts rows={ROWS} />);
    choose(1, w1);
    choose(2, w2);
    choose(3, w3);
    expectAligned();
    for (const chart of charts()) {
      expect(chart.innerHTML).not.toMatch(/NaN|Infinity/);
    }
  });

  it("re-aligns all three charts when any dropdown changes", () => {
    render(<SectorReturnCharts rows={ROWS} />);
    [1, 2, 3].forEach((n) => choose(n, "1y")); // L=12, R=40 -> zero at 12/52
    const before = expectAligned();
    expect(before).toBeCloseTo((12 / 52) * 100, 6);
    choose(2, "3m"); // all negative (L=8, R=0) -> fraction 1 -> clamped: zero jumps right in all three
    const after = expectAligned();
    expect(after).toBeCloseTo(ZERO_MAX * 100, 6);
    choose(2, "1y"); // back
    expect(expectAligned()).toBeCloseTo(before, 9);
  });

  it("clamps the shared zero inside 12%-88% for all-positive and all-negative data", () => {
    render(<SectorReturnCharts rows={ROWS} />);
    for (const w of ["1w"]) [1, 2, 3].forEach((n) => choose(n, w));
    expect(expectAligned()).toBeCloseTo(ZERO_MIN * 100, 6);
    [1, 2, 3].forEach((n) => choose(n, "3m"));
    expect(expectAligned()).toBeCloseTo(ZERO_MAX * 100, 6);
  });
});

describe("SectorReturnCharts: per-chart scale", () => {
  it("fits each chart's own range: a small chart gets a tight axis next to a wide one, zero unchanged", () => {
    render(<SectorReturnCharts rows={ROWS} />);
    choose(3, "1y");
    const [small, , wide] = charts().map(ticksOf);
    expect(Math.max(...small)).toBeLessThan(5);
    expect(Math.max(...wide)).toBeGreaterThanOrEqual(30);
    expectAligned();
  });

  it("draws every bar and its end inside the plot (no clipping), on both sides of zero", () => {
    render(<SectorReturnCharts rows={ROWS} />);
    for (const w of ["1d", "1m", "1y", "ytd", "3m"]) {
      choose(1, w);
      choose(2, w);
      choose(3, w);
      for (const chart of charts()) {
        for (const bar of barsOf(chart)) {
          const left = parseFloat(bar.style.left);
          const right = left + parseFloat(bar.style.width);
          expect(left).toBeGreaterThanOrEqual(0);
          expect(right).toBeLessThanOrEqual(100);
        }
      }
    }
  });

  it("gives round ticks on both sides of zero when the data is mixed", () => {
    render(<SectorReturnCharts rows={ROWS} />);
    [1, 2, 3].forEach((n) => choose(n, "1y"));
    const ticks = ticksOf(charts()[0]);
    expect(ticks).toContain(0);
    expect(ticks.some((t) => t < 0)).toBe(true);
    expect(ticks.some((t) => t > 0)).toBe(true);
  });
});

describe("SectorReturnCharts: shared layout", () => {
  it("renders every chart with the identical column and gutter classes", () => {
    const { container } = render(<SectorReturnCharts rows={ROWS} />);
    const grids = Array.from(container.querySelectorAll("li")).map((li) => li.className);
    expect(new Set(grids).size).toBe(1);
    const axes = Array.from(container.querySelectorAll("[data-testid='axis']")).map((el) => el.className);
    expect(new Set(axes).size).toBe(1);
    const gutters = Array.from(container.querySelectorAll("[data-testid='zero-line']")).map((el) => el.parentElement?.className);
    expect(new Set(gutters).size).toBe(1);
    expect(gutters[0]).toMatch(/mx-\[4\.5rem\]/); // room on BOTH sides for end labels
  });
});
