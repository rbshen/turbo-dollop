// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RatiosTable } from "@/components/ticker/RatiosTable";
import type { RatiosOut } from "@/lib/api/types";

afterEach(cleanup);

const DATA: RatiosOut = {
  ticker: "AAPL",
  periods: ["FY2024", "FY2025", "TTM"],
  groups: [
    {
      label: "Liquidity",
      items: [{ label: "Current Ratio", values: [1.1, 1.2, null], unit: "ratio", emphasis: false }],
    },
  ],
  reported_currency: null,
};

describe("RatiosTable", () => {
  it("renders body rows at the dense (h-9) height with no hover class", () => {
    render(<RatiosTable data={DATA} />);
    const row = screen.getByText("Current Ratio").closest("tr");
    expect(row).toHaveClass("h-9");
    expect(row).not.toHaveClass("hover:bg-surface");
    expect(row).not.toHaveClass("h-11");
  });

  it("renders a missing value as an em dash", () => {
    render(<RatiosTable data={DATA} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders the header row at h-9 with a sentence-case, non-uppercase label", () => {
    render(<RatiosTable data={DATA} />);
    const header = screen.getByText("Metric");
    expect(header.closest("tr")).toHaveClass("h-9");
    expect(header.className).not.toContain("uppercase");
  });
});
