"use client";

import { AnalysisSectionCard, type ReasoningBullet } from "@/components/shared/AnalysisSectionCard";
import { useStep4 } from "@/lib/hooks/useStep4";

interface Props {
  ticker: string;
}

const METRIC_LABELS: Record<string, string> = {
  roe: "Return on Equity",
  roic: "Return on Invested Capital",
  revenue_vs_ar: "Revenue vs Accounts Receivable",
  ccc: "Cash Conversion Cycle",
};

const TIER_LABELS: Record<string, string> = {
  excellent: "Excellent",
  good: "Good",
  marginal: "Marginal",
  fail: "Fail",
  positive_despite_negative_equity: "Positive (negative equity exception)",
  negative_equity_inconsistent_income: "Inconsistent (negative equity)",
  insufficient_data: "Insufficient data",
  healthy: "Healthy",
  outpacing_isolated: "Isolated outpacing",
  outpacing_concerning: "Concerning pattern",
  outpacing_majority_or_red_flag: "Red flag",
  declining_or_stable: "Declining / stable",
  volatile_but_net_declining: "Volatile, net declining",
  volatile_no_trend: "Volatile, no trend",
  sustained_upward: "Sustained upward",
  consistently_negative_strengthening: "Negative & strengthening (suppliers fund the business)",
  consistently_negative_weakening: "Negative, still strong (direction easing)",
  gained_bargaining_power: "Turned negative (gained supplier leverage)",
  lost_bargaining_power: "Turned positive (losing supplier leverage)",
  negligible_working_capital: "Negligible (low working-capital need)",
  mixed_unclear: "Mixed, no clear pattern — investigate",
};

function tierClass(points: number): string {
  if (points === 0) return "text-negative";
  if (points < 70) return "text-warn";
  return "text-text-primary";
}

export function Step4Card({ ticker }: Props) {
  const { data, error } = useStep4(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-negative">Couldn&apos;t load Profitability data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Profitability…</p>
      </div>
    );
  }

  if (data.verdict === "insufficient_data" || data.score == null) {
    return (
      <div className="space-y-2 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Profitability</h2>
        <p className="text-sm text-text-tertiary">Required figures were unavailable for {ticker}.</p>
      </div>
    );
  }

  const componentRows = Object.entries(data.components)
    .filter((entry): entry is [string, { label?: string; pattern?: string; points: number }] => entry[1] != null)
    .map(([key, c]) => ({ key, points: c.points, tierKey: c.label ?? c.pattern ?? "" }));

  const bullets: ReasoningBullet[] = componentRows.map((row) => ({
    key: row.key,
    text: `${METRIC_LABELS[row.key] ?? row.key}: ${TIER_LABELS[row.tierKey] ?? row.tierKey}`,
    tierClassName: tierClass(row.points),
  }));

  const blurb = data.hard_fail
    ? "ROE or ROIC landed in its Fail tier, so this fails regardless of the blended score."
    : "Neither ROE nor ROIC breached its Fail tier.";

  const notes = (
    <>
      {data.roic_exempt_reason && <p className="text-xs text-text-tertiary">{data.roic_exempt_reason}</p>}
      {data.ccc_exempt_reason && <p className="text-xs text-text-tertiary">{data.ccc_exempt_reason}</p>}
      {data.revenue_vs_ar_exempt_reason && <p className="text-xs text-text-tertiary">{data.revenue_vs_ar_exempt_reason}</p>}
      {data.roe_roic_divergence_note && <p className="text-xs text-warn">{data.roe_roic_divergence_note}</p>}
    </>
  );

  return (
    <AnalysisSectionCard
      title="Profitability"
      score={data.score}
      verdict={data.verdict}
      blurb={blurb}
      notes={notes}
      bullets={bullets}
    />
  );
}
