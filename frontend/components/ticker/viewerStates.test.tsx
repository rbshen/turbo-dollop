// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TickerNotFound } from "@/components/ticker/TickerNotFound";
import { TickerTabsContainer } from "@/components/ticker/TickerTabsContainer";
import { ApiError } from "@/lib/api/client";
import { TestAuth } from "@/lib/auth/testAuth";
import { unavailableMessage } from "@/lib/etfOverview";
import type { EtfOverviewOut } from "@/lib/api/types";

const h = vi.hoisted(() => ({ summary: {} as { data?: unknown; error?: Error }, requested: [] as string[] }));
vi.mock("@/lib/hooks/useTickerSummary", () => ({ useTickerSummary: () => h.summary }));
vi.mock("@/lib/api/client", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/client")>()),
  apiFetch: (path: string) => {
    h.requested.push(path);
    return Promise.resolve({ groups: [], tiers: [] });
  },
}));

beforeEach(() => {
  h.summary = {};
  h.requested = [];
});
afterEach(cleanup);

const as = (role: "admin" | "viewer", ui: React.ReactNode) =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <TestAuth role={role}>{ui}</TestAuth>
    </SWRConfig>,
  );

describe("a ticker the viewer cannot open (404)", () => {
  beforeEach(() => {
    h.summary = { error: new ApiError("GET /tickers/ZZZ/summary failed: 404 - Not found", 404, "Not found") };
  });

  it("shows a clean 'isn't available' state to a viewer: not an error line, not a spinner", () => {
    as("viewer", <TickerTabsContainer ticker="ZZZ" />);
    const state = screen.getByTestId("ticker-not-available");
    expect(state).toHaveTextContent("“ZZZ” isn't available");
    expect(state).toHaveTextContent("isn't tracked");
    expect(screen.queryByText(/Loading/)).toBeNull();
    expect(screen.queryByText(/Couldn.t load/)).toBeNull();
  });

  it("keeps the existing 'not found' wording for an admin", () => {
    as("admin", <TickerTabsContainer ticker="ZZZ" />);
    expect(screen.getByText(/Ticker .ZZZ. not found/)).toBeInTheDocument();
    expect(screen.queryByTestId("ticker-not-available")).toBeNull();
  });

  it("TickerNotFound alone follows the role the same way", () => {
    as("viewer", <TickerNotFound ticker="ZZZ" />);
    expect(screen.getByTestId("ticker-not-available")).toBeInTheDocument();
  });

  it("any other failure is still the inline error line, for a viewer too", () => {
    h.summary = { error: new ApiError("GET /tickers/ZZZ/summary failed: 500", 500) };
    as("viewer", <TickerTabsContainer ticker="ZZZ" />);
    expect(screen.getByText(/Couldn.t load ZZZ/)).toBeInTheDocument();
    expect(screen.queryByTestId("ticker-not-available")).toBeNull();
  });

  it("while loading, nobody gets the not-available state", () => {
    h.summary = {};
    as("viewer", <TickerTabsContainer ticker="ZZZ" />);
    expect(screen.getByText("Loading ZZZ…")).toBeInTheDocument();
  });
});

describe("redacted (null) fields", () => {
  const BASE = { ticker: "QQQ", name: null, status: "unavailable", reason: null } as unknown as EtfOverviewOut;

  it("an unavailable ETF overview whose reason is redacted still gets a sentence, not 'null'", () => {
    const text = unavailableMessage(BASE);
    expect(text).toBe("Fund details for QQQ are not available right now.");
    expect(text).not.toMatch(/null|undefined/);
  });
});
