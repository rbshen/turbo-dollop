// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InsiderActivityTab } from "@/components/ticker/InsiderActivityTab";
import type { InsiderActivityOut, InsiderTransaction } from "@/lib/api/types";

const mockUseInsiderActivity = vi.fn();
vi.mock("@/lib/hooks/useInsiderActivity", () => ({
  useInsiderActivity: (ticker: string) => mockUseInsiderActivity(ticker),
}));

// Recharts' ResponsiveContainer needs layout that jsdom doesn't have.
vi.mock("@/components/insiderActivity/InsiderQuarterlyChart", () => ({
  InsiderQuarterlyChart: () => <div data-testid="quarterly-chart" />,
}));

beforeEach(() => mockUseInsiderActivity.mockReset());
afterEach(cleanup);

function tx(kind: InsiderTransaction["kind"], over: Partial<InsiderTransaction> = {}): InsiderTransaction {
  return {
    transaction_date: "2026-09-01",
    filing_date: "2026-09-03",
    insider_name: "Jane Doe",
    insider_cik: "1",
    insider_role: "officer: Chief Financial Officer",
    ownership: "direct",
    kind,
    type_label: kind === "open_market_buy" ? "Open-market buy" : kind === "award" ? "Grant / award" : "Open-market sale",
    shares: 1000,
    price: 10,
    has_cash_value: true,
    dollar_value: 10_000,
    sec_filing_url: "https://www.sec.gov/x",
    ...over,
  };
}

function data(over: Partial<InsiderActivityOut> = {}): InsiderActivityOut {
  return {
    ticker: "TEST",
    transactions: [],
    quarterly_stats: [],
    summary: {
      sentiment: "no_activity",
      quarters_in_window: 0,
      total_purchases: 0,
      total_sales: 0,
      total_acquired: 0,
      total_disposed: 0,
      open_market_buy_count: 0,
      open_market_sale_count: 0,
      cluster_buy: null,
      notable_buy: null,
      notable_sale: null,
    },
    has_data: false,
    as_of: null,
    ...over,
  };
}

describe("InsiderActivityTab empty states", () => {
  it("shows the genuine-empty message when cached but empty", () => {
    mockUseInsiderActivity.mockReturnValue({ data: data({ as_of: "2026-09-19T03:00:00" }) });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/No insider trading data available for this ticker/)).toBeInTheDocument();
    expect(screen.queryByText(/hasn't been cached/)).not.toBeInTheDocument();
  });

  it("shows a distinct 'not cached yet' message on a cold miss", () => {
    mockUseInsiderActivity.mockReturnValue({ data: data({ as_of: null }) });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/hasn't been cached for this ticker yet/)).toBeInTheDocument();
    expect(screen.queryByText(/No insider trading data available/)).not.toBeInTheDocument();
  });

  it("shows a loading state and an error state", () => {
    mockUseInsiderActivity.mockReturnValue({ data: undefined });
    const { unmount } = render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/Loading TEST/)).toBeInTheDocument();
    unmount();

    mockUseInsiderActivity.mockReturnValue({ data: undefined, error: new Error("boom") });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });
});

describe("InsiderActivityTab content", () => {
  const content = data({
    has_data: true,
    as_of: "2026-09-19T03:00:00",
    transactions: [tx("open_market_buy"), tx("award", { has_cash_value: false, dollar_value: null, price: null })],
    summary: {
      ...data().summary,
      sentiment: "net_buying",
      quarters_in_window: 2,
      total_purchases: 5,
      total_sales: 1,
      open_market_buy_count: 4,
      open_market_sale_count: 1,
      cluster_buy: { insider_count: 3, window_start: "2026-07-01", window_end: "2026-09-01" },
      notable_buy: tx("open_market_buy"),
    },
  });

  it("renders sentiment, the buy:sell pair, the cluster pill, the as-of line and the window caption", () => {
    mockUseInsiderActivity.mockReturnValue({ data: content });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText("Net buying")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText(/Cluster buy · 3 insiders/)).toBeInTheDocument();
    expect(screen.getByText(/Data as of/)).toBeInTheDocument();
    expect(screen.getByText(/approximation, not a true rolling 6 months/)).toBeInTheDocument();
    expect(screen.getByTestId("quarterly-chart")).toBeInTheDocument();
  });

  it("omits the cluster pill when there is no cluster", () => {
    mockUseInsiderActivity.mockReturnValue({
      data: { ...content, summary: { ...content.summary, cluster_buy: null } },
    });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.queryByText(/Cluster buy ·/)).not.toBeInTheDocument();
  });

  it("defaults the table to open-market rows and reveals the rest via the toggle, without refetching", () => {
    mockUseInsiderActivity.mockReturnValue({ data: content });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.queryByText("Grant / award")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All types" }));

    expect(screen.getByText("Grant / award")).toBeInTheDocument();
    expect(screen.getByText("no cash value")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    // The toggle only re-renders over the one fetched blob -- never asks for another resource.
    expect(new Set(mockUseInsiderActivity.mock.calls.map((c) => c[0]))).toEqual(new Set(["TEST"]));
  });

  it("links each filing out to the SEC URL", () => {
    mockUseInsiderActivity.mockReturnValue({ data: content });
    render(<InsiderActivityTab ticker="TEST" />);
    const link = screen.getByRole("link", { name: "Open SEC filing" });
    expect(link).toHaveAttribute("href", "https://www.sec.gov/x");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("explains an empty open-market view when only other types exist", () => {
    mockUseInsiderActivity.mockReturnValue({
      data: { ...content, transactions: [tx("award", { has_cash_value: false, dollar_value: null })] },
    });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/No open-market buys or sales/)).toBeInTheDocument();
  });
});
