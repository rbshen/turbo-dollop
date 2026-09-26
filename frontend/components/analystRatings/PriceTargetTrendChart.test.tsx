// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PriceTargetTrendChart } from "@/components/analystRatings/PriceTargetTrendChart";
import type { RatingHistoryPoint } from "@/lib/api/types";

// jsdom has no layout, so ResponsiveContainer would render a 0x0 chart with no lines. Give it a fixed size --
// same convention as MarketBreadthCharts.test.tsx.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) =>
      cloneElement(children, { width: 800, height: 216 }),
  };
});

afterEach(cleanup);

function point(date: string, overrides: Partial<RatingHistoryPoint> = {}): RatingHistoryPoint {
  return {
    date,
    buy_pct: 20,
    outperform_pct: 20,
    hold_pct: 20,
    underperform_pct: 20,
    sell_pct: 20,
    avg_rating: 3,
    avg_price_target: null,
    price_on_date: null,
    ...overrides,
  };
}

const HISTORY_NO_TARGETS: RatingHistoryPoint[] = [point("2024-01-05"), point("2024-06-10")];

const HISTORY_FULL_OVERLAP: RatingHistoryPoint[] = [
  point("2024-01-01", { avg_price_target: 100, price_on_date: 95 }),
  point("2024-06-01", { avg_price_target: 110, price_on_date: 108 }),
  point("2024-12-01", { avg_price_target: 120, price_on_date: 118 }),
];

const HISTORY_ZERO_OVERLAP: RatingHistoryPoint[] = [
  point("2024-01-01", { avg_price_target: 100, price_on_date: null }),
  point("2024-06-01", { avg_price_target: 110, price_on_date: null }),
];

const HISTORY_TRUNCATED: RatingHistoryPoint[] = [
  point("2024-01-01", { avg_price_target: 100, price_on_date: null }), // target's own first point, no price yet
  point("2024-06-01", { avg_price_target: 110, price_on_date: null }),
  point("2024-12-01", { avg_price_target: 120, price_on_date: 118 }), // price data first appears here
];

function chartPanel(): HTMLElement {
  return screen.getByRole("img");
}

describe("PriceTargetTrendChart", () => {
  it("shows the accumulating-history message and no toggle when there's no target data at all", () => {
    render(<PriceTargetTrendChart history={HISTORY_NO_TARGETS} />);
    expect(screen.getByText(/hasn't accumulated yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Overlay stock price" })).not.toBeInTheDocument();
  });

  it("renders the plain single-series chart with no toggle when there's zero overlap with price data", () => {
    render(<PriceTargetTrendChart history={HISTORY_ZERO_OVERLAP} />);
    expect(screen.queryByRole("button", { name: "Overlay stock price" })).not.toBeInTheDocument();
    expect(chartPanel().querySelectorAll("path.recharts-line-curve, path.recharts-area-area")).toHaveLength(1);
  });

  it("defaults to the single-series view (toggle present but off) when overlap exists", () => {
    render(<PriceTargetTrendChart history={HISTORY_FULL_OVERLAP} />);
    const toggle = screen.getByRole("button", { name: "Overlay stock price" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    // The default RechartsAreaChart renders an Area, not a Line -- still one series.
    expect(chartPanel().querySelectorAll("path.recharts-area-area")).toHaveLength(1);
  });

  it("switches to a two-line comparison, correctly colored, with a legend, when the toggle is switched on", () => {
    render(<PriceTargetTrendChart history={HISTORY_FULL_OVERLAP} />);
    fireEvent.click(screen.getByRole("button", { name: "Overlay stock price" }));

    const strokes = Array.from(chartPanel().querySelectorAll("path.recharts-line-curve")).map((el) => el.getAttribute("stroke"));
    expect(strokes).toEqual(["var(--color-brand)", "var(--color-chart-1)"]);

    expect(screen.getByText("Avg. Price Target")).toBeInTheDocument();
    expect(screen.getByText("Stock Price")).toBeInTheDocument();
  });

  it("does not draw a truncation marker when the price line already starts at the target line's own first point", () => {
    render(<PriceTargetTrendChart history={HISTORY_FULL_OVERLAP} />);
    fireEvent.click(screen.getByRole("button", { name: "Overlay stock price" }));
    expect(screen.queryByText("Price data starts →")).not.toBeInTheDocument();
  });

  it("draws a dashed marker labeling where the price line actually starts when it starts later than the target line", () => {
    render(<PriceTargetTrendChart history={HISTORY_TRUNCATED} />);
    fireEvent.click(screen.getByRole("button", { name: "Overlay stock price" }));

    expect(screen.getByText("Price data starts →")).toBeInTheDocument();
    const dashed = Array.from(chartPanel().querySelectorAll("line")).filter((el) => el.getAttribute("stroke-dasharray") === "2 3");
    expect(dashed.length).toBeGreaterThan(0);
  });

  it("toggling back off returns to the exact original single-series view", () => {
    render(<PriceTargetTrendChart history={HISTORY_FULL_OVERLAP} />);
    const toggle = screen.getByRole("button", { name: "Overlay stock price" });
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(chartPanel().querySelectorAll("path.recharts-area-area")).toHaveLength(1);
    expect(chartPanel().querySelectorAll("path.recharts-line-curve")).toHaveLength(0);
  });
});
