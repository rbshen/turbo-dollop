// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SectorHeatmapGrid } from "@/components/sectors/SectorHeatmapGrid";
import type { SectorHeatmapOut } from "@/lib/api/types";

afterEach(cleanup);

const WINDOWS = ["1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y"];

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

describe("SectorHeatmapGrid: the sort direction icon", () => {
  const icons = (name: RegExp) => screen.getByRole("button", { name }).querySelectorAll("svg");

  it("shows one aria-hidden arrow on the active header only, and no arrow characters anywhere", () => {
    const { container } = render(<SectorHeatmapGrid data={DATA} />);
    expect(icons(/3M/)).toHaveLength(1);
    expect(icons(/3M/)[0]).toHaveAttribute("aria-hidden", "true");
    expect(icons(/1Y/)).toHaveLength(0);
    expect(container.textContent).not.toMatch(/[\u2191\u2193]/);
  });

  it("swaps the arrow when the direction flips, and moves it with the active header", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    const before = icons(/3M/)[0].innerHTML;
    fireEvent.click(screen.getByRole("button", { name: /3M/ }));
    expect(icons(/3M/)[0].innerHTML).not.toBe(before);
    fireEvent.click(screen.getByRole("button", { name: /1Y/ }));
    expect(icons(/1Y/)).toHaveLength(1);
    expect(icons(/3M/)).toHaveLength(0);
  });
});

describe("SectorHeatmapGrid", () => {
  it("renders one column header per window plus Sector, and one row per ETF", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    expect(screen.getAllByRole("columnheader").map((el) => el.textContent?.replace(/\s*[↑↓]$/, ""))).toEqual([
      "Sector", "1D", "1W", "1M", "3M", "6M", "9M", "YTD", "1Y",
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
    expect(gain.style.backgroundColor).toContain("--color-positive");
  });

  it("explains the base close in a cell tooltip only when there is a value", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    const xlk = screen.getByText("XLK").closest("[role=row]") as HTMLElement;
    expect(xlk.querySelector('[data-window="ytd"]')).not.toHaveAttribute("title"); // blank in this fixture
    expect(xlk.querySelector('[data-window="1y"]')).toHaveAttribute("title", "1Y: from the Dec 31, 2025 close");
  });
});

// Session 16: the active column is neutral (text-primary plus the arrow and aria-sort), never brand blue.
describe("SectorHeatmapGrid: the active column header is neutral", () => {
  it("draws the active header in text-primary and the others in text-tertiary, with no brand blue", () => {
    const { container } = render(<SectorHeatmapGrid data={DATA} />);
    expect(screen.getByRole("button", { name: /3M/ })).toHaveClass("text-text-primary");
    expect(screen.getByRole("button", { name: /3M/ }).className).not.toMatch(/text-text-tertiary/);
    expect(screen.getByRole("button", { name: /1Y/ })).toHaveClass("text-text-tertiary");
    expect(container.innerHTML).not.toMatch(/(bg|text|border)-brand/);
  });

  it("moves the neutral mark and aria-sort together when another header is chosen", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    fireEvent.click(screen.getByRole("button", { name: /1Y/ }));
    expect(screen.getByRole("button", { name: /1Y/ })).toHaveClass("text-text-primary");
    expect(screen.getByRole("button", { name: /3M/ })).toHaveClass("text-text-tertiary");
    expect(screen.getByRole("columnheader", { name: /1Y/ })).not.toHaveAttribute("aria-sort", "none");
  });
});

describe("SectorHeatmapGrid: sector labels link to the ETF page", () => {
  it("wraps each row label in one link to /tickers/<ETF>, opened in a new tab like other ticker links", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    const headers = screen.getAllByRole("rowheader");
    expect(headers).toHaveLength(3);
    for (const header of headers) {
      expect(within(header).getAllByRole("link")).toHaveLength(1);
    }
    const xlk = screen.getByRole("link", { name: /XLK/ });
    expect(xlk).toHaveAttribute("href", "/tickers/XLK");
    expect(xlk).toHaveAttribute("target", "_blank");
    expect(xlk.getAttribute("rel")).toContain("noopener");
    expect(xlk).toHaveTextContent("Technology");
  });

  it("links only the labels, not the sortable column headers or the return cells", () => {
    render(<SectorHeatmapGrid data={DATA} />);
    expect(screen.getAllByRole("link")).toHaveLength(3);
  });
});
