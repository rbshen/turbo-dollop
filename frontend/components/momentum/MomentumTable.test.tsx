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

  it("renders a null overall_verdict as the missing placeholder, not a fabricated verdict", () => {
    render(<MomentumTable rows={[{ ...ROWS[1], last_price: 10 }]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("no longer draws the Overall score number anywhere", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.queryByText("47")).not.toBeInTheDocument();
    expect(screen.queryByText("Score")).not.toBeInTheDocument();
  });

  it("orders the stock columns Rank, Ticker, Last, Overall verdict, Moat, 1 w ... Composite (no Score)", () => {
    render(<MomentumTable rows={ROWS} />);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Rank", "Ticker", "Last", "Overall verdict", "Moat", "1 w", "1 mo", "3 mo", "6 mo", "12 mo", "Composite",
    ]);
  });

  it("renders an empty-snapshot caption instead of an empty table", () => {
    render(<MomentumTable rows={[]} />);
    expect(screen.getByText("No tickers in this snapshot.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("MomentumTable showMoatAndScore={false}", () => {
  const withVerdictRows: MomentumSnapshotRowOut[] = [{ ...ROWS[0], overall_verdict: "Pass with caution" }];
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

  it("hides the Overall verdict and Moat columns but keeps every other column", () => {
    render(<MomentumTable rows={withVerdictRows} showMoatAndScore={false} />);
    expect(screen.queryByText("Moat")).not.toBeInTheDocument();
    expect(screen.queryByText("Overall verdict")).not.toBeInTheDocument();
    expect(screen.queryByText("None")).not.toBeInTheDocument();
    expect(screen.queryByText("Pass with caution")).not.toBeInTheDocument();
    for (const name of ["Rank", "Ticker", "Last", "1 w", "1 mo", "3 mo", "6 mo", "12 mo", "Composite"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("columnheader")).toHaveLength(9);
    expect(screen.getByText("SNDK").closest("tr")!.querySelectorAll("td")).toHaveLength(9);
  });

  it("renders ETF rows (no moat/verdict/currency fields) with USD formatting and a dash for a missing 1 mo", () => {
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
    expect(screen.getByText("Overall verdict")).toBeInTheDocument();
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
    expect(mrvl.querySelectorAll("td")[5]).toHaveTextContent("—");
    expect(mrvl.querySelectorAll("td")[6]).toHaveTextContent("—");
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

describe("MomentumTable Overall verdict badge", () => {
  const withVerdict = (row: MomentumSnapshotRowOut, overall_score: number | null, overall_verdict: string | null): MomentumSnapshotRowOut => ({
    ...row,
    overall_score,
    overall_verdict,
  });
  // Overall verdict is the cell right after Last.
  const verdictCell = (ticker: string) => (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[3] as HTMLElement;

  it.each([
    ["Strong Pass", 95, "Strong pass", "text-positive-strong"],
    ["Pass", 79, "Pass", "text-positive"],
    ["Pass with caution", 73, "Pass with caution", "text-caution"],
    ["Fail", 40, "May not pass", "text-not-pass"],
  ])("draws the stored %s verdict as %s in the shared tone", (verdict, score, label, toneClass) => {
    render(<MomentumTable rows={[withVerdict(ROWS[0], score, verdict)]} />);
    const badge = screen.getByText(label);
    expect(verdictCell("SNDK")).toContainElement(badge);
    expect(badge).toHaveClass(toneClass);
  });

  it("shows the missing placeholder when the ticker has no verdict", () => {
    render(<MomentumTable rows={[withVerdict(ROWS[0], null, null)]} />);
    expect(verdictCell("SNDK")).toHaveTextContent("—");
  });

  it("keeps the snapshot's own order (rank), whatever the scores and verdicts", () => {
    const rows = [
      withVerdict({ ...ROWS[0], ticker: "ONE", rank: 1 }, 40, "Fail"),
      withVerdict({ ...ROWS[1], ticker: "TWO", rank: 2 }, 95, "Strong Pass"),
      withVerdict({ ...ROWS[1], ticker: "THREE", rank: 3 }, 73, "Pass with caution"),
    ];
    render(<MomentumTable rows={rows} />);
    const order = [...document.querySelectorAll("tbody tr")].map((tr) => tr.querySelectorAll("td")[0].textContent);
    expect(order).toEqual(["1", "2", "3"]);
  });

  it("the ETF table (no Overall verdict column) shows no verdict badge", () => {
    render(<MomentumTable rows={[withVerdict(ROWS[0], 73, "Pass with caution")]} showMoatAndScore={false} />);
    expect(screen.queryByText("Pass with caution")).toBeNull();
  });
});
