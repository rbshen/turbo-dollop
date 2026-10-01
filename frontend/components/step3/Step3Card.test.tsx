// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Step3Card } from "@/components/step3/Step3Card";
import type { Step3Out } from "@/lib/api/types";

// The right-hand panel and the gauge are their own components with their own tests; only this card's own labels
// are under test here.
vi.mock("@/components/step3/ManualCalculationPanel", () => ({ ManualCalculationPanel: () => <div /> }));
vi.mock("@/components/step3/ValuationGauge", () => ({ ValuationGauge: () => <div /> }));

let data: Step3Out | undefined;
vi.mock("@/lib/hooks/useStep3", () => ({ useStep3: () => ({ data, error: undefined }) }));

afterEach(cleanup);

function makeData(method: string, extra: Record<string, unknown> = {}): Step3Out {
  return {
    ticker: "ACME",
    selected_method: method,
    method_reasoning: [],
    discount_premium_pct: 0.1,
    pb_bands: null,
    inputs: {
      growth_yr_1_5: 0.1,
      growth_yr_1_5_source: "Analyst consensus",
      growth_yr_6_10: 0.08,
      growth_yr_11_20: 0.04,
      current_value: 40e9,
      current_value_label: "Operating Cash Flow (Current)",
      discount_rate: 0.085,
      shares_outstanding: 1e9,
      total_debt: 12e9,
      cash_and_st_investments: 5e9,
      cash_and_st_investments_includes_short_term_investments: true,
      sales_per_share: 12.5,
      projected_growth_rate: 0.3,
      fair_psg_ratio: 1.2,
      quote_currency: "USD",
      last_close: 150,
    },
    ...extra,
  } as unknown as Step3Out;
}

const labels = () => Array.from(document.querySelectorAll("tbody tr td:first-child > div:first-child")).map((el) => el.textContent);

describe("Step3Card: the Model Valuation labels", () => {
  it("shows the method in the title", () => {
    data = makeData("DCF");
    render(<Step3Card ticker="ACME" />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Model valuation · Discounted cash flow (operating CF)");
  });

  it("labels the twenty-year rows", () => {
    data = makeData("DCF");
    render(<Step3Card ticker="ACME" />);
    expect(labels()).toEqual([
      "Discount/premium",
      "Growth yr 1-5",
      "Growth yr 6-10",
      "Growth yr 11-20 (terminal)",
      "Operating cash flow (current)",
      "Discount rate (CAPM)",
      "Shares outstanding",
      "Total debt",
      "Cash + ST investments",
    ]);
  });

  it("labels the price-to-sales-growth rows", () => {
    data = makeData("PSG");
    render(<Step3Card ticker="ACME" />);
    expect(labels()).toEqual(["Discount/premium", "Sales per share", "Projected growth rate", "Fair PSG ratio"]);
  });

  it("re-cases the backend's current-value label, whatever shape it comes in", () => {
    data = makeData("DFCF", { inputs: { ...makeData("DFCF").inputs, current_value_label: "Free Cash Flow (Normalized, 5yr avg CapEx)" } });
    render(<Step3Card ticker="ACME" />);
    expect(labels()).toContain("Free cash flow (normalized, 5yr avg CapEx)");
  });

  it("keeps the method reasoning summary, in sentence case with no uppercase styling", () => {
    data = makeData("DCF");
    render(<Step3Card ticker="ACME" />);
    const summary = screen.getByText("Method selection reasoning");
    expect(summary.className).not.toMatch(/uppercase|tracking-widest/);
  });

  it("sentence-cases the price-to-book band labels and the last-close row", () => {
    data = makeData("PRICE_TO_BOOK_STANDARD", {
      pb_bands: { minus_2sd: 10, minus_1sd: 12, mean: 15, plus_1sd: 18, plus_2sd: 20 },
    });
    render(<Step3Card ticker="ACME" />);
    expect(screen.getByText("Intrinsic value")).toBeInTheDocument();
    expect(screen.getByText("Last close")).toBeInTheDocument();
  });
});
