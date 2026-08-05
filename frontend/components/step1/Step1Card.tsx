"use client";

import { AnalysisSectionCard, type ReasoningBullet } from "@/components/shared/AnalysisSectionCard";
import { useStep1 } from "@/lib/hooks/useStep1";
import type { Step1Out } from "@/lib/api/types";

interface Props {
  ticker: string;
}

// Order mirrors scoring/step1.py::score_step1's components dict -- revenue,
// net income and CFO are trend-classified (classify_trend's shared 8-pattern
// set), margins and FCF have their own smaller pattern sets (see CLAUDE.md's
// Step 1 deviations for why each label reads the way it does).
const METRIC_ORDER = ["revenue", "net_income", "cfo", "margins", "fcf"] as const;

const STATIC_METRIC_LABELS: Record<string, string> = {
  net_income: "Net Income",
  cfo: "Cash Flow from Operations",
  margins: "Margins",
  fcf: "Free Cash Flow",
};

// Short, lowercase forms for the blurb's parenthetical component list --
// distinct from STATIC_METRIC_LABELS (used for the bullet rows/headings),
// which are full Title Case labels too long to read naturally inline.
const BLURB_METRIC_LABELS: Record<string, string> = {
  revenue: "revenue",
  net_income: "income",
  cfo: "cash flow",
  margins: "margins",
  fcf: "free cash flow",
};

const TIER_LABELS: Record<string, string> = {
  insufficient_data: "Insufficient data",
  // classify_trend (revenue / net income / CFO)
  declining: "Declining (TTM down)",
  grows_every_year: "Grows every year",
  multiple_dips: "Dip(s), not yet recovered",
  small_dip_recovers: "Small dip, recovered",
  significant_dip_recovers: "Significant dip, recovered",
  flat_then_spike: "Flat, then sudden spike",
  multiple_dips_resolved: "Past dips, fully recovered",
  // margins
  sharply_declining: "Sharply declining",
  gradually_compressing: "Gradually compressing",
  stable_or_expanding: "Stable or expanding",
  wildly_inconsistent: "Wildly inconsistent",
  // FCF
  consistently_positive: "Consistently positive",
  sustained_cash_burn: "Sustained cash burn",
  cash_burn_recovered: "Cash burn, since recovered",
  isolated_dip: "Isolated negative year",
  scattered_negative_years: "Scattered negative years",
};

function tierClass(score: number): string {
  if (score === 0) return "text-negative";
  if (score < 70) return "text-warn";
  return "text-text-primary";
}

function metricLabel(key: string, data: Step1Out): string {
  if (key === "revenue") return data.revenue_label;
  return STATIC_METRIC_LABELS[key] ?? key;
}

export function Step1Card({ ticker }: Props) {
  const { data, error } = useStep1(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-negative">Couldn&apos;t load Financials data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Financials…</p>
      </div>
    );
  }

  if (data.verdict === "insufficient_data" || data.score == null) {
    return (
      <div className="space-y-2 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Financials</h2>
        <p className="text-sm text-text-tertiary">Required figures were unavailable for {ticker}.</p>
      </div>
    );
  }

  const componentRows = METRIC_ORDER.map((key) => {
    const component = data.components[key as keyof typeof data.components];
    if (!component) return null;
    return {
      key,
      label: metricLabel(key, data),
      tierLabel: TIER_LABELS[component.pattern] ?? component.pattern,
      score: component.score,
    };
  }).filter((row): row is NonNullable<typeof row> => row !== null);

  const strongCount = componentRows.filter((r) => r.score >= 70).length;
  const scoredComponents = componentRows.map((r) => BLURB_METRIC_LABELS[r.key] ?? r.key).join(", ");
  const blurb = `${strongCount} of ${componentRows.length} components (${scoredComponents}) score at Pass level or better.`;

  const bullets: ReasoningBullet[] = componentRows.map((row) => ({
    key: row.key,
    text: `${row.label}: ${row.tierLabel}`,
    tierClassName: tierClass(row.score),
  }));

  const notes = data.cfo_exempt_reason ? (
    <p className="text-xs text-text-tertiary">
      Cash Flow and Free Cash Flow aren&apos;t scored for this company — classified as a {data.cfo_exempt_reason}.
    </p>
  ) : null;

  return (
    <AnalysisSectionCard
      title="Financials"
      score={data.score}
      verdict={data.verdict}
      blurb={blurb}
      notes={notes}
      bullets={bullets}
    />
  );
}
