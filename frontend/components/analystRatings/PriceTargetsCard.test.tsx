// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PriceTargetsCard } from "@/components/analystRatings/PriceTargetsCard";
import type { PriceTargetSummary } from "@/lib/api/types";

afterEach(cleanup);

const DATA: PriceTargetSummary = {
  current_price: 380.0,
  target_consensus: 420.5,
  target_high: 480.0,
  target_low: 350.0,
  target_median: 415.0,
  upside_pct: 10.66,
};

// Price targets are quote-domain -- must match the ticker header's own
// price currency (see AnalystRatingsTab.tsx's currency wiring).
describe("PriceTargetsCard currency", () => {
  it("defaults to USD when currency is omitted", () => {
    render(<PriceTargetsCard data={DATA} />);
    expect(screen.getByText("$350.00")).toBeInTheDocument();
    expect(screen.getByText("$420.50")).toBeInTheDocument();
    expect(screen.getByText("$480.00")).toBeInTheDocument();
  });

  it("uses the given quote_currency for every price target figure", () => {
    render(<PriceTargetsCard data={DATA} currency="HKD" />);
    expect(screen.getByText("HK$350.00")).toBeInTheDocument();
    expect(screen.getByText("HK$420.50")).toBeInTheDocument();
    expect(screen.getByText("HK$480.00")).toBeInTheDocument();
  });
});
