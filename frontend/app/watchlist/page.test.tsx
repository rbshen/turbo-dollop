// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import WatchlistPage from "@/app/watchlist/page";
import type { WatchlistOut } from "@/lib/api/types";

afterEach(cleanup);

// Two empty watchlists are enough to exercise the switcher itself --
// WatchlistTable's own empty-tickers early return means no WatchlistRowOut
// fixture is needed here (see WatchlistTable.test.tsx for that shape).
const WATCHLISTS: WatchlistOut[] = [
  {
    id: 1,
    name: "W1",
    sort_field: "ticker",
    sort_direction: "asc",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    tickers: [],
  },
  {
    id: 2,
    name: "W2",
    sort_field: "ticker",
    sort_direction: "asc",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    tickers: [],
  },
];

// Fresh SWRConfig cache per test, matching app/momentum/page.test.tsx's own
// isolation convention.
function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <WatchlistPage />
    </SWRConfig>
  );
}

let fixture: WatchlistOut[] = WATCHLISTS;

beforeEach(() => {
  fixture = WATCHLISTS;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.includes("/rows") ? [] : fixture;
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    })
  );
});

describe("WatchlistPage", () => {
  it("defaults to the most recently created watchlist and lists every watchlist as a tab", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("tab", { name: "W2" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("tab", { name: "W1" })).toHaveAttribute("aria-selected", "false");
  });

  it("switches the active watchlist when a different tab is clicked", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("tab", { name: "W2" })).toHaveAttribute("aria-selected", "true"));

    fireEvent.click(screen.getByRole("tab", { name: "W1" }));

    await waitFor(() => expect(screen.getByRole("tab", { name: "W1" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("tab", { name: "W2" })).toHaveAttribute("aria-selected", "false");
  });

  it("offers rename and delete for an ordinary list but neither for the ETF list", async () => {
    fixture = [{ ...WATCHLISTS[0], id: 3, name: "ETF", created_at: "2026-01-03T00:00:00Z" }, WATCHLISTS[1]];
    renderPage();
    // The ETF list is the most recently created, so it is the active tab.
    await waitFor(() => expect(screen.getByRole("tab", { name: "ETF" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.queryByRole("button", { name: /^Rename/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Delete/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "W2" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Rename W2" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^Delete/ })).toBeInTheDocument();
  });
});
