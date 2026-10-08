// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AssessmentChipView, TickerHeaderView } from "@/components/ticker/TickerHeader";
import type { SpeculativeGrowthOut } from "@/lib/api/types";

afterEach(cleanup);

// A header that qualifies for Speculative growth, with the fake-growth flag on, so both icon buttons render.
const SPECULATIVE = { ticker: "CRWD", qualifies: true, potential_fake_growth: true } as SpeculativeGrowthOut;
const DATA = {
  ticker: "CRWD",
  company_name: "CrowdStrike",
  exchange: "NASDAQ",
  sector: null,
  industry: null,
  index_memberships: [],
  price: 400,
  change: 1,
  change_percent: 0.25,
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
} as unknown as Parameters<typeof TickerHeaderView>[0]["data"];

function header() {
  return render(
    <TickerHeaderView data={DATA} assessment={null} actions={null} moat={null} specGrowth={SPECULATIVE} trend={null} />,
  );
}

describe("TickerHeaderView: the Speculative growth tooltips", () => {
  it("sit in the nowrap pill group, so each bubble has to set its own whitespace-normal", () => {
    header();
    for (const name of ["About Speculative Growth", "Potential fake growth warning"]) {
      const button = screen.getByRole("button", { name });
      fireEvent.mouseEnter(button);
    }
    const group = screen.getByRole("button", { name: "About Speculative Growth" }).closest(".whitespace-nowrap");
    expect(group).not.toBeNull();
    const tooltips = screen.getAllByRole("tooltip");
    expect(tooltips).toHaveLength(2);
    for (const tooltip of tooltips) {
      expect(group).toContainElement(tooltip);
      expect(tooltip).toHaveClass("whitespace-normal");
    }
  });

  it("anchor to the pill row below md: the row is the positioned ancestor and the icon wrappers are static", () => {
    header();
    const info = screen.getByRole("button", { name: "About Speculative Growth" });
    const wrapper = info.parentElement!;
    expect(wrapper).toHaveClass("static", "md:relative");
    const row = wrapper.parentElement!.parentElement!;
    expect(row).toHaveClass("relative", "flex-wrap");
  });
});

describe("AssessmentChipView", () => {
  const ROW = {
    overall_score: 78,
    overall_verdict: "Pass with caution",
    computed_at: "2026-10-06T03:38:00",
    moat: "wide_moat",
  } as unknown as NonNullable<Parameters<typeof AssessmentChipView>[0]["data"]>;

  it("shows the plain verdict chip with the as-of time as its tooltip", () => {
    render(<AssessmentChipView data={ROW} />);
    const chip = screen.getByText("Pass with caution");
    expect(chip).toHaveClass("text-caution");
    expect(chip).toHaveAttribute("title", expect.stringContaining("As of"));
    expect(screen.queryByTestId("moat-not-rated-note")).not.toBeInTheDocument();
  });

  it("renders nothing without a computed score", () => {
    const { container } = render(<AssessmentChipView data={{ ...ROW, overall_score: null } as typeof ROW} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the 'Moat not rated, scored as No moat' note beside the verdict chip (and in its tooltip) for an unrated ticker only", () => {
    const unrated = { ...ROW, moat: null, overall_score: 56, overall_verdict: "Fail" } as typeof ROW;
    const { rerender } = render(<AssessmentChipView data={unrated} />);
    expect(screen.getByText("May not pass")).toHaveAttribute("title", expect.stringContaining("Moat not rated, scored as No moat."));
    expect(screen.getByTestId("moat-not-rated-note")).toHaveTextContent("Moat not rated, scored as No moat");
    expect(screen.queryByText("Moat not rated")).not.toBeInTheDocument(); // no verdict pill of that name any more
    rerender(<AssessmentChipView data={{ ...unrated, moat: "wide_moat" } as typeof ROW} />);
    expect(screen.queryByTestId("moat-not-rated-note")).not.toBeInTheDocument();
  });
});
