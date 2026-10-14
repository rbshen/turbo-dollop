// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import SectorsPage from "@/app/sectors/page";
import type { SectorHeatmapOut } from "@/lib/api/types";

afterEach(cleanup);

const WINDOWS = ["1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y"];
const cells = (byWindow: Record<string, number>) =>
  Object.fromEntries(WINDOWS.map((w) => [w, { return_pct: byWindow[w] ?? 0, base_date: "2025-12-31" }]));

const LOADED: SectorHeatmapOut = {
  as_of_date: "2026-09-18",
  computed_at: "2026-09-21T03:30:00",
  windows: WINDOWS,
  rows: [
    { ticker: "XLK", name: "Technology", cells: cells({ "1d": 0.5, "1w": -1, "1m": 2, "1y": 30 }) },
    { ticker: "XLE", name: "Energy", cells: cells({ "1d": -0.3, "1w": 3, "1m": -2, "1y": 40 }) },
  ],
};
const EMPTY: SectorHeatmapOut = { as_of_date: null, computed_at: null, windows: WINDOWS, rows: [] };

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SectorsPage />
    </SWRConfig>
  );
}

function stubFetch(body: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));
}

const charts = () => screen.getAllByRole("region");
const order = (chart: HTMLElement) => within(chart).getAllByRole("listitem").map((li) => within(li).getByText(/^XL/).textContent);

beforeEach(() => stubFetch(LOADED));

describe("SectorsPage", () => {
  it("is titled Sectors, with no heatmap wording", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Sectors" })).toBeInTheDocument();
    await waitFor(() => expect(charts()).toHaveLength(3));
    expect(document.body.textContent).not.toMatch(/heatmap/i);
  });

  it("shows a loading state before data arrives", () => {
    renderPage();
    expect(screen.getByText("Loading sector returns…")).toBeInTheDocument();
  });

  it("stacks three charts defaulting to Today, 1W, 1M", async () => {
    renderPage();
    await waitFor(() => expect(charts()).toHaveLength(3));
    expect(charts().map((c) => c.getAttribute("data-window"))).toEqual(["1d", "1w", "1m"]);
    expect([1, 2, 3].map((n) => (screen.getByLabelText(`Return window, chart ${n}`) as HTMLSelectElement).value)).toEqual(["1d", "1w", "1m"]);
    expect(order(charts()[0])).toEqual(["XLK", "XLE"]); // 1d: 0.5 > -0.3
    expect(order(charts()[1])).toEqual(["XLE", "XLK"]); // 1w: 3 > -1
  });

  it("changes one chart's window without touching the others", async () => {
    renderPage();
    await waitFor(() => expect(charts()).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("Return window, chart 2"), { target: { value: "1y" } });
    expect(charts().map((c) => c.getAttribute("data-window"))).toEqual(["1d", "1y", "1m"]);
    expect(order(charts()[1])).toEqual(["XLE", "XLK"]);
    expect(screen.getByText("+40.00%")).toBeInTheDocument();
  });

  it("returns to the defaults after a reload (selections are not persisted)", async () => {
    const first = renderPage();
    await waitFor(() => expect(charts()).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("Return window, chart 1"), { target: { value: "1y" } });
    first.unmount();
    renderPage();
    await waitFor(() => expect(charts()).toHaveLength(3));
    expect(charts().map((c) => c.getAttribute("data-window"))).toEqual(["1d", "1w", "1m"]);
  });

  it("shows the no-data state when the nightly job has never run", async () => {
    stubFetch(EMPTY);
    renderPage();
    await waitFor(() => expect(screen.getByText(/No data yet/)).toBeInTheDocument());
    expect(screen.queryAllByRole("region")).toHaveLength(0);
  });

  it("shows an error when the request fails", async () => {
    stubFetch({ detail: "boom" }, 500);
    renderPage();
    await waitFor(() => expect(screen.getByText("Failed to load the sector returns.")).toBeInTheDocument());
  });

  it("notes split-adjusted price change without dividends, and the as-of date", async () => {
    renderPage();
    await waitFor(() => expect(charts()).toHaveLength(3));
    expect(screen.getByText(/split-adjusted price change/)).toBeInTheDocument();
    expect(screen.getByText(/no dividends/)).toBeInTheDocument();
    expect(screen.getByText(/Data as of the close on Sep 18, 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/comparable across columns/)).not.toBeInTheDocument();
  });
});
