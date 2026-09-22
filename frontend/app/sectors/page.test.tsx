// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import SectorsPage from "@/app/sectors/page";
import type { SectorHeatmapOut } from "@/lib/api/types";

afterEach(cleanup);

const WINDOWS = ["1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y"];
const cells = () => Object.fromEntries(WINDOWS.map((w) => [w, { return_pct: 4.25, base_date: "2025-12-31" }]));

const LOADED: SectorHeatmapOut = {
  as_of_date: "2026-09-18",
  computed_at: "2026-09-21T03:30:00",
  windows: WINDOWS,
  rows: [{ ticker: "XLK", name: "Technology", cells: cells() }],
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

beforeEach(() => stubFetch(LOADED));

describe("SectorsPage", () => {
  it("shows a loading state before data arrives", () => {
    renderPage();
    expect(screen.getByText("Loading sector heatmap…")).toBeInTheDocument();
  });

  it("renders the grid and the as-of date (timezone-safe) once loaded", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("XLK")).toBeInTheDocument());
    expect(screen.getByText(/As of close Sep 18, 2026/)).toBeInTheDocument();
  });

  it("shows the no-data state when the nightly job has never run", async () => {
    stubFetch(EMPTY);
    renderPage();
    await waitFor(() => expect(screen.getByText(/No data yet/)).toBeInTheDocument());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows an error when the request fails", async () => {
    stubFetch({ detail: "boom" }, 500);
    renderPage();
    await waitFor(() => expect(screen.getByText("Failed to load the sector heatmap.")).toBeInTheDocument());
  });

  it("keeps the methodology footnote visible", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("XLK")).toBeInTheDocument());
    expect(screen.getByText(/Trailing total return/)).toBeInTheDocument();
    expect(screen.getByText(/scaled within each column/)).toBeInTheDocument();
  });
});
