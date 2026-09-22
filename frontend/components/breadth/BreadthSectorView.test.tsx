// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import { BreadthSectorView } from "@/components/breadth/BreadthSectorView";
import type { MarketBreadthOut, MarketBreadthPointOut } from "@/lib/api/types";

afterEach(cleanup);

// jsdom has no layout engine; recharts' ResponsiveContainer needs ResizeObserver to mount at all.
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", NoopResizeObserver);

const point = (as_of_date: string, is_backfilled: boolean, overrides: Partial<MarketBreadthPointOut> = {}): MarketBreadthPointOut => ({
  as_of_date, pct_above_sma20: 61.2, pct_above_sma50: 63.4, pct_above_sma200: 70.1, sma20_above: 52, sma50_above: 54, sma200_above: 60,
  new_highs: 4, new_lows: 1, net_new_highs: 3, constituents: 85, stale_excluded: 0, sma20_eligible: 85, sma50_eligible: 85, sma200_eligible: 85,
  hl_eligible: 85, is_backfilled,
  ...overrides,
});

const body = (series: MarketBreadthPointOut[], universe = "sector:XLK"): MarketBreadthOut => ({
  universe,
  as_of_date: series.at(-1)?.as_of_date ?? null,
  computed_at: series.length ? "2026-09-21T03:35:00" : null,
  latest: series.at(-1) ?? null,
  series,
});

const MIXED = body([point("2026-09-17", true), point("2026-09-18", false), point("2026-09-19", false)]);
const EMPTY = body([]);

function renderView(sector: string) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <BreadthSectorView sector={sector} />
    </SWRConfig>
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

function stubFetch(payload: unknown, status = 200) {
  fetchMock = vi.fn(async () => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
}

beforeEach(() => stubFetch(MIXED));

describe("BreadthSectorView", () => {
  it("fetches the sector-scoped universe", async () => {
    renderView("XLK");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/market-breadth?universe=sector:XLK");
  });

  it("renders the tab strip with all 12 entries and highlights the active sector", async () => {
    renderView("XLK");
    await waitFor(() => expect(screen.getByRole("tablist")).toBeInTheDocument());
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(12);
    expect(screen.getByRole("tab", { name: "S&P 500" })).toHaveAttribute("href", "/breadth");
    const active = screen.getByRole("tab", { name: "XLK" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveAttribute("href", "/breadth/XLK");
    expect(screen.getByRole("tab", { name: "XLF" })).toHaveAttribute("aria-selected", "false");
  });

  it("shows the sector name/ticker and the latest reading", async () => {
    renderView("XLK");
    await waitFor(() => expect(screen.getByText(/As of close Sep 19, 2026/)).toBeInTheDocument());
    expect(screen.getByText(/Technology \(XLK\)/)).toBeInTheDocument();
    expect(screen.getByText("63.4%")).toBeInTheDocument();
  });

  it("renders gracefully for a refused-day shape (an older stored row, no crash)", async () => {
    renderView("XLK");
    await waitFor(() => expect(screen.getByText(/As of close Sep 19, 2026/)).toBeInTheDocument());
    expect(screen.getByText(/Sessions before Sep 18, 2026 are backfilled/)).toBeInTheDocument();
  });

  it("shows the no-data state when the sector has never cleared the gate", async () => {
    stubFetch(EMPTY);
    renderView("XLK");
    await waitFor(() => expect(screen.getByText(/No data yet/)).toBeInTheDocument());
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows an error when the request fails", async () => {
    stubFetch({ detail: "boom" }, 500);
    renderView("XLK");
    await waitFor(() => expect(screen.getByText("Failed to load Technology sector breadth.")).toBeInTheDocument());
  });

  it("shows an unknown-sector message and makes no fetch call for an unrecognized ticker", async () => {
    renderView("ZZZZ");
    await waitFor(() => expect(screen.getByText(/isn't one of the 11 SPDR sector ETFs/)).toBeInTheDocument());
    expect(screen.getByText('Unknown sector "ZZZZ"')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    // The tab strip still renders (so the user can navigate to a real sector) with nothing highlighted.
    expect(screen.getAllByRole("tab", { selected: false })).toHaveLength(12);
  });

  it("keeps the methodology footnote visible for a known sector", async () => {
    renderView("XLK");
    await waitFor(() => expect(screen.getByText("63.4%")).toBeInTheDocument());
    expect(screen.getByText(/Breadth across the current constituents of the Technology sector/)).toBeInTheDocument();
  });
});
