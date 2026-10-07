// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MomentumTable } from "@/components/momentum/MomentumTable";
import type { EtfMomentumRowOut, MomentumSnapshotRowOut } from "@/lib/api/types";

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

describe("MomentumTable showMoatAndScore={false}", () => {
  const ETF_ROWS: EtfMomentumRowOut[] = [
    {
      ticker: "SOXL",
      company_name: "Direxion Daily Semiconductor Bull 3X",
      return_3mo: 0.4,
      return_6mo: 0.9,
      return_12mo: 2.1,
      composite_score: 1.1333,
      rank: 1,
      return_1w: 0.02,
      return_1mo: null,
      last_price: 55.25,
    },
  ];

  it("hides the Moat and Score columns but keeps every other column", () => {
    render(<MomentumTable rows={ROWS} showMoatAndScore={false} />);
    expect(screen.queryByText("Moat")).not.toBeInTheDocument();
    expect(screen.queryByText("Score")).not.toBeInTheDocument();
    expect(screen.queryByText("None")).not.toBeInTheDocument();
    expect(screen.queryByText("47")).not.toBeInTheDocument();
    for (const name of ["Rank", "Ticker", "Last", "1 w", "1 mo", "3 mo", "6 mo", "12 mo", "Composite"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("columnheader")).toHaveLength(9);
    expect(screen.getByText("SNDK").closest("tr")!.querySelectorAll("td")).toHaveLength(9);
  });

  it("renders ETF rows (no moat/score/currency fields) with USD formatting and a dash for a missing 1 mo", () => {
    render(<MomentumTable rows={ETF_ROWS} showMoatAndScore={false} />);
    const row = screen.getByText("SOXL").closest("tr")!;
    expect(screen.getByText("Direxion Daily Semiconductor Bull 3X")).toBeInTheDocument();
    const cells = row.querySelectorAll("td");
    expect(cells).toHaveLength(9);
    expect(cells[2]).toHaveTextContent("$55.25");
    expect(cells[3]).toHaveTextContent("+2.00%");
    expect(cells[4]).toHaveTextContent("—");
    expect(cells[8]).toHaveTextContent("+113.33%");
  });

  it("shows both columns by default", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getByText("Moat")).toBeInTheDocument();
    expect(screen.getByText("Score")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(11);
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

describe("MomentumTable Review marker", () => {
  const REASON = {
    step: "step5" as const,
    score: 25,
    verdict: "Fail",
    hint: "unclear" as const,
    raw_hint: "unclear" as const,
    guarded: false,
    rule: "not_covered",
    evidence: "Current Ratio 0.59 (severe): below 1.0 in 1 of the last 5 fiscal years and 3 of the last 8 quarters",
  };
  const reviewed = (row: MomentumSnapshotRowOut, status: MomentumSnapshotRowOut["review_status"]): MomentumSnapshotRowOut => ({
    ...row,
    overall_verdict: "Pass",
    review_status: status,
    review_reasons: status ? [REASON] : null,
    conviction: status ? "high" : null,
  });
  const scoreCell = (ticker: string) => {
    const cells = (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td");
    return cells[cells.length - 1] as HTMLElement;
  };

  it.each([
    ["review_structural", "Review (structural)"],
    ["review_unclear", "Review (unclear)"],
    ["review_by_design", "Review (by design)"],
    ["data_uncertain", "Data uncertain"],
  ] as const)("%s draws the icon marker beside the unchanged neutral score badge", (status, label) => {
    render(<MomentumTable rows={[reviewed({ ...ROWS[0], overall_score: 79 }, status)]} />);
    const marker = scoreCell("SNDK").querySelector("[data-testid='review-marker']") as HTMLElement;
    expect(marker).toHaveTextContent(label);
    expect(marker.getAttribute("title")).toBe(`Overall 79 would read Pass. Debt scored 25 (May not pass). ${REASON.evidence}. Conviction: high.`);
    const score = screen.getByText("79");
    expect(score).toHaveClass("text-text-secondary"); // still the neutral pill
    expect(scoreCell("SNDK").querySelector("span[title]:not([data-testid])")).toBeNull(); // no other tooltip added
  });

  it("renders no marker without a status, or for a row that predates the fields", () => {
    render(<MomentumTable rows={[reviewed(ROWS[0], null), ROWS[1]]} />);
    expect(document.querySelector("[data-testid='review-marker']")).toBeNull();
    expect(scoreCell("SNDK")).toHaveTextContent("47");
  });

  it("keeps the snapshot's own order (rank), whatever the statuses and scores", () => {
    const rows = [
      reviewed({ ...ROWS[0], ticker: "ONE", rank: 1, overall_score: 40 }, "review_unclear"),
      reviewed({ ...ROWS[1], ticker: "TWO", rank: 2, overall_score: 90 }, null),
      reviewed({ ...ROWS[1], ticker: "THREE", rank: 3, overall_score: 60 }, "data_uncertain"),
    ];
    render(<MomentumTable rows={rows} />);
    const order = [...document.querySelectorAll("tbody tr")].map((tr) => tr.querySelectorAll("td")[0].textContent);
    expect(order).toEqual(["1", "2", "3"]);
  });

  it("the ETF table (no Moat/Score columns) never shows a marker", () => {
    render(<MomentumTable rows={[reviewed(ROWS[0], "review_unclear")]} showMoatAndScore={false} />);
    expect(document.querySelector("[data-testid='review-marker']")).toBeNull();
  });
});
