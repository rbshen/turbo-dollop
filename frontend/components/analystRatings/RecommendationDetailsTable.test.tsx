// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RecommendationDetailsTable } from "@/components/analystRatings/RecommendationDetailsTable";
import type { RecommendationDetailsColumn } from "@/lib/api/types";

afterEach(cleanup);

const COLUMNS: RecommendationDetailsColumn[] = [
  { label: "Current", buy: 10, outperform: 5, hold: 3, underperform: 1, sell: 0, mean: 4.2, consensus: "Buy", target: 420.5 },
];

// The "Target" row is a price target (quote-domain) -- must match the
// ticker header's own price currency (see AnalystRatingsTab.tsx's currency
// wiring). Every other row is a plain count/rating, currency-irrelevant.
describe("RecommendationDetailsTable Target row currency", () => {
  it("defaults to USD when currency is omitted", () => {
    render(<RecommendationDetailsTable columns={COLUMNS} />);
    expect(screen.getByText("$420.50")).toBeInTheDocument();
  });

  it("uses the given quote_currency for the Target row", () => {
    render(<RecommendationDetailsTable columns={COLUMNS} currency="HKD" />);
    expect(screen.getByText("HK$420.50")).toBeInTheDocument();
  });
});
