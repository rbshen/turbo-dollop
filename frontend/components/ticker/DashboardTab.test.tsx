// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { dashboard, debtStandard, scoreRow, summaryRow, trendRow } from "@/components/dashboard/testData";
import { DashboardTab } from "@/components/ticker/DashboardTab";
import type { DashboardOut, TickerScoreOut, TickerSummaryOut, TrendAnalysisOut } from "@/lib/api/types";

// The hooks are the only data source: the header's three feed Section A and C, /dashboard feeds B and C, /universe the delisted note.
const state: {
  dash: { data?: DashboardOut; error?: Error; isLoading: boolean };
  score: { data?: TickerScoreOut | null; isLoading: boolean };
  summary: { data?: TickerSummaryOut };
  trend: { data?: TrendAnalysisOut | null; isLoading: boolean };
  universe: { data?: { delisted: boolean } };
} = { dash: { isLoading: false }, score: { isLoading: false }, summary: {}, trend: { isLoading: false }, universe: {} };

vi.mock("@/lib/hooks/useDashboard", () => ({ useDashboard: () => state.dash }));
vi.mock("@/lib/hooks/useTickerScore", () => ({ useTickerScore: () => state.score }));
vi.mock("@/lib/hooks/useTickerSummary", () => ({ useTickerSummary: () => state.summary }));
vi.mock("@/lib/hooks/useTrendAnalysis", () => ({ useTrendAnalysis: () => state.trend }));
vi.mock("@/lib/hooks/useUniverse", () => ({ useUniverseStatus: () => state.universe }));
vi.mock("@/lib/hooks/useStuckCheck", () => ({ useStuckCheck: () => ({ data: undefined, error: undefined, isLoading: true }) }));
vi.mock("@/lib/hooks/useDataGroups", () => ({ useDataGroups: () => ({ data: undefined }) }));

beforeEach(() => {
  state.dash = { data: dashboard(), isLoading: false };
  state.score = { data: scoreRow(), isLoading: false };
  state.summary = { data: summaryRow() };
  state.trend = { data: trendRow(), isLoading: false };
  state.universe = {};
});
afterEach(cleanup);

const row = (name: string) => screen.getByTestId(`step-row-${name}`);
const pillOf = (name: string) => within(row(name)).getByTestId("step-pill");

describe("Section A: the verdict strip is the header's own", () => {
  it("shows the header's pills from the header's hooks, and the since date as inline text", () => {
    render(<DashboardTab ticker="ACME" />);
    const strip = within(screen.getByTestId("dashboard-verdicts"));
    expect(strip.getByText("Pass with caution")).toBeInTheDocument(); // the stored Overall verdict, via AssessmentChipView
    expect(strip.getByText(/Undervalued/)).toBeInTheDocument();
    expect(strip.getByText(/Stage 3/)).toBeInTheDocument();
    expect(strip.getByText("5Y vs SPY")).toBeInTheDocument();
    expect(strip.getByText(/^Since /)).toBeInTheDocument();
  });

  it("a lower-bound since date reads 'Since at least' with the data-starts caveat", () => {
    state.trend = { data: trendRow({ weinstein_stage_since_is_lower_bound: true }), isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    const strip = within(screen.getByTestId("dashboard-verdicts"));
    expect(strip.getByText(/Since at least/)).toBeInTheDocument();
    expect(strip.getByText(/Data starts here/)).toBeInTheDocument();
  });

  it("missing pieces degrade one by one to neutral words", () => {
    state.score = { data: null, isLoading: false };
    state.summary = { data: summaryRow({ fair_value_price: null, fair_value_verdict: null, perf_5y_vs_spy_status: "no_data" }) };
    state.trend = { data: null, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    const strip = within(screen.getByTestId("dashboard-verdicts"));
    for (const text of ["Not scored", "No fair value", "No stage yet", "No data"]) expect(strip.getByText(text)).toBeInTheDocument();
  });
});

describe("Section B: pills are the stored verdicts, never recomputed", () => {
  it("draws the STORED verdict with the existing label helpers, even when the live step disagrees", () => {
    const d = dashboard();
    d.financials = { ...d.financials, score: 90, verdict: "Pass", stored_score: 55, stored_verdict: "Fail" };
    d.debt = debtStandard({ score: 85, verdict: "Pass", stored_score: 72, stored_verdict: "Pass with caution", unrescued_breaches: ["current_ratio"] });
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(pillOf("financials")).toHaveTextContent("55");
    expect(pillOf("financials")).toHaveTextContent("May not pass");
    expect(pillOf("financials")).not.toHaveTextContent("Pass");
    expect(pillOf("debt")).toHaveTextContent("Pass, ratio in breach");
    expect(pillOf("debt")).not.toHaveTextContent("Pass with caution");
  });

  it("agrees with the header's own TickerScore row: the same stored step words for the same ticker", () => {
    // The strip's Overall chip and every step pill read stored values; for one ticker they all come from the one TickerScore row.
    const s = scoreRow({ step1_score: 64, step1_verdict: "Fail", step5_score: 91, step5_verdict: "Strong Pass" });
    const d = dashboard();
    d.financials = { ...d.financials, stored_score: s.step1_score, stored_verdict: s.step1_verdict };
    d.debt = debtStandard({ stored_score: s.step5_score, stored_verdict: s.step5_verdict });
    state.score = { data: s, isLoading: false };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(pillOf("financials")).toHaveTextContent("May not pass");
    expect(pillOf("debt")).toHaveTextContent("Strong pass");
    expect(within(screen.getByTestId("dashboard-verdicts")).getByText("Pass with caution")).toBeInTheDocument();
  });

  it("a missing stored verdict or insufficient_data is the neutral 'Not scored' pill", () => {
    const d = dashboard();
    d.growth = { ...d.growth, available: false, growth_rate: null, stored_score: null, stored_verdict: null };
    d.profitability = { ...d.profitability, stored_score: 40, stored_verdict: "insufficient_data" };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(pillOf("growth")).toHaveTextContent("Not scored");
    expect(pillOf("profitability")).toHaveTextContent("Not scored");
    expect(within(row("growth")).getByText("No analyst estimates cached for this ticker")).toBeInTheDocument();
  });

  it("Financials: three mini bar charts, CFO marked 'not scored' for a bank", () => {
    const d = dashboard({ company_type: "Bank" });
    d.financials = { ...d.financials, scored_cfo: false, cfo_exempt_reason: "Bank" };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    const financials = within(row("financials"));
    expect(screen.getByTestId("financials-cfo").getAttribute("data-scored")).toBe("false");
    expect(screen.getByTestId("financials-revenue").getAttribute("data-scored")).toBe("true");
    expect(financials.getByText(/· not scored/)).toBeInTheDocument();
    expect(financials.getByText(/Not scored for a bank: revenue and net income only/)).toBeInTheDocument();
    expect(financials.getByText(/FY2021 to FY2025/)).toBeInTheDocument();
  });

  it("Growth: the rate on a 0-20% scale with the 5, 10 and 15% lines and the analyst count", () => {
    render(<DashboardTab ticker="ACME" />);
    const growth = within(row("growth"));
    expect(growth.getAllByTestId("tier-tick")).toHaveLength(3);
    expect(growth.getByText("12.5%")).toBeInTheDocument();
    expect(growth.getByText(/from 18 analysts/)).toBeInTheDocument();
  });

  it("Moat: the type pill (or 'Not rated') and the sparkline with the endpoint's label", () => {
    render(<DashboardTab ticker="ACME" />);
    expect(within(screen.getByTestId("step-row-moat")).getByText("Narrow moat")).toBeInTheDocument();
    expect(within(screen.getByTestId("step-row-moat")).getAllByText("5-year price").length).toBeGreaterThan(0);

    cleanup();
    const d = dashboard();
    d.moat = { ...d.moat, moat: null, rated: false, multiplier: 0.7, price_series: [], price_unavailable_reason: "No cached daily bars" };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    const moat = within(screen.getByTestId("step-row-moat"));
    expect(moat.getByText("Not rated")).toBeInTheDocument();
    expect(moat.getByText(/Moat not rated, scored as No moat/)).toBeInTheDocument();
    expect(moat.getByText("No cached daily bars")).toBeInTheDocument(); // type only when the series is unavailable
  });

  it("Profitability: the gauge shows the SCORED average, not the latest value", () => {
    render(<DashboardTab ticker="ACME" />);
    const roe = within(screen.getByTestId("profitability-roe"));
    expect(roe.getByText("14.0%")).toBeInTheDocument(); // the average (latest is 18)
    expect(roe.queryByText("18.0%")).not.toBeInTheDocument();
    expect(roe.getByText(/Scored on the average of 6 years \(latest 18.0%\)/)).toBeInTheDocument();
    expect(roe.getByText(/good at 12% or higher, excellent above 15%, weak under 8%/)).toBeInTheDocument();
  });

  it("Profitability: ROIC shows the exempt reason; ROE shows the negative-equity basis note", () => {
    const d = dashboard({ company_type: "Bank" });
    d.profitability = {
      ...d.profitability,
      roe: { ...d.profitability.roe, scored: { basis: "negative_equity", average: null, minimum: null, points_used: 0, points_total: 0, recovery_excluded: 0, spike_excluded: false } },
      roic: { exempt_reason: "ROIC not applicable for Bank", years: [], values: [], scored: null },
    };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(within(screen.getByTestId("profitability-roic")).getByText(/Not applicable — ROIC not applicable for Bank/)).toBeInTheDocument();
    expect(within(screen.getByTestId("profitability-roe")).getByText(/Equity was negative in some period/)).toBeInTheDocument();
  });

  it("Debt, Standard: three gauges with the monitor zone from the endpoint's pass line and hard limit", () => {
    render(<DashboardTab ticker="ACME" />);
    const debt = within(row("debt"));
    expect(debt.getAllByRole("img")).toHaveLength(3);
    expect(debt.getByText("Passes at 3.00x or lower · hard limit 4.00x")).toBeInTheDocument();
    expect(debt.getByText("Passes at 1.00x or higher · hard limit 0.70x")).toBeInTheDocument();
    expect(row("debt").querySelectorAll(".bg-warn\\/20")).toHaveLength(3);
  });

  it("Debt: a ratio in breach is amber and named; negative EBITDA and an excluded ratio say so", () => {
    const d = dashboard();
    const ratios = debtStandard().ratios;
    ratios[0] = { ...ratios[0], value: 0.8 };
    ratios[1] = { ...ratios[1], value: null, tier: "negative_ebitda", points: 0 };
    ratios[2] = { ...ratios[2], value: null, tier: "excluded_negative_cfo", excluded: true };
    d.debt = debtStandard({ ratios, unrescued_breaches: ["current_ratio", "debt_to_ebitda"], stored_verdict: "Pass with caution", stored_score: 72 });
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    const debt = within(row("debt"));
    expect(within(screen.getByTestId("debt-current_ratio")).getByRole("img").getAttribute("data-state")).toBe("monitor");
    expect(debt.getByText(/EBITDA is negative/)).toBeInTheDocument();
    expect(debt.getByText(/Excluded this period/)).toBeInTheDocument();
    expect(debt.getByText("In breach: current ratio, debt / ebitda")).toBeInTheDocument();
  });

  it("Debt, Bank and REIT: single-line gauges (one tick, no zone)", () => {
    const d = dashboard({ company_type: "REIT/Property Developer" });
    d.debt = debtStandard({
      ratios: [{ key: "gearing_ratio", label: "Gearing", unit: "pct", direction: "ceiling", value: 38, adjusted_value: null, tier: "good", points: 85, excluded: false, note: null, pass_line: 45, hard_limit: 45 }],
    });
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(within(row("debt")).getAllByTestId("gauge-tick")).toHaveLength(1);
    expect(row("debt").querySelector(".bg-warn\\/20")).toBeNull();
  });

  it("Debt: Insurance and a no-deposit bank say 'Not applicable' with the reason, and the pill is 'Not scored'", () => {
    const d = dashboard({ company_type: "Insurance" });
    d.debt = { ...debtStandard(), status: "not_applicable", status_reason: "Debt is not applied to insurers", ratios: [], stored_score: null, stored_verdict: "not_supported" };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(within(row("debt")).getByText("Not applicable — Debt is not applied to insurers")).toBeInTheDocument();
    expect(pillOf("debt")).toHaveTextContent("Not scored");
  });

  it("Debt, Bank missing a figure: the partial reason shows", () => {
    const d = dashboard({ company_type: "Bank" });
    const [cr] = debtStandard().ratios;
    d.debt = debtStandard({ status: "partial", status_reason: "CET1 and NPL are both needed for a score", ratios: [{ ...cr, key: "cet1_ratio", label: "CET1 ratio", value: null }] });
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(within(row("debt")).getByText("CET1 and NPL are both needed for a score")).toBeInTheDocument();
    expect(within(row("debt")).getByText("No data")).toBeInTheDocument();
  });
});

describe("Section C: price and valuation", () => {
  it("uses the HEADER's price and fair value, not the endpoint's cached quote", () => {
    // summary: price 92.5, fair value 100; endpoint: price 90 -- the bar and its sentence must say 92.5.
    render(<DashboardTab ticker="ACME" />);
    const bar = within(screen.getByTestId("price-range-row"));
    expect(bar.getByText("$92.50")).toBeInTheDocument();
    expect(bar.queryByText("$90.00", { selector: "span.font-mono.text-text-primary" })).not.toBeInTheDocument();
    expect(bar.getByText("Price is 7.5% below fair value, inside the fair-value band")).toBeInTheDocument();
  });

  it("no fair value shows the reason in plain words and still the price", () => {
    state.summary = { data: summaryRow({ fair_value_price: null, fair_value_verdict: null }) };
    const d = dashboard();
    d.fair_value = { ...d.fair_value, available: false, fair_value_price: null, verdict: null, unavailable_reason: "pass_method", unavailable_detail: "Losses and no P/B route" };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    const bar = within(screen.getByTestId("price-range-row"));
    expect(bar.getByText("No fair value: no valuation method applies (Losses and no P/B route)")).toBeInTheDocument();
    expect(bar.getByText("Price $92.50")).toBeInTheDocument();
  });

  it("the stage strip draws the weeks; unavailable shows the reason and the since date only", () => {
    const { unmount } = render(<DashboardTab ticker="ACME" />);
    expect(within(screen.getByTestId("stage-row")).getAllByTestId("stage-run").length).toBeGreaterThan(0);
    unmount();

    const d = dashboard();
    d.weinstein = { ...d.weinstein, available: false, unavailable_reason: "Fewer than 40 weeks of cached history", weeks: [], stage: null };
    state.dash = { data: d, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    const stage = within(screen.getByTestId("stage-row"));
    expect(stage.queryByTestId("stage-run")).not.toBeInTheDocument();
    expect(stage.getByText("Fewer than 40 weeks of cached history")).toBeInTheDocument();
    expect(stage.getByText(/^Since /)).toBeInTheDocument();
  });
});

describe("states: loading, error, no data, delisted, independence", () => {
  it("loading draws pulsing blocks in the content's own shape", () => {
    state.dash = { data: undefined, isLoading: true };
    render(<DashboardTab ticker="ACME" />);
    expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("step-row-debt")).not.toBeInTheDocument();
  });

  it("an endpoint error degrades Sections B and C only; the header-driven strip still shows", () => {
    state.dash = { data: undefined, error: new Error("boom"), isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(screen.getAllByText(/boom/).length).toBe(2);
    expect(within(screen.getByTestId("dashboard-verdicts")).getByText("Pass with caution")).toBeInTheDocument();
  });

  it("nothing cached: one plain sentence in Section B, the strip unaffected", () => {
    state.dash = { data: dashboard({ has_data: false }), isLoading: false };
    state.score = { data: null, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    expect(screen.getByText("Nothing is cached for this ticker yet, so there is nothing to show.")).toBeInTheDocument();
    expect(within(screen.getByTestId("dashboard-verdicts")).getByText("Not scored")).toBeInTheDocument();
  });

  it("a ticker with no scores at all: every step is 'Not scored' and the page still renders", () => {
    const d = dashboard();
    d.financials = { ...d.financials, stored_score: null, stored_verdict: null };
    d.growth = { ...d.growth, stored_score: null, stored_verdict: null };
    d.profitability = { ...d.profitability, stored_score: null, stored_verdict: null };
    d.debt = { ...d.debt, stored_score: null, stored_verdict: null };
    state.dash = { data: d, isLoading: false };
    state.score = { data: null, isLoading: false };
    render(<DashboardTab ticker="ACME" />);
    for (const name of ["financials", "growth", "profitability", "debt"]) expect(pillOf(name)).toHaveTextContent("Not scored");
  });

  it("a delisted ticker gets one plain line", () => {
    state.universe = { data: { delisted: true } };
    render(<DashboardTab ticker="ACME" />);
    expect(screen.getByTestId("dashboard-delisted")).toHaveTextContent("delisted");
  });

  it("uses no tooltips of its own: no title attribute outside the header's reused pills", () => {
    render(<DashboardTab ticker="ACME" />);
    const steps = screen.getByTestId("dashboard-steps");
    const price = screen.getByTestId("dashboard-price");
    expect(steps.querySelectorAll("[title]")).toHaveLength(0);
    expect(price.querySelectorAll("[title]")).toHaveLength(0);
  });
});
