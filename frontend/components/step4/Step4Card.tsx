"use client";

import { AnalysisSectionCard, type ReasoningBullet, weightScoreSuffix } from "@/components/shared/AnalysisSectionCard";
import { useStep4 } from "@/lib/hooks/useStep4";

interface Props {
  ticker: string;
}

const METHODOLOGY =
  "A weighted blend of Return on Equity, Return on Invested Capital, Revenue vs. Accounts Receivable, and Cash " +
  "Conversion Cycle (ROIC/CCC/Revenue-vs-AR excluded and reweighted for Bank/Insurance/Utility/REIT); a Fail-tier " +
  "ROE or ROIC forces a Fail regardless of the blended score.";

function joinWithAnd(items: string[]): string {
  if (items.length <= 1) return items.join("");
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
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
  weak_but_positive: "Weak (never negative)",
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
    .filter((entry): entry is [string, { label?: string; pattern?: string; points: number; note?: string | null }] => entry[1] != null)
    .map(([key, c]) => ({ key, points: c.points, tierKey: c.label ?? c.pattern ?? "", note: c.note }));

  const bullets: ReasoningBullet[] = componentRows.flatMap((row) => {
    const suffix = weightScoreSuffix(data.weights[row.key], row.points);
    const bullet: ReasoningBullet = {
      key: row.key,
      text: `${METRIC_LABELS[row.key] ?? row.key}${suffix}: ${TIER_LABELS[row.tierKey] ?? row.tierKey}`,
      tierClassName: tierClass(row.points),
    };
    // Manual-check note (OCF vs Net Income, business-model-shift prompt) --
    // only present on Revenue-vs-AR when it landed in a non-healthy tier
    // (backend/step4_data.py::_build_ar_note). Nested directly under its
    // own bullet, same "↳" sub-bullet convention Step5Card.tsx uses for
    // breach-context detail text.
    if (!row.note) return [bullet];
    return [
      bullet,
      { key: `${row.key}-note`, text: `↳ ${row.note}`, tierClassName: "text-text-tertiary" },
    ];
  });

  // Profitability's `hard_fail` only fires from ROE/ROIC's own Fail tier
  // (avg <8%) -- a ticker can still land on a Fail verdict via the
  // companion score<70 floor (`_verdict_for`, see CLAUDE.md's Profitability
  // deviations) with hard_fail=false, e.g. weak-but-positive ROE/ROIC
  // dragging the blend down without either one outright failing. Naming
  // the actual weak components (instead of restating "Neither ROE nor ROIC
  // breached its Fail tier" next to a Fail badge) avoids that contradiction.
  const weakComponents = componentRows.filter((row) => row.points < 70).map((row) => METRIC_LABELS[row.key] ?? row.key);
  const blurb = data.hard_fail
    ? "ROE or ROIC landed in its Fail tier, so this fails regardless of the blended score."
    : data.verdict === "Fail"
      ? `Neither ROE nor ROIC breached its Fail tier outright, but ${joinWithAnd(weakComponents)} still pulled the blended score below the Pass threshold.`
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
      methodology={METHODOLOGY}
      notes={notes}
      bullets={bullets}
    />
  );
}
