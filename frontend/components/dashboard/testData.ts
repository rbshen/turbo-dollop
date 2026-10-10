// Fixtures shared by the Dashboard tests (not shipped: only imported from *.test.tsx).
import type { DashboardDebt, DashboardOut, TickerScoreOut, TickerSummaryOut, TrendAnalysisOut } from "@/lib/api/types";

const YEARS = ["2021", "2022", "2023", "2024", "2025"];

const head = (score: number | null, verdict: string | null) => ({ score, verdict, stored_score: score, stored_verdict: verdict });

export function debtStandard(over: Partial<DashboardDebt> = {}): DashboardDebt {
  return {
    ...head(82, "Pass"),
    available: true,
    status: "scored",
    status_reason: null,
    unrescued_breaches: [],
    pass_with_caution: false,
    ratios: [
      { key: "current_ratio", label: "Current ratio", unit: "x", direction: "floor", value: 1.8, adjusted_value: null, tier: "good", points: 85, excluded: false, note: null, pass_line: 1.0, hard_limit: 0.7 },
      { key: "debt_to_ebitda", label: "Debt / EBITDA", unit: "x", direction: "ceiling", value: 2.1, adjusted_value: null, tier: "acceptable", points: 70, excluded: false, note: null, pass_line: 3.0, hard_limit: 4.0 },
      { key: "debt_servicing_ratio", label: "Debt servicing", unit: "pct", direction: "ceiling", value: 12, adjusted_value: null, tier: "good", points: 85, excluded: false, note: null, pass_line: 30, hard_limit: 40 },
    ],
    ...over,
  };
}

export function dashboard(over: Partial<DashboardOut> = {}): DashboardOut {
  const weeks = Array.from({ length: 52 }, (_, i) => ({
    week: new Date(Date.UTC(2025, 9, 6) + i * 7 * 86400000).toISOString().slice(0, 10),
    stage: (i < 30 ? "advance" : "top") as "advance" | "top",
  }));
  return {
    ticker: "ACME",
    applicable: true,
    not_applicable_reason: null,
    has_data: true,
    company_type: "Standard",
    currency: "USD",
    financials: {
      ...head(80, "Pass"),
      available: true,
      scored_revenue: true,
      scored_net_income: true,
      scored_cfo: true,
      cfo_exempt_reason: null,
      series: { years: YEARS, revenue: [100, 110, 121, 133, 146], net_income: [10, 11, 12, 13, 15], cfo: [12, 13, 14, 16, 18] },
    },
    growth: { ...head(75, "Pass"), available: true, growth_rate: 12.5, target_analyst_count: 18, basis: "eps", base_fiscal_year: "2025", target_fiscal_year: "2028", bands: [5, 10, 15] },
    moat: {
      moat: "narrow_moat",
      rated: true,
      multiplier: 0.85,
      price_series: [
        { day: "2021-10-08", close: 80 },
        { day: "2023-10-06", close: 120 },
        { day: "2026-10-09", close: 150 },
      ],
      price_years_covered: 5,
      price_label: "5-year price",
      price_unavailable_reason: null,
    },
    profitability: {
      ...head(71, "Pass"),
      available: true,
      roe: { exempt_reason: null, years: YEARS, values: [12, 13, 14, 15, 18], scored: { basis: "average", average: 14.0, minimum: 12, points_used: 6, points_total: 6, recovery_excluded: 0, spike_excluded: false } },
      roic: { exempt_reason: null, years: YEARS, values: [8, 9, 10, 11, 12], scored: { basis: "average", average: 10.0, minimum: 8, points_used: 6, points_total: 6, recovery_excluded: 0, spike_excluded: false } },
      cutoffs: { excellent: 15, good: 12, marginal: 8, min_year: 8 },
    },
    debt: debtStandard(),
    fair_value: { available: true, unavailable_reason: null, unavailable_detail: null, fair_value_price: 100, verdict: "undervalued", method: "DCF", source: "auto", price: 90, currency: "USD", band_low: 0.9, band_high: 1.1, discount_premium_pct: -10 },
    weinstein: { available: true, unavailable_reason: null, weeks_available: 300, weeks_required: 40, stage: "top", since_date: weeks[30].week, since_is_lower_bound: false, weeks, ma_label: "EMA30" },
    ...over,
  };
}

export function scoreRow(over: Partial<TickerScoreOut> = {}): TickerScoreOut {
  return {
    ticker: "ACME",
    company_name: "Acme",
    sector: "Technology",
    step1_score: 80,
    step1_verdict: "Pass",
    step2_score: 75,
    step2_verdict: "Pass",
    step4_score: 71,
    step4_verdict: "Pass",
    step5_score: 82,
    step5_verdict: "Pass",
    moat: "narrow_moat",
    steps_score: 78.2,
    moat_multiplier: 0.85,
    overall_score: 66,
    overall_verdict: "Pass with caution",
    computed_at: "2026-10-09T03:00:00",
    ...over,
  } as TickerScoreOut;
}

export function summaryRow(over: Partial<TickerSummaryOut> = {}): TickerSummaryOut {
  return {
    ticker: "ACME",
    company_name: "Acme",
    is_etf: false,
    price: 92.5,
    quote_currency: "USD",
    fair_value_price: 100,
    fair_value_verdict: "undervalued",
    fair_value_method: "DCF",
    valuation_source: "auto",
    fair_value_reported_currency: null,
    perf_5y_vs_spy_status: "outperform",
    perf_5y_insufficient_history: false,
    ...over,
  } as TickerSummaryOut;
}

export function trendRow(over: Partial<TrendAnalysisOut> = {}): TrendAnalysisOut {
  return {
    ticker: "ACME",
    weinstein_stage: "top",
    weinstein_stage_since_date: "2026-04-27",
    weinstein_stage_since_is_lower_bound: false,
    weinstein_ma_slope_pct: 1.2,
    weinstein_vs_ma_pct: 4.2,
    pending: null,
    weinstein_params: null,
    ...over,
  } as TrendAnalysisOut;
}
