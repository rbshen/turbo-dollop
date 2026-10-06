// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FinancialsStatementTable } from "@/components/ticker/FinancialsStatementTable";
import type { DataQualityFlag, FinancialsPeriodOut } from "@/lib/api/types";

afterEach(cleanup);

const annual: FinancialsPeriodOut = {
  periods: ["2025-06-30", "2026-06-30", "TTM (2026-06-30)"],
  groups: [{ label: null, items: [{ label: "Operating cash flow", values: [100, 0, 0], unit: "money", emphasis: false }] }],
};
const quarterly: FinancialsPeriodOut = {
  periods: ["Q3 2026", "Q4 2026"],
  groups: [{ label: null, items: [{ label: "Operating cash flow", values: [50, 0], unit: "money", emphasis: false }] }],
};
const placeholder: DataQualityFlag = {
  rule: "placeholder_cf",
  statement: "cash_flow",
  period: "quarterly",
  period_end: "2026-06-30",
  column: "Q4 2026",
  evidence: "all cash-flow section totals are 0 while net income is 100",
  detail: { net_income: 100, in_ttm_window: true },
};

function markersOf(container: HTMLElement) {
  return Array.from(container.querySelectorAll('[role="img"]')).map((el) => el.getAttribute("aria-label"));
}

describe("FinancialsStatementTable data-quality markers", () => {
  it("marks the flagged quarter's header and leaves the values exactly as given", () => {
    const { container } = render(
      <FinancialsStatementTable ticker="AZO" periodType="quarterly" data={quarterly} statement="cash_flow" dataQuality={[placeholder]} />,
    );

    expect(markersOf(container)).toEqual(["No cash flow reported for this period — $0 is a placeholder, not a result."]);
    const marker = container.querySelector('[role="img"]')!;
    expect(marker).toHaveAttribute("title", expect.stringContaining("net income is 100"));
    expect(marker.parentElement).toHaveTextContent("Q4 2026");
    // $0 stays $0: nothing is hidden or replaced
    expect(screen.getAllByText("0.00").length).toBeGreaterThan(0);
  });

  it("marks the annual table's TTM column with the understated-TTM sentence", () => {
    const { container } = render(
      <FinancialsStatementTable ticker="AZO" periodType="annual" data={annual} statement="cash_flow" dataQuality={[placeholder]} />,
    );

    expect(markersOf(container)).toEqual([
      "TTM sums the last four quarters as returned, including a placeholder quarter, so it is understated. The Analysis tab uses the last four valid quarters.",
    ]);
    expect(container.querySelector('[role="img"]')!.parentElement).toHaveTextContent("TTM (2026-06-30)");
  });

  it("shows no marker on another statement's table, or without flags", () => {
    expect(markersOf(render(<FinancialsStatementTable ticker="AZO" periodType="annual" data={annual} statement="income" dataQuality={[placeholder]} />).container)).toEqual([]);
    cleanup();
    expect(markersOf(render(<FinancialsStatementTable ticker="AZO" periodType="annual" data={annual} statement="cash_flow" />).container)).toEqual([]);
  });
});
