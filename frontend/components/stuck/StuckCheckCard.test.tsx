// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StuckCheckCard } from "@/components/stuck/StuckCheckCard";
import type { StuckCheckOut, StuckRow } from "@/lib/api/types";
import { useStuckCheck } from "@/lib/hooks/useStuckCheck";

vi.mock("@/lib/hooks/useStuckCheck", () => ({ useStuckCheck: vi.fn() }));
vi.mock("@/lib/hooks/useDataGroups", () => ({ useDataGroups: vi.fn(() => ({ data: undefined })) }));

const mockedHook = vi.mocked(useStuckCheck);

const row = (over: Partial<StuckRow> & Pick<StuckRow, "key" | "number" | "title">): StuckRow => ({
  status: null,
  reason: null,
  figures: [],
  notes: [],
  ...over,
});

const DATA: StuckCheckOut = {
  ticker: "ACME",
  subtitle: "Context, not scored",
  applicable: true,
  not_applicable_reason: null,
  has_data: true,
  company_type: "Standard",
  currency: "USD",
  footer: null,
  rows: [
    row({
      key: "cash_conversion",
      number: 1,
      title: "Cash conversion",
      status: "ok",
      figures: [{ key: "last_3y", label: "Last 3 fiscal years", value: 0.66, unit: "ratio", text: null }],
    }),
    row({
      key: "sbc",
      number: 2,
      title: "Stock-based compensation",
      status: "flagged",
      figures: [
        { key: "sbc_latest", label: "Latest fiscal year", value: 1_096_679_000, unit: "money", text: null },
        { key: "sbc_5y_pct_fcf", label: "5-year total, % of free cash flow", value: null, unit: "pct", text: "n/m" },
      ],
      notes: ["% of free cash flow not assessed: Broker"],
    }),
    row({ key: "fcf_after_sbc", number: 3, title: "FCF after stock-based compensation", status: "not_reported", reason: "Stock-based compensation is zero or missing in 5 of the last 5 fiscal years" }),
    row({ key: "share_count", number: 5, title: "Share count", status: "not_applicable", reason: "Broker: Up-C share structure" }),
    row({ key: "shareholder_yield", number: 6, title: "Shareholder yield", figures: [{ key: "y", label: "% of 5-year free cash flow", value: 74.2, unit: "pct", text: null }] }),
    row({
      key: "price_context",
      number: 7,
      title: "Price context",
      figures: [
        { key: "overall_verdict", label: "Overall verdict", value: null, unit: "text", text: "Pass with caution" },
        { key: "valuation_verdict", label: "Valuation verdict", value: null, unit: "text", text: "undervalued" },
        { key: "weinstein_stage", label: "Weinstein stage", value: null, unit: "text", text: "decline" },
        { key: "perf_5y_vs_spy", label: "5Y vs SPY", value: -12.5, unit: "pp", text: "underperform" },
      ],
    }),
    row({
      key: "relative_strength",
      number: 8,
      title: "Relative strength",
      figures: [{ key: "vs_sector_6m", label: "vs XLK, 6 months", value: 3.2, unit: "pp", text: "leads" }],
      notes: ["This stock is 12% of its sector's tracked market cap, so the sector ETF partly measures the stock itself"],
    }),
    row({ key: "margins", number: 9, title: "Margins", figures: [{ key: "m", label: "Operating margin, last 3 years average", value: 45.68, unit: "pct", text: null }] }),
    row({ key: "roic", number: 12, title: "Return on invested capital", status: "not_applicable", reason: "Not meaningful for this company type" }),
  ],
};

function serve(data: StuckCheckOut | undefined, extra: Record<string, unknown> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false, ...extra } as any);
}

beforeEach(() => serve(DATA));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("StuckCheckCard", () => {
  it("renders the title and the 'Context, not scored' subtitle, with no score, verdict pill or count", () => {
    render(<StuckCheckCard ticker="ACME" />);
    expect(screen.getByRole("heading", { level: 2, name: "Why might it be stuck?" })).toBeInTheDocument();
    expect(screen.getByText("Context, not scored")).toBeInTheDocument();
    expect(screen.queryByText(/to review|flagged \(|\d+ of \d+ flagged/i)).toBeNull();
  });

  it("groups rows under three sub-headings in row order", () => {
    render(<StuckCheckCard ticker="ACME" />);
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    const groupTitles = ["Earnings quality and capital allocation", "Price", "Fundamentals trend"];
    expect(headings.filter((h) => groupTitles.includes(h ?? ""))).toEqual(groupTitles);
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles.indexOf("Cash conversion")).toBeLessThan(titles.indexOf("Price context"));
    expect(titles.indexOf("Price context")).toBeLessThan(titles.indexOf("Margins"));
  });

  it("draws each status as its plain label: Flagged amber, the rest neutral, and nothing for a figures-only row", () => {
    render(<StuckCheckCard ticker="ACME" />);
    const flagged = within(screen.getByTestId("stuck-row-sbc")).getByText("Flagged");
    expect(flagged.className).toMatch(/warn/);
    expect(flagged.className).not.toMatch(/negative|not-pass/);
    expect(within(screen.getByTestId("stuck-row-cash_conversion")).getByText("OK").className).not.toMatch(/warn|negative|positive/);
    expect(within(screen.getByTestId("stuck-row-fcf_after_sbc")).getByText("Not reported")).toBeInTheDocument();
    expect(within(screen.getByTestId("stuck-row-share_count")).getByText("Not applicable")).toBeInTheDocument();
    const yieldRow = screen.getByTestId("stuck-row-shareholder_yield");
    for (const label of ["OK", "Flagged", "Not applicable", "Not reported"]) expect(within(yieldRow).queryByText(label)).toBeNull();
  });

  it("shows reasons, notes and figures, formatted", () => {
    render(<StuckCheckCard ticker="ACME" />);
    expect(screen.getByText("Broker: Up-C share structure")).toBeInTheDocument();
    expect(screen.getByText("% of free cash flow not assessed: Broker")).toBeInTheDocument();
    expect(screen.getByText("0.66")).toBeInTheDocument();
    expect(screen.getByText("$1.10B")).toBeInTheDocument();
    expect(screen.getByText("n/m")).toBeInTheDocument();
    expect(screen.getByText("+3.2 pp · leads")).toBeInTheDocument();
    expect(screen.getByText(/12% of its sector's tracked market cap/)).toBeInTheDocument();
  });

  it("shows the stored price values in the app's display words, as neutral text", () => {
    render(<StuckCheckCard ticker="ACME" />);
    const price = screen.getByTestId("stuck-row-price_context");
    expect(within(price).getByText("Pass with caution")).toBeInTheDocument();
    expect(within(price).getByText("Undervalued")).toBeInTheDocument();
    expect(within(price).getByText("Stage 4 · Decline")).toBeInTheDocument();
    expect(within(price).getByText("−12.5 pp · underperform")).toBeInTheDocument();
    expect(price.querySelector("[class*='bg-positive'], [class*='bg-negative'], [class*='bg-caution']")).toBeNull();
  });

  it("draws a stored Fail as plain 'May not pass' text with no colour, pill or amber/red class", () => {
    const fail = DATA.rows[5].figures.map((f) => (f.key === "overall_verdict" ? { ...f, text: "Fail" } : f));
    serve({ ...DATA, rows: DATA.rows.map((r) => (r.key === "price_context" ? { ...r, figures: fail } : r)) });
    render(<StuckCheckCard ticker="ACME" />);
    const price = screen.getByTestId("stuck-row-price_context");
    const value = within(price).getByText("May not pass");
    expect(value.tagName).toBe("DD");
    expect(value.className).toBe("font-mono text-sm tabular-nums text-text-primary");
    expect(price.innerHTML).not.toMatch(/not-pass|negative|warn|caution|positive|strong|pill/);
    expect(within(price).queryByText("Fail")).toBeNull();
  });

  it("shows the footer line when the endpoint sends one", () => {
    serve({ ...DATA, footer: "Nothing flagged (3 of 4 labelled rows assessed)" });
    render(<StuckCheckCard ticker="ACME" />);
    expect(screen.getByText("Nothing flagged (3 of 4 labelled rows assessed)")).toBeInTheDocument();
  });

  it("has loading, error, no-data and ETF states", () => {
    serve(undefined, { isLoading: true });
    const { unmount } = render(<StuckCheckCard ticker="ACME" />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    unmount();

    serve(undefined, { error: new Error("boom") });
    const second = render(<StuckCheckCard ticker="ACME" />);
    expect(screen.getByText(/Couldn't load this card — boom/)).toBeInTheDocument();
    second.unmount();

    serve({ ...DATA, rows: [] });
    const third = render(<StuckCheckCard ticker="ACME" />);
    expect(screen.getByText(/Nothing is cached for this ticker yet/)).toBeInTheDocument();
    third.unmount();

    serve({ ...DATA, has_data: false, rows: [DATA.rows[5]] });
    const fourth = render(<StuckCheckCard ticker="ACME" />);
    expect(screen.getByText(/No cached financial statements/)).toBeInTheDocument();
    expect(screen.getByTestId("stuck-row-price_context")).toBeInTheDocument();
    fourth.unmount();

    serve({ ...DATA, applicable: false, rows: [] });
    const fifth = render(<StuckCheckCard ticker="SPY" />);
    expect(fifth.container).toBeEmptyDOMElement();
  });

  it("reads the right endpoint for the ticker", () => {
    render(<StuckCheckCard ticker="ACME" />);
    expect(mockedHook).toHaveBeenCalledWith("ACME");
  });
});
