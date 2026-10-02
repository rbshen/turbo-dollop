// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MomentumTable } from "@/components/momentum/MomentumTable";
import type { MomentumSnapshotRowOut } from "@/lib/api/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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
    return_1w: 0.0123,
    return_1mo: -0.0456,
    last_price: 1234.5,
    quote_currency: "USD",
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
    return_1w: 0.005,
    return_1mo: 0.02,
    last_price: null,
    quote_currency: null,
  },
];

describe("MomentumTable", () => {
  it("renders one row per ticker with rank, company, and moat badge", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByText("SNDK")).toBeInTheDocument();
    expect(screen.getByText("Sandisk Corporation")).toBeInTheDocument();
    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.getByText("Narrow")).toBeInTheDocument();
  });

  it("links each ticker to its ticker page, opening in a new tab", () => {
    render(<MomentumTable rows={ROWS} />);
    const link = screen.getByRole("link", { name: "SNDK" });
    expect(link).toHaveAttribute("href", "/tickers/SNDK");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("colors a negative return red and a positive return green", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByText("-7.57%")).toHaveClass("text-negative");
    expect(screen.getByText("+146.58%")).toHaveClass("text-positive");
  });

  it("renders a null overall_score as an em dash, not a fabricated 0", () => {
    render(<MomentumTable rows={[{ ...ROWS[1], last_price: 10 }]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders the Score column as a neutral (never sign-colored) badge", () => {
    render(<MomentumTable rows={ROWS} />);
    const overallCell = screen.getAllByText("47")[0];
    expect(overallCell).toHaveClass("text-text-secondary");
    const compositeCell = screen.getByText("+1008.30%");
    expect(compositeCell.className).not.toContain("text-text-secondary");
  });

  it("renders an empty-snapshot caption instead of an empty table", () => {
    render(<MomentumTable rows={[]} />);
    expect(screen.getByText("No tickers in this snapshot.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("MomentumTable whole-row click", () => {
  beforeEach(() => {
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  it("opens the ticker page in a new tab when a non-link cell is clicked", () => {
    render(<MomentumTable rows={ROWS} />);
    // Any cell that isn't the ticker anchor itself -- the company name line.
    screen.getByText("Sandisk Corporation").click();
    expect(window.open).toHaveBeenCalledTimes(1);
    expect(window.open).toHaveBeenCalledWith("/tickers/SNDK", "_blank", "noopener,noreferrer");
  });

  it("does not double-open when the ticker anchor itself is clicked", () => {
    render(<MomentumTable rows={ROWS} />);
    screen.getByRole("link", { name: "SNDK" }).click();
    expect(window.open).not.toHaveBeenCalled();
  });

  it("shows 1w/1mo returns, and a dash when they are missing", () => {
    render(<MomentumTable rows={[ROWS[0], { ...ROWS[1], return_1w: null, return_1mo: null }]} />);
    expect(screen.getByText("1 w")).toBeInTheDocument();
    expect(screen.getByText("1 mo")).toBeInTheDocument();
    const sndk = screen.getByText("SNDK").closest("tr")!;
    expect(sndk).toHaveTextContent("1.23%");
    expect(sndk).toHaveTextContent("-4.56%");
    const mrvl = screen.getByText("MRVL").closest("tr")!;
    expect(mrvl.querySelectorAll("td")[4]).toHaveTextContent("—");
    expect(mrvl.querySelectorAll("td")[5]).toHaveTextContent("—");
  });

  it("shows the last price after the ticker, and a dash when uncached", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByText("Last")).toBeInTheDocument();
    const sndk = screen.getByText("SNDK").closest("tr")!;
    expect(sndk.querySelectorAll("td")[2]).toHaveTextContent("$1,234.50");
    const mrvl = screen.getByText("MRVL").closest("tr")!;
    expect(mrvl.querySelectorAll("td")[2]).toHaveTextContent("—");
  });
});
