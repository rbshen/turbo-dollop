// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MomentumTable } from "@/components/momentum/MomentumTable";
import type { MomentumSnapshotRowOut } from "@/lib/api/types";

afterEach(cleanup);

const ROWS: MomentumSnapshotRowOut[] = [
  {
    ticker: "SNDK",
    company_name: "Sandisk Corporation",
    moat: "no_moat",
    return_3mo: -0.0757,
    return_6mo: 1.4658,
    return_12mo: 28.859,
    composite_score: 10.083,
    rank: 1,
    overall_score: 47,
  },
  {
    ticker: "MRVL",
    company_name: "Marvell Technology, Inc.",
    moat: "narrow_moat",
    return_3mo: 0.033,
    return_6mo: 1.593,
    return_12mo: 2.374,
    composite_score: 1.333,
    rank: 8,
    overall_score: null,
  },
];

describe("MomentumTable", () => {
  it("renders one row per ticker with rank, company, and moat badge", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByText("SNDK")).toBeInTheDocument();
    expect(screen.getByText("Sandisk Corporation")).toBeInTheDocument();
    expect(screen.getByText("No Moat")).toBeInTheDocument();
    expect(screen.getByText("Narrow Moat")).toBeInTheDocument();
  });

  it("links each ticker to its ticker page", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByRole("link", { name: "SNDK" })).toHaveAttribute("href", "/tickers/SNDK");
  });

  it("colors a negative return red and a positive return green", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByText("-7.57%")).toHaveClass("text-negative");
    expect(screen.getByText("+146.58%")).toHaveClass("text-positive");
  });

  it("renders a null overall_score as an em dash, not a fabricated 0", () => {
    render(<MomentumTable rows={[ROWS[1]]} />);
    expect(screen.getByText("—", { selector: "td:last-child" })).toBeInTheDocument();
  });

  it("renders the Overall column muted relative to the other numeric columns", () => {
    render(<MomentumTable rows={ROWS} />);
    const overallCell = screen.getAllByText("47")[0];
    expect(overallCell).toHaveClass("text-text-tertiary");
    const compositeCell = screen.getByText("+1008.30%");
    expect(compositeCell.className).not.toContain("text-text-tertiary");
  });

  it("shows the info icon next to the Overall header", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByRole("button", { name: "About the Overall column" })).toBeInTheDocument();
  });
});
