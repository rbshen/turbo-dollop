// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EtfOverviewTab } from "@/components/ticker/EtfOverviewTab";
import type { EtfOverviewOut, EtfTradingDataOut } from "@/lib/api/types";

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
  trading_data: null,
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

const TRADING: EtfTradingDataOut = {
  perf_1m: 4.21,
  perf_ytd: -3.4,
  perf_1y: 20.05,
  perf_as_of: "2026-10-01",
  week52_low: 555.6,
  week52_high: 748.65,
  avg_volume_30d: 41_200_000,
  avg_dollar_volume_20d: 29_800_000_000,
  distribution_ttm_per_share: 3.09182,
  distribution_ttm_yield_pct: 0.42,
  beta: 1.23,
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

describe("EtfOverviewTab: Trading data block", () => {
  it("sits between Fund facts and About this fund, as mono right-aligned definition rows", () => {
    hookState = { data: { ...EQUITY, trading_data: TRADING }, isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);

    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings.slice(0, 3)).toEqual(["Fund facts", "Trading data", "About this fund"]);
    const row = screen.getByText("52-week range").parentElement as HTMLElement;
    expect(within(row).getByText("$555.60 – $748.65")).toHaveClass("font-mono");
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Distribution yield (TTM)")).toBeInTheDocument();
  });

  it("colours the signed returns", () => {
    hookState = { data: { ...EQUITY, trading_data: TRADING }, isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.getByText("+4.21%")).toHaveClass("text-positive");
    expect(screen.getByText("-3.40%")).toHaveClass("text-negative");
  });

  it("carries a 13px tertiary caption naming the basis", () => {
    hookState = { data: { ...EQUITY, trading_data: TRADING }, isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);
    const caption = screen.getByText(/Performance is price return from daily closes through 2026-10-01/);
    expect(caption).toHaveClass("text-xs", "text-text-tertiary");
  });

  it("a bond or commodity fund: no beta row, no distribution row when the fund pays none, other rows stay", () => {
    hookState = {
      data: {
        ...GOLD,
        trading_data: { ...TRADING, beta: null, distribution_ttm_per_share: null, distribution_ttm_yield_pct: null },
      },
      isLoading: false,
    };
    render(<EtfOverviewTab ticker="GLD" />);
    expect(screen.getByRole("heading", { name: "Trading data" })).toBeInTheDocument();
    expect(screen.queryByText("Beta")).not.toBeInTheDocument();
    expect(screen.queryByText("Distribution yield (TTM)")).not.toBeInTheDocument();
    expect(screen.queryByText(/not an SEC yield/)).not.toBeInTheDocument();
    expect(screen.getByText("1Y performance")).toBeInTheDocument();
  });

  it("missing bars: the performance rows (and their note) are omitted, the rest stay", () => {
    hookState = {
      data: { ...EQUITY, trading_data: { ...TRADING, perf_1m: null, perf_ytd: null, perf_1y: null, perf_as_of: null } },
      isLoading: false,
    };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.queryByText("1M performance")).not.toBeInTheDocument();
    expect(screen.queryByText(/Performance is price return/)).not.toBeInTheDocument();
    expect(screen.getByText("52-week range")).toBeInTheDocument();
  });

  it("hides the whole block when there is no data, or every row is zero/null", () => {
    hookState = { data: { ...EQUITY, trading_data: null }, isLoading: false };
    const { unmount } = render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.queryByRole("heading", { name: "Trading data" })).not.toBeInTheDocument();
    unmount();

    hookState = {
      data: {
        ...EQUITY,
        trading_data: {
          perf_1m: 0, perf_ytd: null, perf_1y: null, perf_as_of: null, week52_low: null, week52_high: null,
          avg_volume_30d: null, avg_dollar_volume_20d: 0, distribution_ttm_per_share: null,
          distribution_ttm_yield_pct: null, beta: null,
        },
      },
      isLoading: false,
    };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.queryByRole("heading", { name: "Trading data" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fund facts" })).toBeInTheDocument();
  });

  it("is not shown in the unavailable state", () => {
    hookState = { data: { ...EQUITY, status: "unavailable", reason: "group_off", trading_data: TRADING }, isLoading: false };
    render(<EtfOverviewTab ticker="QQQ" />);
    expect(screen.queryByRole("heading", { name: "Trading data" })).not.toBeInTheDocument();
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
