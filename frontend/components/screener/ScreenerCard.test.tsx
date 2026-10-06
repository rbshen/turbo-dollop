// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScreenerCard } from "@/components/screener/ScreenerCard";
import type { ReviewReason, TickerScoreOut } from "@/lib/api/types";

afterEach(cleanup);

const REASON: ReviewReason = {
  step: "step5",
  score: 25,
  verdict: "Fail",
  hint: "unclear",
  raw_hint: "unclear",
  guarded: false,
  rule: "not_covered",
  evidence: "Current Ratio 0.59 (severe): below 1.0 in 1 of the last 5 fiscal years and 3 of the last 8 quarters",
};

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

describe("ScreenerCard Review pill", () => {
  it("shows the pill beside the unchanged score and verdict, with the reason in its tooltip", () => {
    render(
      <ScreenerCard data={card({ review_status: "review_unclear", review_reasons: [REASON], conviction: "high" })} />,
    );
    expect(screen.getByText("79")).toBeInTheDocument();
    expect(screen.getByText("Pass")).toBeInTheDocument();
    const pill = screen.getByText("Review (unclear)");
    expect(pill.getAttribute("title")).toContain("Overall 79 would read Pass.");
    expect(pill.getAttribute("title")).toContain(REASON.evidence);
    expect(pill.getAttribute("title")).toContain("Conviction: high.");
  });

  it("shows Data uncertain in its own label", () => {
    render(
      <ScreenerCard
        data={card({ review_status: "data_uncertain", review_reasons: [{ ...REASON, guarded: true, hint: "data_uncertain" }], conviction: "high" })}
      />,
    );
    expect(screen.getByText("Data uncertain")).toBeInTheDocument();
    expect(screen.getByText("Data uncertain").getAttribute("title")).toContain("If the data is confirmed this would read Review (unclear).");
  });

  it("renders no pill for a row without a status, and the score and verdict are the same", () => {
    render(<ScreenerCard data={card({ review_status: null, review_reasons: null, conviction: "high" })} />);
    expect(screen.queryByText(/Review \(|Data uncertain/)).toBeNull();
    expect(screen.getByText("79")).toBeInTheDocument();
    expect(screen.getByText("Pass")).toBeInTheDocument();
  });

  it("renders no pill for a payload that predates the fields", () => {
    render(<ScreenerCard data={card()} />);
    expect(screen.queryByText(/Review \(|Data uncertain/)).toBeNull();
  });

  it("an Incomplete card (no score) shows no pill", () => {
    render(
      <ScreenerCard data={card({ overall_score: null, overall_verdict: null, review_status: "review_unclear", review_reasons: [REASON] })} />,
    );
    expect(screen.getByText("Incomplete")).toBeInTheDocument();
    expect(screen.queryByText("Review (unclear)")).toBeNull();
  });
});
