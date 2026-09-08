// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SpeculativeGrowthInfoIcon, SPECULATIVE_GROWTH_INFO_COPY } from "@/components/ticker/SpeculativeGrowthInfoIcon";
import { SpeculativeGrowthPill } from "@/components/ticker/SpeculativeGrowthPill";
import type { SpeculativeGrowthOut } from "@/lib/api/types";

afterEach(cleanup);

// Same base fixture as the qualifying tickers found in the Speculative
// Growth universe scan (e.g. NET) -- only `qualifies` varies per test.
const QUALIFYING: SpeculativeGrowthOut = {
  ticker: "NET",
  qualifies: true,
  company_type: "Standard",
  not_applicable_reason: null,
  moat: "wide_moat",
  growth_rate_pct: 41.99,
  growth_basis: "revenue",
  trailing_revenue_growth_pct: 28.0,
  gross_margin_ttm_pct: 77.0,
  net_income_ttm: -206_275_000,
  cfo_ttm: 50_000_000,
  cfo_recent_direction: "turning_positive",
  cash_and_st_investments: 1_600_000_000,
  cash_runway_years: null,
  price_to_sales_ttm: 20.0,
  psg_ratio: null,
};

const NOT_QUALIFYING: SpeculativeGrowthOut = { ...QUALIFYING, ticker: "MSFT", qualifies: false };

// Mirrors TickerHeader.tsx's exact gating JSX (`<SpeculativeGrowthPill .../>`
// immediately followed by `{data?.qualifies && <SpeculativeGrowthInfoIcon />}`)
// without pulling in TickerHeader's own SWR data hooks, which this icon's
// behavior doesn't depend on.
function PillWithIcon({ data }: { data: SpeculativeGrowthOut | null }) {
  return (
    <span>
      <SpeculativeGrowthPill data={data} variant="flat" />
      {data?.qualifies && <SpeculativeGrowthInfoIcon />}
    </span>
  );
}

describe("SpeculativeGrowthInfoIcon pairing with the pill", () => {
  it("renders the info icon alongside the pill when qualifies=true", () => {
    render(<PillWithIcon data={QUALIFYING} />);
    expect(screen.getByText("Speculative Growth")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About Speculative Growth" })).toBeInTheDocument();
  });

  it("renders neither the pill nor the icon when qualifies=false", () => {
    render(<PillWithIcon data={NOT_QUALIFYING} />);
    expect(screen.queryByText("Speculative Growth")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "About Speculative Growth" })).not.toBeInTheDocument();
  });

  it("renders neither the pill nor the icon when data hasn't loaded yet (null)", () => {
    render(<PillWithIcon data={null} />);
    expect(screen.queryByText("Speculative Growth")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "About Speculative Growth" })).not.toBeInTheDocument();
  });
});

describe("SpeculativeGrowthInfoIcon tooltip behavior", () => {
  it("tooltip is not in the document until hovered/tapped", () => {
    render(<SpeculativeGrowthInfoIcon />);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows the exact fixed copy on hover, and hides it again on mouse-leave", () => {
    render(<SpeculativeGrowthInfoIcon />);
    const button = screen.getByRole("button", { name: "About Speculative Growth" });

    fireEvent.mouseEnter(button);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent(SPECULATIVE_GROWTH_INFO_COPY);

    fireEvent.mouseLeave(button);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows the tooltip on keyboard focus, and hides it on blur", () => {
    render(<SpeculativeGrowthInfoIcon />);
    const button = screen.getByRole("button", { name: "About Speculative Growth" });

    fireEvent.focus(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent(SPECULATIVE_GROWTH_INFO_COPY);

    fireEvent.blur(button);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("tap (click) toggles the tooltip open, then closed, on touch devices where hover never fires", () => {
    render(<SpeculativeGrowthInfoIcon />);
    const button = screen.getByRole("button", { name: "About Speculative Growth" });

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.click(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent(SPECULATIVE_GROWTH_INFO_COPY);

    fireEvent.click(button);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("tooltip panel is absolutely positioned so it never affects layout while open or closed", () => {
    render(<SpeculativeGrowthInfoIcon />);
    const button = screen.getByRole("button", { name: "About Speculative Growth" });
    fireEvent.mouseEnter(button);
    expect(screen.getByRole("tooltip").className).toContain("absolute");
  });
});
