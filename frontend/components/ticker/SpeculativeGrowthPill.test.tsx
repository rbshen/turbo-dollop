// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SpeculativeGrowthPill } from "@/components/ticker/SpeculativeGrowthPill";
import type { SpeculativeGrowthOut } from "@/lib/api/types";

afterEach(cleanup);

const QUALIFYING: SpeculativeGrowthOut = {
  ticker: "0700.HK",
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
  potential_fake_growth: false,
};

describe("SpeculativeGrowthPill tooltip currency", () => {
  it("defaults the Net income (TTM) tooltip line to USD when currency is omitted", () => {
    render(<SpeculativeGrowthPill data={QUALIFYING} />);
    expect(screen.getByText("Speculative Growth").title).toContain("Net income (TTM): -$206.28M");
  });

  it("uses the given reported_currency for the Net income (TTM) tooltip line", () => {
    render(<SpeculativeGrowthPill data={QUALIFYING} currency="CNY" />);
    expect(screen.getByText("Speculative Growth").title).toContain("Net income (TTM): -CN¥206.28M");
  });
});
