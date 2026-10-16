// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import TechnicalIdeasPage from "@/app/technical-ideas/page";
import type { WarrenWatchOut } from "@/lib/api/types";
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
});
