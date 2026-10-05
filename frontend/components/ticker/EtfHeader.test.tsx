// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EtfHeaderView } from "@/components/ticker/EtfHeader";
import type { TrendAnalysisOut } from "@/lib/api/types";

afterEach(cleanup);

// Only the fields the Stage pill reads are set; the rest of TrendAnalysisOut is irrelevant to the header.
function trend(stage: TrendAnalysisOut["weinstein_stage"]): TrendAnalysisOut {
  return {
    weinstein_stage: stage,
    weinstein_stage_since_date: "2026-04-13",
    weinstein_stage_since_is_lower_bound: false,
    weinstein_ma_slope_pct: 1.2,
    weinstein_vs_ma_pct: 3.4,
  } as TrendAnalysisOut;
}

const DATA = {
  ticker: "QQQ",
  company_name: "Invesco QQQ Trust, Series 1",
  exchange: "NASDAQ",
  price: 612.34,
  change: -3.5,
  change_percent: -0.57,
  quote_currency: "USD",
};

describe("EtfHeaderView", () => {
  it("shows name, ticker, price, daily change and the 'Exchange-traded fund · asset class' caption", () => {
    render(<EtfHeaderView data={DATA} assetClass="Equity" actions={<button>Add to watchlist</button>} />);

    expect(screen.getByRole("heading", { name: "Invesco QQQ Trust, Series 1" })).toBeInTheDocument();
    expect(screen.getByText(/QQQ · NASDAQ/)).toBeInTheDocument();
    expect(screen.getByText("$612.34")).toBeInTheDocument();
    expect(screen.getByText(/-\$3.50/)).toBeInTheDocument();
    expect(screen.getByText("Exchange-traded fund · Equity")).toHaveClass("text-xs", "text-text-tertiary");
  });

  it("drops the asset class from the caption while /etf/info is loading or unavailable", () => {
    render(<EtfHeaderView data={DATA} assetClass={undefined} actions={null} />);
    expect(screen.getByText("Exchange-traded fund")).toBeInTheDocument();
  });

  it("renders the Weinstein Stage pill beside the price and change when trend carries a stage", () => {
    render(<EtfHeaderView data={DATA} assetClass="Equity" actions={null} trend={trend("advance")} />);

    const pill = screen.getByText("Stage 2 · Advance");
    expect(pill).toBeInTheDocument();
    // Same row as the price (the stock header's placement): the pill's row also holds the price text.
    expect(pill.closest(".flex-wrap")).toContainElement(screen.getByText("$612.34"));
  });

  it.each([
    ["trend is undefined", undefined],
    ["trend is null", null],
    ["trend has no weinstein_stage", trend(null)],
  ])("renders no Stage pill when %s", (_label, value) => {
    render(<EtfHeaderView data={DATA} assetClass="Equity" actions={null} trend={value} />);
    expect(screen.queryByText(/Stage \d/)).not.toBeInTheDocument();
  });

  it("has no sector/industry eyebrow, score/Moat/valuation pills or next-earnings line, and one action slot", () => {
    render(<EtfHeaderView data={DATA} assetClass="Equity" actions={<button>Add to watchlist</button>} />);

    expect(screen.queryByText(/Financial Services/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Next earnings/)).not.toBeInTheDocument();
    expect(screen.queryByText(/moat/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});
