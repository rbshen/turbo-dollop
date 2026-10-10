// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TickerTabsContainer } from "@/components/ticker/TickerTabsContainer";
import type { TickerSummaryOut } from "@/lib/api/types";

// Detection + routing: the container reads is_etf off the summary and renders either the stock page or the
// ETF variant. Every tab body and the header hooks are replaced by probes, so what is pinned is WHICH page and
// WHICH tab set renders -- and that no stock-only tab body is ever mounted for an ETF.
let summary: Partial<TickerSummaryOut> | undefined;
const { mounted, probe } = vi.hoisted(() => {
  const mounted: string[] = [];
  return {
    mounted,
    probe: (name: string) => () => {
      mounted.push(name);
      return null;
    },
  };
});

vi.mock("@/lib/hooks/useTickerSummary", () => ({ useTickerSummary: () => ({ data: summary, error: undefined }) }));
vi.mock("@/components/ticker/TickerHeader", () => ({ TickerHeader: () => <div data-testid="stock-header" /> }));
vi.mock("@/components/ticker/EtfHeader", () => ({ EtfHeader: () => <div data-testid="etf-header" /> }));
vi.mock("@/components/shared/GroupOffBadge", () => ({ GroupOffBadge: () => null }));
vi.mock("@/components/ticker/SummaryTab", () => ({ SummaryTab: probe("summary") }));
vi.mock("@/components/ticker/FinancialsTab", () => ({ FinancialsTab: probe("financials") }));
vi.mock("@/components/ticker/RatiosTab", () => ({ RatiosTab: probe("ratios") }));
vi.mock("@/components/ticker/DashboardTab", () => ({ DashboardTab: probe("dashboard") }));
vi.mock("@/components/ticker/AnalysisTab", () => ({ AnalysisTab: probe("analysis") }));
vi.mock("@/components/ticker/AnalystRatingsTab", () => ({ AnalystRatingsTab: probe("analystRatings") }));
vi.mock("@/components/ticker/ValuationTab", () => ({ ValuationTab: probe("valuation") }));
vi.mock("@/components/ticker/EconomicMoatTab", () => ({ EconomicMoatTab: probe("moat") }));
vi.mock("@/components/ticker/EtfOverviewTab", () => ({ EtfOverviewTab: probe("etfOverview") }));
vi.mock("@/components/ticker/TechnicalTab", () => ({
  TechnicalTab: ({ isEtf }: { isEtf?: boolean }) => {
    mounted.push(isEtf ? "technical:etf" : "technical");
    return null;
  },
}));
vi.mock("@/components/ticker/ChartTab", () => ({
  ChartTab: ({ isEtf }: { isEtf?: boolean }) => {
    mounted.push(isEtf ? "chart:etf" : "chart");
    return null;
  },
}));

beforeEach(() => {
  mounted.length = 0;
});
afterEach(cleanup);

describe("TickerTabsContainer: detection and routing", () => {
  it("an ETF (is_etf true) renders the ETF header and exactly Overview / Technical / Chart, Overview first", () => {
    summary = { ticker: "QQQ", is_etf: true };
    render(<TickerTabsContainer ticker="QQQ" />);

    expect(screen.getByTestId("etf-header")).toBeInTheDocument();
    expect(screen.queryByTestId("stock-header")).not.toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((el) => el.textContent)).toEqual(["Overview", "Technical", "Chart"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(mounted).toEqual(["etfOverview"]);
  });

  it("the Technical and Chart tabs are the existing components, told they are on an ETF page", () => {
    summary = { ticker: "QQQ", is_etf: true };
    render(<TickerTabsContainer ticker="QQQ" />);

    fireEvent.click(screen.getByRole("tab", { name: "Technical" }));
    fireEvent.click(screen.getByRole("tab", { name: "Chart" }));

    expect(mounted).toEqual(["etfOverview", "technical:etf", "chart:etf"]);
  });

  it("no stock-only tab body (Financials, Ratios, Analysis, Valuation, Moat, Analyst Ratings) is ever mounted for an ETF", () => {
    summary = { ticker: "QQQ", is_etf: true };
    render(<TickerTabsContainer ticker="QQQ" />);
    for (const name of ["Overview", "Technical", "Chart"]) fireEvent.click(screen.getByRole("tab", { name }));

    for (const stockOnly of ["summary", "dashboard", "financials", "ratios", "analysis", "analystRatings", "valuation", "moat"]) {
      expect(mounted).not.toContain(stockOnly);
    }
  });

  it("a stock (is_etf false) keeps today's page: stock header, the ten tabs, Summary first, Dashboard second", () => {
    summary = { ticker: "AAPL", is_etf: false };
    render(<TickerTabsContainer ticker="AAPL" />);

    expect(screen.getByTestId("stock-header")).toBeInTheDocument();
    expect(screen.queryByTestId("etf-header")).not.toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((el) => el.textContent)).toEqual([
      "Summary", "Dashboard", "Financials", "Ratios", "Analysis", "Valuation", "Economic Moat", "Analyst Ratings", "Technical", "Chart",
    ]);
    expect(mounted).toEqual(["summary"]);

    fireEvent.click(screen.getByRole("tab", { name: "Technical" }));
    expect(mounted.at(-1)).toBe("technical"); // not told it is an ETF
  });

  it("the Dashboard tab is lazy-mounted: its body mounts only once the tab is opened, and Summary stays the default", () => {
    summary = { ticker: "AAPL", is_etf: false };
    render(<TickerTabsContainer ticker="AAPL" />);
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
    expect(mounted).not.toContain("dashboard");

    fireEvent.click(screen.getByRole("tab", { name: "Dashboard" }));
    expect(mounted.at(-1)).toBe("dashboard");
  });
});
