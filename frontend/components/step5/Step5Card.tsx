"use client";

import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { AnalysisSectionCard, type ReasoningBullet } from "@/components/shared/AnalysisSectionCard";
import { BankCapitalMetricsForm } from "@/components/step5/BankCapitalMetricsForm";
import { useStep5 } from "@/lib/hooks/useStep5";
import { fmtNumber, fmtPct, fmtTableMoney } from "@/lib/format";
import type { BreachContextSignal, Step5Out, Step5RatioResult } from "@/lib/api/types";

// Order mirrors scoring/step5.py's WEIGHTS_STANDARD / WEIGHTS_REIT /
// WEIGHTS_BANK -- the ratios that actually carry weight/points. Interest
// Coverage Ratio is excluded: it's a tiebreaker signal only, never
// independently weighted. cet1_ratio/npl_ratio only appear here (via
// data.weights) once a Bank ticker has both a CET1 value and a resolved
// NPL value and produces a real score -- data.weights is empty otherwise,
// so reasoningBullets's `weight == null` guard already skips them
// naturally for every other Bank state.
const REASONING_ORDER = ["current_ratio", "debt_to_ebitda", "debt_servicing_ratio", "gearing_ratio", "cet1_ratio", "npl_ratio"] as const;

interface Props {
  ticker: string;
}

const OUTLIER_METRIC_LABELS: Record<string, string> = {
  ebitda_ttm: "EBITDA (TTM)",
  ebit_ttm: "EBIT (TTM)",
  interest_expense_ttm: "Interest Expense (TTM)",
  interest_income_ttm: "Interest Income (TTM)",
  net_interest_expense_ttm: "Net Interest Expense (TTM)",
  cfo_ttm: "Cash Flow from Operations (TTM)",
};

const RATIO_LABELS: Record<string, string> = {
  current_ratio: "Current Ratio",
  debt_to_ebitda: "Debt / EBITDA",
  debt_servicing_ratio: "Debt Servicing Ratio",
  interest_coverage_ratio: "Interest Coverage Ratio",
  gearing_ratio: "Gearing Ratio",
  npl_ratio: "NPL Ratio",
  cet1_ratio: "CET1 Ratio",
};

const TIER_LABELS: Record<string, string> = {
  excellent: "Excellent",
  good: "Good",
  acceptable: "Acceptable",
  approaching_limit: "Approaching limit",
  fail: "Fail",
  // Severity-band tiers (Current Ratio, Debt/EBITDA, Debt Servicing Ratio).
  borderline_saved_by_icr: "Borderline (saved by Interest Coverage)",
  // Debt/EBITDA's and Current Ratio's Borderline breach, downgraded by the
  // richer breach-context framework (see breach_context below) -- the
  // successor to borderline_saved_by_icr for these two ratios specifically
  // (DSR keeps the older label; its own rescue is unchanged).
  marginal_via_breach_context: "Marginal (context-adjusted)",
  borderline_fail: "Borderline — Fail",
  severe: "Severe — Fail",
  // Interest Coverage Ratio's own tiers (informational, no points of its own).
  safe: "Safe",
  tight: "Tight",
  dangerous: "Dangerous",
  not_applicable: "N/A",
};

// Signal keys from scoring/step5.py's breach-context framework -- short
// labels for the nested reasoning sub-bullets below.
const BREACH_CONTEXT_SIGNAL_LABELS: Record<string, string> = {
  trend: "5yr trend",
  fcf_vs_debt: "FCF vs Total Debt",
  interest_coverage: "Interest Coverage",
  cause_of_debt: "Cause of debt",
  net_vs_gross_debt: "Net vs Gross Debt",
  deferred_revenue: "Deferred revenue",
  cash_position: "Cash position",
  asset_quality: "Current asset quality",
  undrawn_revolving_credit: "Undrawn revolving credit",
};

function formatRatioValue(key: string, value: number | null): string {
  if (value == null) return "N/A";
  const PERCENT_RATIOS = new Set(["debt_servicing_ratio", "gearing_ratio", "npl_ratio", "cet1_ratio"]);
  return PERCENT_RATIOS.has(key) ? fmtPct(value, 1) : `${fmtNumber(value, 2)}x`;
}

function tierClass(label: string): string {
  if (label === "fail" || label === "borderline_fail" || label === "severe" || label === "dangerous") return "text-negative";
  if (label === "approaching_limit" || label === "borderline_saved_by_icr" || label === "marginal_via_breach_context" || label === "tight")
    return "text-warn";
  return "text-text-primary";
}

// favorable/unfavorable reuse the same positive/negative tokens the rest of
// the app's score coloring does; not_computable is muted + italicized so
// the manual-check notes read as caveats, not as a real favorable/
// unfavorable data point.
function breachContextSignalClass(status: string): string {
  if (status === "favorable") return "text-positive";
  if (status === "unfavorable") return "text-negative";
  return "text-text-tertiary italic";
}

function breachContextBullets(ratioKey: string, signals: BreachContextSignal[] | null): ReasoningBullet[] {
  if (!signals) return [];
  return signals.map((s) => ({
    key: `${ratioKey}-context-${s.key}`,
    text: `↳ ${BREACH_CONTEXT_SIGNAL_LABELS[s.key] ?? s.key}: ${s.detail ?? "—"}`,
    tierClassName: breachContextSignalClass(s.status),
  }));
}

const TIEBREAKER_FOR: Record<string, string> = {
  current_ratio: "deferred revenue",
  debt_to_ebitda: "a healthy Interest Coverage Ratio",
  debt_servicing_ratio: "a healthy Interest Coverage Ratio",
};

function savedRatioSummary(ratios: Record<string, Step5RatioResult>): string {
  const saved = Object.entries(ratios).filter(([, r]) => r.saved_by_tiebreaker);
  return saved
    .map(([key]) => `${RATIO_LABELS[key] ?? key} was borderline but excused by ${TIEBREAKER_FOR[key] ?? "its tiebreaker"}`)
    .join("; ");
}

function reasoningBullets(data: Step5Out): ReasoningBullet[] {
  const bullets: ReasoningBullet[] = [];
  for (const key of REASONING_ORDER) {
    const weight = data.weights[key];
    const ratio = data.ratios[key];
    if (weight == null || !ratio) continue;
    bullets.push({
      key,
      text: `${RATIO_LABELS[key] ?? key}: ${formatRatioValue(key, ratio.value)} (${TIER_LABELS[ratio.label] ?? ratio.label})`,
      tierClassName: tierClass(ratio.label),
    });
    // Nested directly under the ratio's own bullet -- only present when
    // that ratio actually reached Borderline and the breach-context
    // framework evaluated it (see schemas.py::Step5RatioResult).
    bullets.push(...breachContextBullets(key, ratio.breach_context));
  }
  return bullets;
}

export function Step5Card({ ticker }: Props) {
  const { data, error } = useStep5(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-negative">Couldn&apos;t load Debt data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Debt…</p>
      </div>
    );
  }

  const isBank = data.company_type === "Bank";
  const isInsurance = data.company_type === "Insurance";
  const bullets = data.score != null ? reasoningBullets(data) : [];
  const icr = data.ratios.interest_coverage_ratio;

  const blurb = isBank
    ? data.bank_capital_metrics_editable
      ? data.cet1_ratio_pct == null
        ? "CET1 ratio not yet entered — enter it below to complete this ticker's Debt verdict."
        : "Scored from manually-entered CET1 and NPL (see below)."
      : // IBKR/HOOD -- no customer deposit-taking business. This is a
        // permanent, deliberate exemption, not a temporary data gap --
        // unlike the "not yet entered" case above, no CET1/NPL form is ever
        // offered for these tickers (see bank_capital_metrics_editable).
        "Debt isn't assessed for this company. It isn't a traditional deposit-taking, lending bank, so the standard debt ratios and the CET1/NPL capital-adequacy check don't apply here."
    : isInsurance
      ? "Standard debt ratios aren't meaningful for insurers -- no substitute capital-adequacy signal is currently available from FMP."
      : data.verdict === "insufficient_data"
        ? `Required balance sheet/income statement figures were unavailable for ${ticker}.`
        : data.hard_fail
          ? "At least one ratio breached its hard limit, so this fails regardless of the blended score."
          : data.pass_with_caution
            ? "No ratio breached its hard limit outright, but see the caution note below."
            : "No ratio breached its hard limit.";

  const notes = (
    <>
      <OutlierWarningNote warnings={data.outlier_warnings} labels={OUTLIER_METRIC_LABELS} />
      {isBank && !data.bank_capital_metrics_editable && (
        <p className="text-xs text-text-tertiary">{data.classification_note}</p>
      )}
      {icr && bullets.length > 0 && (
        <p className="text-xs text-text-tertiary">
          Interest Coverage Ratio carries no weight of its own — it&apos;s the tiebreaker that can excuse a Borderline
          breach on Debt/EBITDA or Debt Servicing Ratio above (currently {TIER_LABELS[icr.label] ?? icr.label}
          {icr.value != null && <>, {formatRatioValue("interest_coverage_ratio", icr.value)}</>}).
        </p>
      )}
      {!isBank && !isInsurance && data.deferred_revenue_current != null && data.deferred_revenue_current > 0 && (
        <p className="text-xs text-text-tertiary">
          Deferred revenue (current): {fmtTableMoney(data.deferred_revenue_current)} — cash already collected, not yet
          delivered, so it isn&apos;t a real short-term obligation.
          {data.ratios.current_ratio?.saved_by_tiebreaker
            ? " Subtracting it from current liabilities is what resolved the Current Ratio's apparent shortfall above."
            : " Subtracted from current liabilities when tiering the Current Ratio above."}
        </p>
      )}
      {!isBank && !isInsurance && data.pass_with_caution && (
        <p className="text-sm text-caution">Pass with caution: {savedRatioSummary(data.ratios)}.</p>
      )}
    </>
  );

  return (
    <div className="space-y-4">
      <AnalysisSectionCard title="Debt" score={data.score} verdict={data.verdict} blurb={blurb} notes={notes} bullets={bullets} />
      {isBank && data.bank_capital_metrics_editable && <BankCapitalMetricsForm ticker={ticker} step5={data} />}
    </div>
  );
}
