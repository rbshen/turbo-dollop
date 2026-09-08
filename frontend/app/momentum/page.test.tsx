// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import MomentumPage from "@/app/momentum/page";
import type { MomentumOut } from "@/lib/api/types";

afterEach(cleanup);

const CURRENT: MomentumOut = {
  as_of_date: "2026-08-31",
  computed_at: "2026-09-08T07:11:15.217090",
  rows: [
    {
      ticker: "SNDK",
      company_name: "Sandisk Corporation",
      moat: "no_moat",
      return_3mo: -0.0757,
      return_6mo: 1.4658,
      return_12mo: 28.859,
      composite_score: 10.083,
      rank: 1,
      overall_score: 47,
    },
  ],
};

const EMPTY: MomentumOut = { as_of_date: null, computed_at: null, rows: [] };

// A fresh SWRConfig cache per test, matching the "fresh cache provider"
// pattern SWR's own docs recommend for tests -- this codebase has no prior
// SWR-mocking precedent to follow, so the isolation itself (rather than a
// specific existing convention) is what matters here.
function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MomentumPage />
    </SWRConfig>
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const period = new URL(url, "http://localhost").searchParams.get("period");
      const body = period === "previous" ? EMPTY : CURRENT;
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    })
  );
});

describe("MomentumPage", () => {
  it("shows a loading state before data arrives", () => {
    renderPage();
    expect(screen.getByText("Loading Momentum…")).toBeInTheDocument();
  });

  it("renders the current month's data once loaded", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("SNDK")).toBeInTheDocument());
    expect(screen.getByText(/As of/)).toBeInTheDocument();
  });

  it("toggling to Previous month refetches and shows the empty state", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("SNDK")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));

    await waitFor(() => expect(screen.getByText("No previous month's snapshot available yet.")).toBeInTheDocument());
    expect(screen.queryByText("SNDK")).not.toBeInTheDocument();
  });

  it("footer caveats are always visible, not behind any collapse toggle", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("SNDK")).toBeInTheDocument());
    expect(screen.getByText(/Point-in-time caveat/)).toBeInTheDocument();
    expect(screen.getByText(/Ad hoc external research/)).toBeInTheDocument();
  });
});
