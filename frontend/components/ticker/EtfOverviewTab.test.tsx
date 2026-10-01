// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EtfOverviewTab } from "@/components/ticker/EtfOverviewTab";
import type { EtfOverviewOut } from "@/lib/api/types";

let hookState: { data?: EtfOverviewOut; error?: Error; isLoading: boolean };
vi.mock("@/lib/hooks/useEtfOverview", () => ({ useEtfOverview: () => hookState }));

const EQUITY: EtfOverviewOut = {
  ticker: "QQQ",
  status: "ok",
  reason: null,
  name: "Invesco QQQ Trust",
  issuer: "Invesco",
  asset_class: "Equity",
  expense_ratio: 0.18,
  assets_under_management: 498_608_653_246,
  holdings_count: 102,
  nav: 737.91,
  nav_currency: "USD",
  avg_volume: 39_574_630,
  inception_date: "1999-03-10",
  domicile: "US",
  description: "Tracks the Nasdaq-100 index.",
  website: null,
  sector_weights: [
    { sector: "Technology", weight: 60.5 },
    { sector: "Communication Services", weight: 12.18 },
    { sector: "Basic Materials", weight: 0.9 },
  ],
  updated_at: "2026-10-01T00:38:20.213Z",
  fetched_at: null,
};
const GOLD: EtfOverviewOut = {
  ...EQUITY,
  ticker: "GLD",
  issuer: "SPDR",
  asset_class: "Commodities",
  holdings_count: null, // GLD reports 0 -> the backend sends null
  domicile: null,
  sector_weights: [],
};

beforeEach(() => {
  hookState = { data: EQUITY, isLoading: false };
});
afterEach(cleanup);

describe("EtfOverviewTab: a loaded equity fund", () => {
  it("shows Fund facts as mono right-aligned definition rows, then About this fund as plain text", () => {
    render(<EtfOverviewTab ticker="QQQ" />);

    expect(screen.getByRole("heading", { name: "Fund facts" })).toBeInTheDocument();
    const row = screen.getByText("Expense ratio").parentElement as HTMLElement;
    expect(within(row).getByText("0.18%")).toHaveClass("font-mono");
    for (const label of [
      "Issuer", "Asset class", "Assets under management", "Holdings", "NAV", "Average volume", "Inception date", "Domicile",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("$498.61B")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "About this fund" })).toBeInTheDocument();
    expect(screen.getByText("Tracks the Nasdaq-100 index.").tagName).toBe("P");
  });

  it("shows sector weights as bars, largest first, with the exact figure and the series colour", () => {
    render(<EtfOverviewTab ticker="QQQ" />);

    expect(screen.getByRole("heading", { name: "Sector weights" })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["Technology60.5%", "Communication Services12.2%", "Basic Materials0.9%"]);
    const bar = items[0].querySelector(".bg-series-1") as HTMLElement;
    expect(bar.style.width).toBe("100%"); // longest bar
    expect((items[1].querySelector(".bg-series-1") as HTMLElement).style.width).toMatch(/^20\.1/);
    expect(screen.queryByTestId("sector-weights-note")).not.toBeInTheDocument();
    expect(screen.getByText("Fund data as of 2026-10-01")).toBeInTheDocument();
  });

  it("uses the 7/5 two-column layout", () => {
    const { container } = render(<EtfOverviewTab ticker="QQQ" />);
    expect(container.querySelector(".lg\\:col-span-7")).not.toBeNull();
    expect(container.querySelector(".lg\\:col-span-5")).not.toBeNull();
  });
});

describe("EtfOverviewTab: a fund that does not hold stocks", () => {
  it("replaces the sector bars with the short note and omits facts the endpoint did not return", () => {
    hookState = { data: GOLD, isLoading: false };
    render(<EtfOverviewTab ticker="GLD" />);

    expect(screen.getByTestId("sector-weights-note")).toHaveTextContent(
      "Sector weights are not shown for funds that don't hold stocks.",
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.queryByText("Holdings")).not.toBeInTheDocument();
    expect(screen.queryByText("Domicile")).not.toBeInTheDocument();
    expect(screen.getByText("Commodities")).toBeInTheDocument();
  });

  it("omits the About section when there is no description", () => {
    hookState = { data: { ...GOLD, description: null }, isLoading: false };
    render(<EtfOverviewTab ticker="GLD" />);
    expect(screen.queryByRole("heading", { name: "About this fund" })).not.toBeInTheDocument();
  });
});

describe("EtfOverviewTab: unavailable and failure states", () => {
  it("group off / not on plan, nothing cached: a clear unavailable state, no facts", () => {
    hookState = { data: { ...EQUITY, status: "unavailable", reason: "group_off" }, isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.getByTestId("etf-overview-unavailable")).toHaveTextContent(/ETF info data group is off/);
    expect(screen.queryByRole("heading", { name: "Fund facts" })).not.toBeInTheDocument();
  });

  it("call failed, nothing cached: says FMP couldn't be reached", () => {
    hookState = { data: { ...EQUITY, status: "unavailable", reason: "fetch_failed" }, isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.getByTestId("etf-overview-unavailable")).toHaveTextContent(/Couldn't load fund details for QQQ/);
  });

  it("FMP has no record for the ticker", () => {
    hookState = { data: { ...EQUITY, status: "no_data" }, isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.getByTestId("etf-overview-unavailable")).toHaveTextContent("FMP has no fund details for QQQ.");
  });

  it("an API error (the backend itself down) is a one-line negative message", () => {
    hookState = { error: new Error("GET /x failed: 500"), isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.getByText(/Couldn't load fund details — GET \/x failed: 500/)).toHaveClass("text-negative");
  });

  it("shows a loading line while the request is in flight", () => {
    hookState = { isLoading: true };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
