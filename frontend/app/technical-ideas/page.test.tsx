// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import TechnicalIdeasPage from "@/app/technical-ideas/page";
import type { AnchorHeadroomOut, WarrenWatchOut } from "@/lib/api/types";
import { TestAuth } from "@/lib/auth/testAuth";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const DATA: WarrenWatchOut = {
  as_of: "2026-10-15T15:30:00",
  rows: [
    {
      ticker: "AAA", profile: "any", latest_arrow_color: "blue", latest_arrow_direction: "up", latest_arrow_at: "2026-10-15T13:30:00",
      instruction_type: 2, instruction_text: "BLUE UP - Buy.", entry_kind: "blue", entry_at: "2026-10-15T13:30:00", last_price: 110, last_price_date: "2026-10-15", pl_pct: 0.1, stop_distance_pct: 0.1818, entry_price: 100, stop_price: null, stop_basis: "none", stop_moved_at: null, stop_moved_by: null,
      status: "active", breached_at: null, last_signal_at: "2026-10-15T13:30:00", last_updated_at: "2026-10-16T01:25:00", age_bars: 5,
      last_signal_age_bars: 5,
    },
  ],
};

describe("Technical Ideas page", () => {
  it("loads the Warren watch table from the API under the page title", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(DATA), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <TestAuth role="viewer">
          <TechnicalIdeasPage />
        </TestAuth>
      </SWRConfig>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Technical Ideas" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "RSI WVF ADX by Warren" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("link", { name: "AAA" })).toBeInTheDocument());
    expect(screen.getByText("As of Oct 15, 15:30 ET")).toBeInTheDocument();
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain("/technical-ideas/warren");
  });

  it("draws the anchor banner directly below the title for an admin, above the table", async () => {
    const headroom: AnchorHeadroomOut = {
      days: 250, level: "urgent", anchor: "2025-10-15T15:30:00", slice_start: "2026-01-12",
      warning_date: "2026-12-19", urgent_date: "2027-01-18", deadline_date: "2027-04-17",
    };
    const body = JSON.stringify({ ...DATA, anchor_headroom: headroom });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200, headers: { "content-type": "application/json" } })));
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <TestAuth role="admin">
          <TechnicalIdeasPage />
        </TestAuth>
      </SWRConfig>,
    );
    const banner = await screen.findByRole("alert", { name: "Warren replay start: urgent" });
    const title = screen.getByRole("heading", { level: 1, name: "Technical Ideas" });
    const section = screen.getByRole("region", { name: /RSI WVF ADX by Warren/ });
    expect(title.compareDocumentPosition(banner) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(banner.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Nothing sits between the title block and the banner but the header wrapper's own siblings.
    expect(title.closest("div")?.parentElement?.nextElementSibling).toBe(banner);
  });

  it("draws no banner for a viewer even when the data carries one", async () => {
    const headroom: AnchorHeadroomOut = {
      days: 250, level: "urgent", anchor: "2025-10-15T15:30:00", slice_start: "2026-01-12",
      warning_date: "2026-12-19", urgent_date: "2027-01-18", deadline_date: "2027-04-17",
    };
    const body = JSON.stringify({ ...DATA, anchor_headroom: headroom });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200, headers: { "content-type": "application/json" } })));
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <TestAuth role="viewer">
          <TechnicalIdeasPage />
        </TestAuth>
      </SWRConfig>,
    );
    await waitFor(() => expect(screen.getByRole("link", { name: "AAA" })).toBeInTheDocument());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
