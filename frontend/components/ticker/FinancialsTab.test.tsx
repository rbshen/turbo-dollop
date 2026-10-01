// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FinancialsTab } from "@/components/ticker/FinancialsTab";

// The period switch is the segmented control under test; the tables are probes that show which period and statement
// were handed down.
vi.mock("@/components/ticker/HistoricalTrendsGrid", () => ({ HistoricalTrendsGrid: () => <div /> }));
vi.mock("@/components/ticker/FinancialsStatementTable", () => ({
  FinancialsStatementTable: ({ periodType, data }: { periodType: string; data: unknown }) => (
    <div data-testid="table" data-period={periodType}>
      {JSON.stringify(data)}
    </div>
  ),
}));

const stmt = (tag: string) => ({ annual: `${tag}-annual`, quarterly: `${tag}-quarterly` });
vi.mock("@/lib/hooks/useFinancials", () => ({
  useFinancials: () => ({
    data: {
      reported_currency: "USD",
      income_statement: stmt("income"),
      balance_sheet: stmt("balance"),
      cash_flow: stmt("cash"),
    },
    error: undefined,
  }),
}));

afterEach(cleanup);

// How the period control marks its selected option: aria-pressed (the shared control it replaced drew a brand
// fill and no ARIA).
function isOn(el: HTMLElement): boolean {
  return el.getAttribute("aria-pressed") === "true";
}

describe("FinancialsTab: the period switch", () => {
  it("is a named group of two sentence-case segments with a neutral selected state, not brand blue", () => {
    render(<FinancialsTab ticker="AAPL" />);
    expect(screen.getByRole("group", { name: "Statement period" })).toBeInTheDocument();
    const annual = screen.getByRole("button", { name: "Annual" });
    expect(screen.getByRole("button", { name: "Quarterly" })).toBeInTheDocument();
    expect(annual).toHaveClass("data-[pressed]:bg-surface-2", "data-[pressed]:text-text-primary");
    expect(annual.className).not.toMatch(/bg-brand/);
  });

  it("offers Annual and Quarterly, starting on annual", () => {
    render(<FinancialsTab ticker="AAPL" />);
    expect(screen.getByRole("button", { name: /^annual$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^quarterly$/i })).toBeInTheDocument();
    expect(screen.getByTestId("table")).toHaveAttribute("data-period", "annual");
    expect(isOn(screen.getByRole("button", { name: /^annual$/i }))).toBe(true);
    expect(isOn(screen.getByRole("button", { name: /^quarterly$/i }))).toBe(false);
  });

  it("switches the table to the quarterly figures, and back", () => {
    render(<FinancialsTab ticker="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: /^quarterly$/i }));
    expect(screen.getByTestId("table")).toHaveAttribute("data-period", "quarterly");
    expect(screen.getByTestId("table")).toHaveTextContent("income-quarterly");
    expect(isOn(screen.getByRole("button", { name: /^quarterly$/i }))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /^annual$/i }));
    expect(screen.getByTestId("table")).toHaveAttribute("data-period", "annual");
  });

  it("clicking the selected period again changes nothing", () => {
    render(<FinancialsTab ticker="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: /^annual$/i }));
    expect(screen.getByTestId("table")).toHaveAttribute("data-period", "annual");
    expect(isOn(screen.getByRole("button", { name: /^annual$/i }))).toBe(true);
  });

  it("keeps the period when the statement changes", () => {
    render(<FinancialsTab ticker="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: /^quarterly$/i }));
    fireEvent.click(screen.getByRole("button", { name: "Balance Sheet" }));
    expect(screen.getByTestId("table")).toHaveTextContent("balance-quarterly");
  });
});
