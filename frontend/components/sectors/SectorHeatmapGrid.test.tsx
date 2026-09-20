// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SectorHeatmapGrid } from "@/components/sectors/SectorHeatmapGrid";
import type { SectorHeatmapOut } from "@/lib/api/types";

afterEach(cleanup);

const WINDOWS = ["1w", "1m", "3m", "6m", "9m", "ytd", "1y"];

function makeRow(ticker: string, name: string, byWindow: Record<string, number | null>) {
  return {
    ticker,
    name,
    cells: Object.fromEntries(
      WINDOWS.map((w) => [w, { return_pct: byWindow[w] ?? null, base_date: byWindow[w] == null ? null : "2025-12-31" }])
    ),
  };
}

const DATA: SectorHeatmapOut = {
  as_of_date: "2026-09-18",
  computed_at: "2026-09-21T03:30:00",
  windows: WINDOWS,
  rows: [
    makeRow("XLK", "Technology", { "3m": -0.84, "1y": 38.05 }),
    makeRow("XLE", "Energy", { "3m": 20.46, "1y": 47.84 }),
    makeRow("XLC", "Communication Services", { "3m": 1.51 }), // young/blank 1y
  ],
};

function tickerOrder() {
  return screen.getAllByRole("rowheader").map((el) => el.textContent?.slice(0, 3));
}

describe("SectorHeatmapGrid", () => {
  it("renders one column header per window plus Sector, and one row per ETF", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    expect(screen.getAllByRole("columnheader").map((el) => el.textContent?.replace(/\s*[↑↓]$/, ""))).toEqual([
      "Sector", "1W", "1M", "3M", "6M", "9M", "YTD", "1Y",
    ]);
    expect(screen.getAllByRole("rowheader")).toHaveLength(3);
  });

  it("defaults to 3M descending with the active header marked", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    expect(tickerOrder()).toEqual(["XLE", "XLC", "XLK"]);
    expect(screen.getByRole("columnheader", { name: /3M/ })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: /1Y/ })).toHaveAttribute("aria-sort", "none");
  });

  it("clicking a header re-sorts, and clicking the active one again reverses it", () => {
    render(<SectorHeatmapGrid data={DATA} />);

    fireEvent.click(screen.getByRole("button", { name: /1Y/ }));
    expect(tickerOrder()).toEqual(["XLE", "XLK", "XLC"]); // XLC's blank 1Y sinks last
    expect(screen.getByRole("columnheader", { name: /1Y/ })).toHaveAttribute("aria-sort", "descending");

    fireEvent.click(screen.getByRole("button", { name: /1Y/ }));
    expect(tickerOrder()).toEqual(["XLK", "XLE", "XLC"]); // still last, though ascending
    expect(screen.getByRole("columnheader", { name: /1Y/ })).toHaveAttribute("aria-sort", "ascending");
  });

  it("shows signed one-decimal percentages and an em dash for a blank cell", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    const xle = screen.getByText("XLE").closest("[role=row]") as HTMLElement;
    expect(within(xle).getByText("+20.5%")).toBeInTheDocument();
    expect(within(xle).getByText("+47.8%")).toBeInTheDocument();

    const xlc = screen.getByText("XLC").closest("[role=row]") as HTMLElement;
    const oneYear = xlc.querySelector('[data-window="1y"]') as HTMLElement;
    expect(oneYear).toHaveTextContent("—");
    expect(oneYear.style.backgroundColor).toBe("");
  });

  it("tints gains with the positive token and losses with the negative one", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    const xlk = screen.getByText("XLK").closest("[role=row]") as HTMLElement;
    const loss = xlk.querySelector('[data-window="3m"]') as HTMLElement;
    const gain = xlk.querySelector('[data-window="1y"]') as HTMLElement;
    expect(loss).toHaveTextContent("-0.8%");
    expect(loss.style.backgroundColor).toContain("--color-negative");
    expect(gain.style.backgroundColor).toContain("--color-positive-strong");
  });

  it("explains the base close in a cell tooltip only when there is a value", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    const xlk = screen.getByText("XLK").closest("[role=row]") as HTMLElement;
    expect(xlk.querySelector('[data-window="ytd"]')).not.toHaveAttribute("title"); // blank in this fixture
    expect(xlk.querySelector('[data-window="1y"]')).toHaveAttribute("title", "1Y: from the Dec 31, 2025 close");
  });

  it("does not link the ETF labels (the ETF page doesn't exist yet)", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
