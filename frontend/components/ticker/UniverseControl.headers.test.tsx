// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EtfHeader } from "@/components/ticker/EtfHeader";
import { TickerHeader } from "@/components/ticker/TickerHeader";
import type { TickerSummaryOut } from "@/lib/api/types";

// The one shared control is rendered by both headers; mocked here to a marker so this only pins the wiring (the control's
// own behaviour is in UniverseControl.test.tsx).
vi.mock("@/components/ticker/UniverseControl", () => ({
  UniverseControl: ({ ticker }: { ticker: string }) => <div data-testid="universe-control">{ticker}</div>,
}));
vi.mock("@/components/ticker/AddToWatchlistButton", () => ({ AddToWatchlistButton: () => <button>Add to watchlist</button> }));
vi.mock("@/components/ticker/EtfWatchlistButton", () => ({ EtfWatchlistButton: () => <button>Add to watchlist</button> }));
vi.mock("@/components/ticker/RefreshButton", () => ({ RefreshButton: () => <button>Refresh data</button> }));
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useSpeculativeGrowth", () => ({ useSpeculativeGrowth: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTrendAnalysis", () => ({ useTrendAnalysis: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTickerScore", () => ({ useTickerScore: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useEtfOverview", () => ({ useEtfOverview: () => ({ data: undefined }) }));

afterEach(cleanup);

const SUMMARY = {
  ticker: "ABC",
  company_name: "Abc Corp",
  exchange: "NYSE",
  sector: null,
  industry: null,
  index_memberships: [],
  price: 10,
  change: 0,
  change_percent: 0,
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

describe("the universe control on the headers", () => {
  it("TickerHeader renders it for the ticker, before the watchlist and refresh buttons", () => {
    render(<TickerHeader symbol="ABC" data={SUMMARY} />);
    const control = screen.getByTestId("universe-control");
    expect(control).toHaveTextContent("ABC");
    expect(control.compareDocumentPosition(screen.getByRole("button", { name: "Add to watchlist" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Refresh data" })).toBeInTheDocument();
  });

  it("EtfHeader renders the same control, before the ETF watchlist button", () => {
    render(<EtfHeader data={{ ...SUMMARY, ticker: "QQQ" }} />);
    const control = screen.getByTestId("universe-control");
    expect(control).toHaveTextContent("QQQ");
    expect(control.compareDocumentPosition(screen.getByRole("button", { name: "Add to watchlist" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
