// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PeHistoryPanel } from "@/components/ticker/PeHistoryCard";
import type { PeHistoryOut } from "@/lib/api/types";
import { fmtPeMonth, peHeadline, peYRange } from "@/lib/peHistory";

// jsdom has no layout; give ResponsiveContainer a fixed size (same convention as PriceTargetTrendChart.test.tsx).
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) =>
      cloneElement(children, { width: 800, height: 216 }),
  };
});

afterEach(cleanup);

const LABEL = "average PE of listed companies (FMP)";

function payload(overrides: Partial<PeHistoryOut> = {}): PeHistoryOut {
  return {
    ticker: "ABC",
    status: "ok",
    note: null,
    label: LABEL,
    window_start: "2025-10-09",
    exchange: "NASDAQ",
    sector: "Technology",
    industry: "Software - Application",
    stock_status: "ok",
    stock_starts: "2025-10-10",
    sector_available: true,
    industry_available: true,
    industry_fallback: false,
    points: [
      { date: "2025-10-10", stock: 28, sector: 22, industry: 25 },
      { date: "2025-10-13", stock: 28.4, sector: 22.1, industry: 24.7 },
    ],
    latest_stock: { value: 28.4, date: "2025-10-13" },
    latest_sector: { value: 22.1, date: "2025-10-13" },
    latest_industry: { value: 24.7, date: "2025-10-13" },
    ...overrides,
  };
}

describe("PeHistoryPanel", () => {
  it("shows the headline, both switches off, and only the stock line to start", () => {
    render(<PeHistoryPanel data={payload()} />);
    expect(screen.getByText("Stock 28.4 · Sector 22.1 · Industry 24.7")).toBeTruthy();
    const sector = screen.getByRole("switch", { name: "Overlay sector PE" }) as HTMLInputElement;
    const industry = screen.getByRole("switch", { name: "Overlay industry PE" }) as HTMLInputElement;
    expect(sector.checked).toBe(false);
    expect(industry.checked).toBe(false);
    expect(screen.queryByText(new RegExp(`Technology: ${LABEL.replace(/[()]/g, "\\$&")}`))).toBeNull();
  });

  it("adds the sector line, labelled as FMP's average, when the switch is on", () => {
    render(<PeHistoryPanel data={payload()} />);
    fireEvent.click(screen.getByRole("switch", { name: "Overlay sector PE" }));
    expect(screen.getByText(`Technology: ${LABEL}`)).toBeTruthy();
    expect(screen.queryByText(`Software - Application: ${LABEL}`)).toBeNull();
  });

  it("never describes the gap as a premium or discount", () => {
    const { container } = render(<PeHistoryPanel data={payload()} />);
    expect(container.textContent?.toLowerCase()).not.toMatch(/premium|discount/);
  });

  it("reads n/a for a missing value", () => {
    render(<PeHistoryPanel data={payload({ latest_stock: null, stock_status: "no_eps" })} />);
    expect(screen.getByText("Stock n/a · Sector 22.1 · Industry 24.7")).toBeTruthy();
  });

  it("falls back to the sector line with a note when the industry series is missing", () => {
    render(
      <PeHistoryPanel
        data={payload({ industry: "Asset Management", industry_available: false, industry_fallback: true, latest_industry: null })}
      />
    );
    expect(screen.queryByRole("switch", { name: "Overlay industry PE" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Overlay sector PE" })).toBeTruthy();
    expect(screen.getByText(/No industry series for Asset Management on NASDAQ/)).toBeTruthy();
    expect(screen.getByText(/Industry n\/a/)).toBeTruthy();
  });

  it("shows the note and no chart or switches for an ETF", () => {
    render(<PeHistoryPanel data={payload({ status: "etf", note: "ETFs and funds have no P/E history.", points: [] })} />);
    expect(screen.getByText("ETFs and funds have no P/E history.")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("shows an empty state for a ticker with no usable EPS and turns the overlays on so the chart is not blank", () => {
    render(<PeHistoryPanel data={payload({ stock_status: "no_eps", stock_starts: null, latest_stock: null })} />);
    expect(screen.getByText(/No stock P\/E line: trailing diluted EPS is zero or negative/)).toBeTruthy();
    expect((screen.getByRole("switch", { name: "Overlay sector PE" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("img")).toBeTruthy();
  });

  it("explains the missing stock line for an ADR and keeps the overlays", () => {
    render(<PeHistoryPanel data={payload({ stock_status: "adr", stock_starts: null, latest_stock: null })} />);
    expect(screen.getByText(/reports in a different currency/)).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Overlay industry PE" })).toBeTruthy();
  });

  it("marks where the stock P/E starts when it begins after the window", () => {
    render(<PeHistoryPanel data={payload({ stock_starts: "2025-10-13" })} />);
    expect(screen.getByText("Stock P/E starts →")).toBeTruthy();
  });

  it("draws no start marker when the stock line begins with the window", () => {
    render(<PeHistoryPanel data={payload()} />);
    expect(screen.queryByText("Stock P/E starts →")).toBeNull();
  });
});

describe("peYRange", () => {
  it("keeps the whole range when there are no outliers", () => {
    const r = peYRange([10, 12, 14, 16, 18, 20]);
    expect(r.clippedCount).toBe(0);
    expect(r.domain[0]).toBe(0);
    expect(r.domain[1]).toBeGreaterThanOrEqual(20);
  });

  it("clips outlier days above 1.15 x the 95th percentile and counts them", () => {
    const values = [...Array.from({ length: 98 }, () => 20), 400, 500];
    const r = peYRange(values);
    expect(r.domain[1]).toBeLessThan(100);
    expect(r.clippedCount).toBe(2);
  });

  it("copes with no values", () => {
    expect(peYRange([]).domain).toEqual([0, 1]);
  });
});

describe("formatters", () => {
  it("builds the headline and the axis month", () => {
    expect(peHeadline({ value: 28.44, date: "x" }, null, { value: 24.7, date: "x" })).toBe("Stock 28.4 · Sector n/a · Industry 24.7");
    expect(fmtPeMonth("2026-03-14")).toBe("Mar 26");
  });
});
