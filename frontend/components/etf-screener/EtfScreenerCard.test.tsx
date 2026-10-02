// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EtfScreenerCard } from "@/components/etf-screener/EtfScreenerCard";
import type { EtfScreenerRowOut } from "@/lib/api/types";

afterEach(cleanup);

const ROW: EtfScreenerRowOut = {
  ticker: "SPY",
  name: "SPDR S&P 500 ETF Trust",
  asset_class: "Equity",
  expense_ratio: 0.09,
  aum: 5.2e11,
  last_price: 601.23,
  pct_change_1d: -0.45,
  beta: 1,
  return_1y: 18,
  vs_spy_1y: 3.46,
  weinstein_stage: "advance",
  weinstein_stage_since_date: "2026-03-02",
  weinstein_stage_since_is_lower_bound: false,
  weinstein_ma_slope_pct: 1.2,
  weinstein_vs_ma_pct: 4.5,
  weinstein_pending_direction: null,
  bb_rsi_entry_signal: null,
  warren_active_signal_kind: null,
  warren_last_buy_fired_at: null,
  as_of_date: "2026-10-01",
  info_updated_at: null,
  updated_at: null,
};

// The value printed under a label ("Quote" -> "$601.23").
const value = (label: string) => screen.getByText(label).nextElementSibling?.textContent;

describe("EtfScreenerCard", () => {
  it("is one link to the ticker page that opens in a new tab", () => {
    render(<EtfScreenerCard data={ROW} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/tickers/SPY");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link).toContainElement(screen.getByText("SPDR S&P 500 ETF Trust"));
  });

  it("shows the ticker, name, asset class, stage pill and every figure", () => {
    render(<EtfScreenerCard data={ROW} />);
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("Stage 2 · Advance")).toBeInTheDocument();
    expect(value("Quote")).toBe("$601.23");
    expect(value("1D")).toBe("-0.45%");
    expect(value("AUM")).toBe("$520.00B");
    expect(value("Exp. ratio")).toBe("0.09%");
    expect(value("1Y vs SPY")).toBe("+3.5 pp");
    expect(value("Beta")).toBe("1.00");
  });

  it("colours the 1D change and the relative figure by sign", () => {
    render(<EtfScreenerCard data={ROW} />);
    expect(screen.getByText("-0.45%")).toHaveClass("text-negative");
    expect(screen.getByText("+3.5 pp")).toHaveClass("text-positive");
  });

  it("renders a dash for a null beta (a non-equity fund) and for every other missing value", () => {
    render(
      <EtfScreenerCard
        data={{
          ...ROW,
          name: null,
          asset_class: null,
          beta: null,
          aum: null,
          expense_ratio: null,
          last_price: null,
          pct_change_1d: null,
          vs_spy_1y: null,
          weinstein_stage: null,
        }}
      />
    );
    for (const label of ["Quote", "1D", "AUM", "Exp. ratio", "1Y vs SPY", "Beta"]) expect(value(label)).toBe("—");
    expect(screen.getByText("Unclassified")).toBeInTheDocument();
    expect(screen.queryByText("Stage 2 · Advance")).not.toBeInTheDocument();
  });

  it("writes a multi-word asset class in sentence case", () => {
    render(<EtfScreenerCard data={{ ...ROW, asset_class: "Fixed Income" }} />);
    expect(screen.getByText("Fixed income")).toBeInTheDocument();
  });
});
