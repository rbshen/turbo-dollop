// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MarketBreadthStats } from "@/components/breadth/MarketBreadthStats";
import type { MarketBreadthPointOut } from "@/lib/api/types";

afterEach(cleanup);

const latest: MarketBreadthPointOut = {
  as_of_date: "2026-09-18", pct_above_sma20: 17.89, pct_above_sma50: 27.83, pct_above_sma200: 49.3, sma20_above: 90, sma50_above: 140,
  sma200_above: 247, new_highs: 5, new_lows: 29, net_new_highs: -24, constituents: 503, stale_excluded: 0, sma20_eligible: 503,
  sma50_eligible: 503, sma200_eligible: 501, hl_eligible: 500, is_backfilled: false,
};

describe("MarketBreadthStats", () => {
  it("lays the tiles out 20-day, 50-day, 200-day, net new highs", () => {
    render(<MarketBreadthStats latest={latest} />);
    const labels = screen.getAllByText(/SMA$|52-week highs$/).map((el) => el.textContent);
    expect(labels).toEqual(["Above 20-day SMA", "Above 50-day SMA", "Above 200-day SMA", "Net new 52-week highs"]);
  });

  it("shows each reading with its own numerator and denominator", () => {
    render(<MarketBreadthStats latest={latest} />);
    expect(screen.getByText("17.9%")).toBeInTheDocument();
    expect(screen.getByText("90 of 503 stocks")).toBeInTheDocument();
    expect(screen.getByText("27.8%")).toBeInTheDocument();
    expect(screen.getByText("140 of 503 stocks")).toBeInTheDocument();
    expect(screen.getByText("49.3%")).toBeInTheDocument();
    expect(screen.getByText("247 of 501 stocks")).toBeInTheDocument();
  });

  it("does not print 'null of null' for a row with no 20-day reading yet", () => {
    render(<MarketBreadthStats latest={{ ...latest, pct_above_sma20: null, sma20_above: null, sma20_eligible: null }} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Not computed yet")).toBeInTheDocument();
    expect(screen.queryByText(/null/)).not.toBeInTheDocument();
  });
});
