// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    fireEvent.click(screen.getByRole("tab", { name: "Balance Sheet" }));
    expect(screen.getByTestId("table")).toHaveTextContent("balance-quarterly");
  });
});

// Characterization of the statement strip (Income statement, Balance sheet, Cash flow). How a strip entry is found
// and how it shows as selected are the markup-dependent parts, so they live in these two helpers.
const statementEntry = (name: string) => screen.getByRole("tab", { name });
const entrySelected = (el: HTMLElement) => el.getAttribute("aria-selected") === "true";

describe("FinancialsTab: the statement strip", () => {
  it("offers the three statements, starting on the income statement", () => {
    render(<FinancialsTab ticker="AAPL" />);
    expect(entrySelected(statementEntry("Income Statement"))).toBe(true);
    expect(entrySelected(statementEntry("Balance Sheet"))).toBe(false);
    expect(entrySelected(statementEntry("Cash Flow"))).toBe(false);
    expect(screen.getByTestId("table")).toHaveTextContent("income-annual");
  });

  it("switches the table to the chosen statement and moves the selected mark with it", () => {
    render(<FinancialsTab ticker="AAPL" />);
    fireEvent.click(statementEntry("Cash Flow"));
    expect(screen.getByTestId("table")).toHaveTextContent("cash-annual");
    expect(entrySelected(statementEntry("Cash Flow"))).toBe(true);
    expect(entrySelected(statementEntry("Income Statement"))).toBe(false);
    fireEvent.click(statementEntry("Balance Sheet"));
    expect(screen.getByTestId("table")).toHaveTextContent("balance-annual");
  });

  it("clicking the selected statement again changes nothing", () => {
    render(<FinancialsTab ticker="AAPL" />);
    fireEvent.click(statementEntry("Income Statement"));
    expect(screen.getByTestId("table")).toHaveTextContent("income-annual");
    expect(entrySelected(statementEntry("Income Statement"))).toBe(true);
  });
});

// Session 16: the strip is the shared Tabs primitive, with the neutral selected state (never brand blue).
describe("FinancialsTab: the statement strip is a neutral tab list", () => {
  it("is a named tablist of three tabs, the selected one marked by aria-selected", () => {
    render(<FinancialsTab ticker="AAPL" />);
    const list = screen.getByRole("tablist", { name: "Financial statement" });
    expect(within(list).getAllByRole("tab")).toHaveLength(3);
    expect(statementEntry("Income Statement")).toHaveAttribute("aria-selected", "true");
    expect(statementEntry("Cash Flow")).toHaveAttribute("aria-selected", "false");
  });

  it("draws the selected tab with the neutral underline and text-primary, and no brand blue", () => {
    render(<FinancialsTab ticker="AAPL" />);
    const tab = statementEntry("Income Statement");
    expect(tab).toHaveClass("data-[active]:border-text-primary", "data-[active]:text-text-primary");
    for (const name of ["Income Statement", "Balance Sheet", "Cash Flow"]) {
      expect(statementEntry(name).className).not.toMatch(/brand/);
    }
  });

  it("moves between tabs with the arrow keys and selects with Enter", async () => {
    render(<FinancialsTab ticker="AAPL" />);
    const income = statementEntry("Income Statement");
    income.focus();
    fireEvent.keyDown(income, { key: "ArrowRight" });
    await waitFor(() => expect(statementEntry("Balance Sheet")).toHaveFocus());
    fireEvent.click(statementEntry("Balance Sheet"));
    expect(screen.getByTestId("table")).toHaveTextContent("balance-annual");
  });
});
