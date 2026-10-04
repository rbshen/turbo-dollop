// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EtfHeader } from "@/components/ticker/EtfHeader";
import { TickerHeader } from "@/components/ticker/TickerHeader";
import type { TickerSummaryOut } from "@/lib/api/types";

// Which watchlist control each ticker-page header mounts, and for which audience. The controls themselves are tested
// in AddToWatchlistButton.test.tsx and EtfWatchlistButton.test.tsx.
vi.mock("@/components/ticker/AddToWatchlistButton", () => ({
  AddToWatchlistButton: ({ tickers, audience }: { tickers: string[]; audience?: string }) => (
    <span data-testid="stock-add" data-audience={audience}>{tickers.join(",")}</span>
  ),
}));
vi.mock("@/components/ticker/EtfWatchlistButton", () => ({
  EtfWatchlistButton: ({ ticker }: { ticker: string }) => <span data-testid="etf-add">{ticker}</span>,
}));
vi.mock("@/components/ticker/UniverseControl", () => ({ useUniverseControl: () => ({ control: null, note: null }) }));
vi.mock("@/components/ticker/RefreshButton", () => ({ RefreshButton: () => null }));
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useSpeculativeGrowth", () => ({ useSpeculativeGrowth: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTrendAnalysis", () => ({ useTrendAnalysis: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTickerScore", () => ({ useTickerScore: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useEtfOverview", () => ({ useEtfOverview: () => ({ data: undefined }) }));

afterEach(cleanup);

const DATA = {
  ticker: "AAPL",
  company_name: "Apple",
  exchange: "NASDAQ",
  sector: null,
  industry: null,
  index_memberships: [],
  price: 100,
  change: 1,
  change_percent: 1,
  quote_currency: "USD",
  reported_currency: "USD",
  fair_value_verdict: null,
  fair_value_price: null,
  fair_value_method: null,
  valuation_source: null,
  fair_value_reported_currency: null,
  perf_5y_vs_spy_status: null,
  perf_5y_insufficient_history: false,
  next_earnings_date: null,
} as unknown as TickerSummaryOut;

describe("ticker page watchlist controls", () => {
  it("the stock page uses the shared Add menu for the stock audience (the ETF-only list is hidden)", () => {
    render(<TickerHeader symbol="AAPL" data={DATA} />);
    expect(screen.getByTestId("stock-add")).toHaveAttribute("data-audience", "stock");
    expect(screen.queryByTestId("etf-add")).not.toBeInTheDocument();
  });

  it("the ETF page keeps its own one-click button and mounts no shared Add menu", () => {
    render(<EtfHeader data={{ ...DATA, ticker: "SPY" }} />);
    expect(screen.getByTestId("etf-add")).toHaveTextContent("SPY");
    expect(screen.queryByTestId("stock-add")).not.toBeInTheDocument();
  });
});
