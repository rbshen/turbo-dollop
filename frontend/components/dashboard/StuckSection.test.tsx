// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LazyMount } from "@/components/dashboard/LazyMount";
import { StuckSection } from "@/components/dashboard/StuckSection";
import type { StuckCheckOut, StuckRow } from "@/lib/api/types";
import { useStuckCheck } from "@/lib/hooks/useStuckCheck";

vi.mock("@/lib/hooks/useStuckCheck", () => ({ useStuckCheck: vi.fn() }));
vi.mock("@/lib/hooks/useDataGroups", () => ({ useDataGroups: vi.fn(() => ({ data: undefined })) }));
const hook = vi.mocked(useStuckCheck);

const row = (over: Partial<StuckRow> & Pick<StuckRow, "key" | "number" | "title">): StuckRow => ({
  status: null,
  reason: null,
  figures: [],
  notes: [],
  series: [],
  returns: null,
  growth: null,
  meaning: null,
  gauges: [],
  ...over,
});

const RETURNS = {
  sector_etf: "XLK",
  benchmark: "SPY",
  band_pp: 2,
  windows: [
    { months: 1 as const, stock_pct: 2.0, sector_pct: 1.5, spy_pct: 1.0 },
    { months: 3 as const, stock_pct: 12.0, sector_pct: 5.0, spy_pct: 4.0 },
    { months: 6 as const, stock_pct: -3.0, sector_pct: 6.0, spy_pct: 5.0 },
    { months: 12 as const, stock_pct: 20.0, sector_pct: 18.0, spy_pct: null },
  ],
};

function data(over: Partial<StuckCheckOut> = {}): StuckCheckOut {
  return {
    ticker: "ACME",
    subtitle: "Context, not scored",
    applicable: true,
    not_applicable_reason: null,
    has_data: true,
    company_type: "Standard",
    currency: "USD",
    footer: "Nothing flagged",
    rows: [
      row({
        key: "cash_conversion",
        number: 1,
        title: "Cash conversion",
        status: "not_flagged",
        meaning: "Free cash flow was 1.12 times net income over the last 3 fiscal years and 0.98 times over the last 10. It is flagged only when both are under 0.70.",
        gauges: [
          { key: "last_3y", label: "Last 3 fiscal years", value: 1.12, unit: "ratio", line: 0.7, direction: "floor", note: null },
          { key: "last_10y", label: "Last 10 fiscal years", value: 0.98, unit: "ratio", line: 0.7, direction: "floor", note: null },
        ],
      }),
      row({
        key: "sbc",
        number: 2,
        title: "Stock-based compensation",
        status: "flagged",
        meaning: "Stock-based compensation was 9.5% of revenue (limit 8%) and 21.0% of free cash flow (limit 30%) over the last 5 fiscal years. It is flagged because one of them is over its limit.",
        gauges: [
          { key: "sbc_5y_pct_revenue", label: "5-year total, % of revenue", value: 9.5, unit: "pct", line: 8, direction: "ceiling", note: null },
          { key: "sbc_5y_pct_fcf", label: "5-year total, % of free cash flow", value: null, unit: "pct", line: 30, direction: "ceiling", note: "Not meaningful: free cash flow was zero, negative or smaller than the stock-based compensation, which counts as over the line" },
        ],
      }),
      row({ key: "fcf_after_sbc", number: 3, title: "FCF after stock-based compensation", status: "not_applicable", reason: "Free cash flow is not comparable for a bank" }),
      row({ key: "buybacks_vs_sbc", number: 4, title: "Buybacks vs stock-based compensation", figures: [{ key: "buybacks_multiple", label: "Gross buybacks vs SBC", value: 2.5, unit: "multiple", text: null }] }),
      row({ key: "share_count", number: 5, title: "Share count", status: "not_applicable", reason: "Free cash flow is not comparable for a bank" }),
      row({ key: "shareholder_yield", number: 6, title: "Shareholder yield", figures: [{ key: "y", label: "% of 5-year free cash flow", value: 74.2, unit: "pct", text: null }] }),
      row({ key: "relative_strength", number: 8, title: "Relative strength", returns: RETURNS, notes: ["This stock is 12% of its sector's tracked market cap, so the sector ETF partly measures the stock itself"] }),
      row({
        key: "margins",
        number: 9,
        title: "Margins",
        series: [{ key: "operating_margin", label: "Operating margin", unit: "pct", points: ["2021", "2022", "2023", "2024", "2025"].map((label, i) => ({ label, value: 10 + i })) }],
        meaning: "Operating margin averaged 11.0% over the first 3 of the last 5 fiscal years and 13.0% over the last 3, a change of +1.0% a year.",
        figures: [{ key: "gross_margin_last3", label: "Gross margin, last 3 years average", value: 55, unit: "pct", text: null }],
      }),
      row({
        key: "growth",
        number: 10,
        title: "Growth",
        growth: { cagr_5y: 12, sector_median: 8, percentile: 86, sector_peers: 9 },
        meaning: "Revenue grew 12.0% a year over 5 years; the sector median is 8.0% and it grew faster than 86% of the 9 tracked stocks in its sector.",
        figures: [{ key: "latest_growth", label: "Latest fiscal year growth", value: 9, unit: "pct", text: null }],
      }),
      row({
        key: "roic",
        number: 12,
        title: "Return on invested capital",
        series: [{ key: "roic", label: "Return on invested capital", unit: "pct", points: ["2021", "2022", "2023", "2024", "2025"].map((label, i) => ({ label, value: 8 + i })) }],
        meaning: "Return on invested capital went from 8.0% to 12.0% across the last 5 fiscal years, +1.0% a year.",
      }),
    ],
    ...over,
  };
}

beforeEach(() => hook.mockReturnValue({ data: data(), error: undefined, isLoading: false } as unknown as ReturnType<typeof useStuckCheck>));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const put = (d: StuckCheckOut | undefined, extra: Record<string, unknown> = {}) =>
  hook.mockReturnValue({ data: d, error: undefined, isLoading: false, ...extra } as unknown as ReturnType<typeof useStuckCheck>);

describe("StuckSection: heading and separation from the scored sections", () => {
  it("is headed 'Why might it be stuck?' with 'Context, not scored', has no pill and no score, and a stronger rule", () => {
    render(<StuckSection ticker="ACME" />);
    const section = screen.getByTestId("dashboard-stuck");
    expect(within(section).getByText("Why might it be stuck?")).toBeInTheDocument();
    expect(within(section).getByText("Context, not scored")).toBeInTheDocument();
    expect(within(section).queryByTestId("step-pill")).toBeNull();
    expect(section.className).toContain("border-border-card"); // the stronger rule that sets it apart
  });

  it("uses no verdict wording and no red anywhere", () => {
    render(<StuckSection ticker="ACME" />);
    const text = screen.getByTestId("dashboard-stuck").textContent ?? "";
    for (const word of ["May not pass", "Strong pass", "Review", "Fail"]) expect(text).not.toContain(word);
    expect(screen.getByTestId("dashboard-stuck").innerHTML).not.toMatch(/text-negative|bg-negative\/16|not-pass/);
  });
});

describe("relative strength", () => {
  it("draws all four windows against the sector ETF and against SPY, on the 'ahead of / behind benchmark' column", () => {
    render(<StuckSection ticker="ACME" />);
    const rs = within(screen.getByTestId("stuck-relative-strength"));
    expect(within(screen.getByTestId("stuck-rs-sector")).getAllByRole("img")).toHaveLength(4);
    expect(within(screen.getByTestId("stuck-rs-spy")).getAllByRole("img")).toHaveLength(4);
    expect(rs.getByText("Against XLK, the sector ETF")).toBeInTheDocument();
    expect(rs.getByText("Against SPY")).toBeInTheDocument();
    expect(rs.getByText(/ahead of \/ behind benchmark/)).toBeInTheDocument();
    expect(rs.getByText(/within 2% either way/)).toBeInTheDocument();
  });

  it("shows the stock's and the benchmark's own return next to every gap, in %, never 'pp'", () => {
    render(<StuckSection ticker="ACME" />);
    const sector = within(screen.getByTestId("stuck-rs-sector"));
    expect(sector.getByText("stock +12.0% · XLK +5.0%")).toBeInTheDocument(); // 3 months
    expect(sector.getByText("+7.0%")).toBeInTheDocument(); // the gap
    expect(screen.getByTestId("dashboard-stuck").textContent).not.toMatch(/\bpp\b/);
  });

  it("green ahead, red behind, neutral inside the in-line band; a missing window is blank", () => {
    render(<StuckSection ticker="ACME" />);
    const bars = within(screen.getByTestId("stuck-rs-sector")).getAllByRole("img");
    expect(bars.map((b) => b.getAttribute("data-tone"))).toEqual(["in_line", "ahead", "behind", "in_line"]);
    const spy = within(screen.getByTestId("stuck-rs-spy")).getAllByRole("img");
    expect(spy[3].getAttribute("data-tone")).toBe("missing"); // SPY 12 months is not cached
  });

  it("says why when there is no sector ETF, and still shows the weight note when there is one", () => {
    const d = data();
    d.rows = d.rows.map((r) => (r.key === "relative_strength" ? { ...r, returns: null, status: "not_applicable" as const, reason: "No sector ETF for this sector", notes: [] } : r));
    put(d);
    render(<StuckSection ticker="ACME" />);
    expect(screen.getByText("No sector ETF for this sector")).toBeInTheDocument();
    cleanup();
    put(data());
    render(<StuckSection ticker="ACME" />);
    expect(screen.getByText(/12% of its sector's tracked market cap/)).toBeInTheDocument();
  });
});

describe("earnings quality and capital allocation", () => {
  it("labels with 'Not flagged' (neutral, never green) and 'Flagged' (amber), with the meaning line and the gauges", () => {
    render(<StuckSection ticker="ACME" />);
    const cash = within(screen.getByTestId("stuck-row-cash_conversion"));
    const tag = cash.getByText("Not flagged");
    expect(tag.className).toContain("bg-surface-2");
    expect(tag.className).not.toMatch(/positive|warn|negative/);
    expect(cash.getByText(/Free cash flow was 1.12 times net income over the last 3 fiscal years/)).toBeInTheDocument();
    expect(cash.getAllByRole("img")).toHaveLength(2);
    expect(cash.getByText("Flagged below 0.70x")).toBeInTheDocument();
    expect(screen.queryByText("OK")).toBeNull();

    const sbc = within(screen.getByTestId("stuck-row-sbc"));
    expect(sbc.getByText("Flagged").className).toMatch(/warn/);
    expect(sbc.getByText("Flagged above 8.0%")).toBeInTheDocument();
    // a figure that is not meaningful is written out, not drawn as a gauge
    expect(sbc.getByText(/Not meaningful: free cash flow was zero, negative or smaller/)).toBeInTheDocument();
    expect(sbc.getAllByRole("img")).toHaveLength(1);
  });

  it("draws Not-applicable and Not-reported rows not at all; their reasons become ONE note at the bottom of the group", () => {
    render(<StuckSection ticker="ACME" />);
    expect(screen.queryByTestId("stuck-row-fcf_after_sbc")).toBeNull();
    expect(screen.queryByTestId("stuck-row-share_count")).toBeNull();
    const notes = within(screen.getByTestId("stuck-collapsed-notes"));
    // two rows with the same reason are merged into one sentence, not repeated
    expect(notes.getAllByText(/Free cash flow is not comparable for a bank/)).toHaveLength(1);
    expect(notes.getByText("FCF after stock-based compensation and share count: Free cash flow is not comparable for a bank.")).toBeInTheDocument();
    expect(screen.getByTestId("stuck-quality").textContent).not.toContain("Not applicable");
  });

  it("keeps a Settings-driven exemption's reason as it is (IBKR, GM): the backend's words, collapsed", () => {
    const d = data();
    d.rows = d.rows.map((r) =>
      r.key === "share_count" ? { ...r, reason: "Broker: Up-C share structure" } : r.key === "fcf_after_sbc" ? { ...r, reason: "Broker: customer cash distorts free cash flow" } : r,
    );
    put(d);
    render(<StuckSection ticker="ACME" />);
    const notes = within(screen.getByTestId("stuck-collapsed-notes"));
    expect(notes.getByText("Share count: Broker: Up-C share structure.")).toBeInTheDocument();
    expect(notes.getByText("FCF after stock-based compensation: Broker: customer cash distorts free cash flow.")).toBeInTheDocument();
  });

  it("buybacks and shareholder yield are figures only: no label, no gauge", () => {
    render(<StuckSection ticker="ACME" />);
    for (const key of ["buybacks_vs_sbc", "shareholder_yield"]) {
      const r = within(screen.getByTestId(`stuck-row-${key}`));
      expect(r.queryByText("Flagged")).toBeNull();
      expect(r.queryByText("Not flagged")).toBeNull();
      expect(r.queryByRole("img")).toBeNull();
    }
    expect(within(screen.getByTestId("stuck-row-shareholder_yield")).getByText("74.2%")).toBeInTheDocument();
  });

  it("a 10-year window that is not meaningful is said in words on the gauge row", () => {
    const d = data();
    d.rows[0] = {
      ...d.rows[0],
      gauges: [d.rows[0].gauges![0], { key: "last_10y", label: "Last 10 fiscal years", value: null, unit: "ratio", line: 0.7, direction: "floor", note: "Not meaningful: net income was under 2% of revenue over it" }],
    };
    put(d);
    render(<StuckSection ticker="ACME" />);
    expect(within(screen.getByTestId("stuck-row-cash_conversion")).getByText("Not meaningful: net income was under 2% of revenue over it")).toBeInTheDocument();
  });
});

describe("fundamentals trend", () => {
  it("operating margin and ROIC as mini bars for five completed fiscal years, with their meaning lines", () => {
    render(<StuckSection ticker="ACME" />);
    const margin = within(screen.getByTestId("stuck-trend-operating_margin"));
    expect(margin.getByText(/Last 5 completed fiscal years, FY2021 to FY2025/)).toBeInTheDocument();
    expect(margin.getByText(/Operating margin averaged 11.0%/)).toBeInTheDocument();
    expect(within(screen.getByTestId("stuck-trend-roic")).getByText(/Return on invested capital went from 8.0% to 12.0%/)).toBeInTheDocument();
  });

  it("revenue growth against the sector median, with the percentile, as a diverging bar", () => {
    render(<StuckSection ticker="ACME" />);
    const g = within(screen.getByTestId("stuck-trend-growth"));
    expect(g.getByRole("img").getAttribute("data-tone")).toBe("ahead");
    expect(g.getByText("stock +12.0% · sector median +8.0%")).toBeInTheDocument();
    expect(g.getByText(/grew faster than 86% of the 9 tracked stocks/)).toBeInTheDocument();
  });

  it("drops gross margin, latest-year growth and growth against its own CAGR", () => {
    render(<StuckSection ticker="ACME" />);
    const text = screen.getByTestId("stuck-trend").textContent ?? "";
    for (const dropped of ["Gross margin", "Latest fiscal year growth", "own 5-year CAGR", "Latest year vs"]) expect(text).not.toContain(dropped);
  });

  it("ROIC not applicable (a bank) is collapsed to its reason, not drawn", () => {
    const d = data();
    d.rows = d.rows.map((r) => (r.key === "roic" ? { ...r, status: "not_applicable" as const, series: [], meaning: null, reason: "Not meaningful for this company type" } : r));
    put(d);
    render(<StuckSection ticker="ACME" />);
    expect(within(screen.getByTestId("stuck-trend-roic")).getByText("Not meaningful for this company type")).toBeInTheDocument();
  });
});

describe("footer and states", () => {
  it("the footer is 'Nothing flagged', with no 'k of 4' count", () => {
    render(<StuckSection ticker="ACME" />);
    expect(screen.getByTestId("stuck-footer")).toHaveTextContent(/^Nothing flagged$/);
    expect(screen.getByTestId("dashboard-stuck").textContent).not.toMatch(/of 4/);
  });

  it("no footer when something is flagged (the backend sends none)", () => {
    put(data({ footer: null }));
    render(<StuckSection ticker="ACME" />);
    expect(screen.queryByTestId("stuck-footer")).toBeNull();
  });

  it("loading, error, ETF and the empty (no statements: no rows) states degrade on their own", () => {
    put(undefined, { isLoading: true });
    const { unmount } = render(<StuckSection ticker="ACME" />);
    expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
    unmount();

    put(undefined, { error: new Error("boom") });
    const e = render(<StuckSection ticker="ACME" />);
    expect(screen.getByText(/Couldn't load this section — boom/)).toBeInTheDocument();
    e.unmount();

    put(data({ applicable: false, rows: [] }));
    const etf = render(<StuckSection ticker="SPY" />);
    expect(etf.container).toBeEmptyDOMElement();
    etf.unmount();

    put(data({ rows: [], has_data: false }));
    const empty = render(<StuckSection ticker="NEW" />);
    expect(screen.getByText("Nothing is cached for this ticker yet, so there is nothing to show.")).toBeInTheDocument();
    empty.unmount();

  });
});

describe("LazyMount: the section's own call starts when scrolled into view", () => {
  it("mounts its children only once the placeholder intersects, and keeps them mounted", () => {
    let trigger: (entries: Array<{ isIntersecting: boolean }>) => void = () => {};
    const disconnect = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: typeof trigger) {
          trigger = cb;
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    const Child = vi.fn(() => <span>mounted</span>);
    render(
      <LazyMount placeholder={<span>placeholder</span>}>
        <Child />
      </LazyMount>,
    );
    expect(screen.getByText("placeholder")).toBeInTheDocument();
    expect(Child).not.toHaveBeenCalled();

    act(() => trigger([{ isIntersecting: false }]));
    expect(Child).not.toHaveBeenCalled();
    act(() => trigger([{ isIntersecting: true }]));
    expect(screen.getByText("mounted")).toBeInTheDocument();
    expect(disconnect).toHaveBeenCalled();
  });

  it("without IntersectionObserver it mounts at once", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    render(
      <LazyMount placeholder={<span>placeholder</span>}>
        <span>mounted</span>
      </LazyMount>,
    );
    expect(screen.getByText("mounted")).toBeInTheDocument();
  });
});
