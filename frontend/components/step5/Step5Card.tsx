"use client";

import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { AnalysisSectionCard, type ReasoningBullet } from "@/components/shared/AnalysisSectionCard";
import { useStep5 } from "@/lib/hooks/useStep5";
import { fmtNumber, fmtPct, fmtTableMoney } from "@/lib/format";
import type { Step5Out, Step5RatioResult } from "@/lib/api/types";

// Order mirrors scoring/step5.py's WEIGHTS_STANDARD / WEIGHTS_REIT -- the
// ratios that actually carry weight/points. Interest Coverage Ratio and NPL
// are excluded: ICR is a tiebreaker signal only, and NPL is a partial
// signal with no composite score to explain (Bank verdict is always
// "not_supported").
const REASONING_ORDER = ["current_ratio", "debt_to_ebitda", "debt_servicing_ratio", "gearing_ratio"] as const;

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
};

const TIER_LABELS: Record<string, string> = {
  excellent: "Excellent",
  good: "Good",
  acceptable: "Acceptable",
  approaching_limit: "Approaching limit",
  fail: "Fail",
  // Severity-band tiers (Current Ratio, Debt/EBITDA, Debt Servicing Ratio).
  borderline_saved_by_icr: "Borderline (saved by Interest Coverage)",
  borderline_fail: "Borderline — Fail",
  severe: "Severe — Fail",
  // Interest Coverage Ratio's own tiers (informational, no points of its own).
  safe: "Safe",
  tight: "Tight",
  dangerous: "Dangerous",
  not_applicable: "N/A",
};

function formatRatioValue(key: string, value: number | null): string {
  if (value == null) return "N/A";
  const PERCENT_RATIOS = new Set(["debt_servicing_ratio", "gearing_ratio", "npl_ratio"]);
  return PERCENT_RATIOS.has(key) ? fmtPct(value, 1) : `${fmtNumber(value, 2)}x`;
}

function tierClass(label: string): string {
  if (label === "fail" || label === "borderline_fail" || label === "severe" || label === "dangerous") return "text-negative";
  if (label === "approaching_limit" || label === "borderline_saved_by_icr" || label === "tight") return "text-warn";
  return "text-text-primary";
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
  const bullets: (ReasoningBullet | null)[] = REASONING_ORDER.map((key) => {
    const weight = data.weights[key];
    const ratio = data.ratios[key];
    if (weight == null || !ratio) return null;
    return {
      key,
      text: `${RATIO_LABELS[key] ?? key}: ${formatRatioValue(key, ratio.value)} (${TIER_LABELS[ratio.label] ?? ratio.label})`,
      tierClassName: tierClass(ratio.label),
    };
  });
  return bullets.filter((b): b is ReasoningBullet => b !== null);
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
    ? "CET1 ratio still unavailable from FMP — Debt verdict incomplete for Banks."
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
    <AnalysisSectionCard title="Debt" score={data.score} verdict={data.verdict} blurb={blurb} notes={notes} bullets={bullets} />
  );
}
