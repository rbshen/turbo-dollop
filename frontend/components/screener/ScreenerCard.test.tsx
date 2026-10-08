// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScreenerCard } from "@/components/screener/ScreenerCard";
import type { TickerScoreOut } from "@/lib/api/types";

afterEach(cleanup);

function card(overrides: Partial<TickerScoreOut> = {}): TickerScoreOut {
  return {
    ticker: "YUM",
    company_name: "Yum! Brands",
    sector: "Consumer Cyclical",
    company_type: "Standard",
    overall_score: 79,
    overall_verdict: "Pass",
    last_price: 150,
    quote_currency: "USD",
    market_cap: 40_000_000_000,
    pe_ratio: 28,
    beta: 0.8,
    moat: null,
    valuation_verdict: null,
    perf_5y_vs_spy_status: null,
    weinstein_stage: null,
    speculative_growth_qualifies: null,
    ...overrides,
  } as TickerScoreOut;
}

describe("ScreenerCard score", () => {
  it("shows the score and verdict", () => {
    render(<ScreenerCard data={card()} />);
    expect(screen.getByText("79")).toBeInTheDocument();
    expect(screen.getByText("Pass")).toBeInTheDocument();
  });

  it("an Incomplete card (no score) says so", () => {
    render(<ScreenerCard data={card({ overall_score: null, overall_verdict: null })} />);
    expect(screen.getByText("Incomplete")).toBeInTheDocument();
  });
});
