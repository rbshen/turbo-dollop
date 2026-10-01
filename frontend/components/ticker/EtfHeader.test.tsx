// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EtfHeaderView } from "@/components/ticker/EtfHeader";

afterEach(cleanup);

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

  it("has no sector/industry eyebrow, score/Moat/valuation pills or next-earnings line, and one action slot", () => {
    render(<EtfHeaderView data={DATA} assetClass="Equity" actions={<button>Add to watchlist</button>} />);

    expect(screen.queryByText(/Financial Services/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Next earnings/)).not.toBeInTheDocument();
    expect(screen.queryByText(/moat/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});
