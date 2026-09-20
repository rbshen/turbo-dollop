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
// The mock echoes the view it was handed, so tests can assert the toggle reaches the chart.
vi.mock("@/components/insiderActivity/InsiderQuarterlyChart", () => ({
  InsiderQuarterlyChart: ({ view }: { view: string }) => <div data-testid="quarterly-chart" data-view={view} />,
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
    direction: kind === "open_market_buy" ? "acquired" : "disposed",
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
    enabled: true,
    transactions: [],
    quarterly_stats: [],
    quarterly_activity: [],
    history_truncated: false,
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

  it("shows a distinct 'turned off' message when the backend flag is off -- not the empty or not-cached ones", () => {
    mockUseInsiderActivity.mockReturnValue({ data: data({ enabled: false }) });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/Insider Activity is turned off/)).toBeInTheDocument();
    expect(screen.queryByText(/No insider trading data available/)).not.toBeInTheDocument();
    expect(screen.queryByText(/hasn't been cached/)).not.toBeInTheDocument();
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
      notable_buy: { ...tx("open_market_buy"), fill_count: 1 },
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

    fireEvent.click(screen.getAllByRole("button", { name: "All types" })[0]);

    expect(screen.getByText("Grant / award")).toBeInTheDocument();
    expect(screen.getByText("no cash value")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    // The toggle only re-renders over the one fetched blob -- never asks for another resource.
    expect(new Set(mockUseInsiderActivity.mock.calls.map((c) => c[0]))).toEqual(new Set(["TEST"]));
  });

  it("drives the chart and the table from one control -- either toggle switches both", () => {
    mockUseInsiderActivity.mockReturnValue({ data: content });
    render(<InsiderActivityTab ticker="TEST" />);
    const chart = () => screen.getByTestId("quarterly-chart");
    expect(chart()).toHaveAttribute("data-view", "open_market");

    // Two controls (chart heading, table header), index 0 = chart's, 1 = table's.
    const allTypes = () => screen.getAllByRole("button", { name: "All types" });
    const openMarket = () => screen.getAllByRole("button", { name: "Open market" });
    expect(allTypes()).toHaveLength(2);

    fireEvent.click(allTypes()[0]); // the chart's own control...
    expect(chart()).toHaveAttribute("data-view", "all");
    expect(screen.getByText("Grant / award")).toBeInTheDocument(); // ...also switched the table
    allTypes().forEach((b) => expect(b.className).toContain("bg-brand")); // ...and both controls agree
    openMarket().forEach((b) => expect(b.className).not.toContain("bg-brand"));

    fireEvent.click(openMarket()[1]); // the table's control switches the chart back
    expect(chart()).toHaveAttribute("data-view", "open_market");
    expect(screen.queryByText("Grant / award")).not.toBeInTheDocument();
  });

  it("captions what the chart is counting for the current view", () => {
    mockUseInsiderActivity.mockReturnValue({ data: content });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText("Open-market buys and sales only.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "All types" })[0]);
    expect(screen.getByText(/All transaction types — includes option exercises, tax withholding/)).toBeInTheDocument();
  });

  it("notes when earlier quarters were left out, and only then", () => {
    mockUseInsiderActivity.mockReturnValue({ data: { ...content, history_truncated: true } });
    const { unmount } = render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/Earlier quarters are left out/)).toBeInTheDocument();
    unmount();

    mockUseInsiderActivity.mockReturnValue({ data: content });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.queryByText(/Earlier quarters are left out/)).not.toBeInTheDocument();
  });

  it("renders a page of rows at a time and reveals the rest on request", () => {
    const many = Array.from({ length: 230 }, (_, i) =>
      tx("open_market_sale", { insider_name: `Insider ${i}`, insider_cik: String(i) })
    );
    mockUseInsiderActivity.mockReturnValue({ data: { ...content, transactions: many } });
    render(<InsiderActivityTab ticker="TEST" />);

    expect(screen.getAllByText(/^Insider \d+$/)).toHaveLength(100);
    expect(screen.getByText("Showing 100 of 230")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show 100 more" }));
    expect(screen.getAllByText(/^Insider \d+$/)).toHaveLength(200);

    fireEvent.click(screen.getByRole("button", { name: "Show 30 more" }));
    expect(screen.getAllByText(/^Insider \d+$/)).toHaveLength(230);
    expect(screen.queryByText(/^Showing/)).not.toBeInTheDocument();
  });

  it("renders no 'show more' control when everything fits on one page", () => {
    mockUseInsiderActivity.mockReturnValue({ data: content });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.queryByText(/^Showing/)).not.toBeInTheDocument();
  });

  it("shows a fill count on a merged notable trade and none on a single-line one", () => {
    mockUseInsiderActivity.mockReturnValue({
      data: {
        ...content,
        summary: {
          ...content.summary,
          notable_buy: { ...tx("open_market_buy", { shares: 1000 }), fill_count: 1 },
          notable_sale: { ...tx("open_market_sale", { shares: 5000, dollar_value: 250_000_000 }), fill_count: 22 },
        },
      },
    });
    render(<InsiderActivityTab ticker="TEST" />);
    expect(screen.getByText(/22 fills/)).toBeInTheDocument();
    expect(screen.getByText("$250.00M")).toBeInTheDocument();
    expect(screen.queryByText(/1 fills/)).not.toBeInTheDocument();
    expect(screen.queryByText(/fill\b/)).not.toBeInTheDocument();
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
