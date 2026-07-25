"use client";

import { CaretDown } from "@phosphor-icons/react";

import { FinancialsSection } from "@/components/step1/FinancialsSection";
import { MarginSection } from "@/components/step1/MarginSection";
import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
  isolated_dip: "Isolated negative year",
  scattered_negative_years: "Scattered negative years",
};

function tierClass(score: number): string {
  if (score === 0) return "text-red-400";
  if (score < 70) return "text-amber-300";
  return "text-zinc-100";
}

function metricLabel(key: string, data: Step1Out): string {
  if (key === "revenue") return data.revenue_label;
  return STATIC_METRIC_LABELS[key] ?? key;
}

export function Step1Card({ ticker }: Props) {
  const { data, error } = useStep1(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-red-400">Couldn&apos;t load Step 1 data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Step 1…</p>
      </div>
    );
  }

  const componentRows = METRIC_ORDER.map((key) => {
    const component = data.components[key as keyof typeof data.components];
    if (!component) return null;
    const weight = data.weights[key] ?? 0;
    return {
      key,
      label: metricLabel(key, data),
      tierLabel: TIER_LABELS[component.pattern] ?? component.pattern,
      score: component.score,
      weight,
      contribution: Math.round(weight * component.score),
    };
  }).filter((row): row is NonNullable<typeof row> => row !== null);

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">
          Financials
        </h2>
        <ScoreBadge score={data.score} verdict={data.verdict} />
      </div>

      <Collapsible>
        <CollapsibleTrigger className="group flex items-center gap-1.5 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-300">
          <CaretDown size={12} className="transition-transform duration-200 group-data-[panel-open]:rotate-180" />
          Reasoning
        </CollapsibleTrigger>
        <CollapsibleContent>
          <table className="mt-3 w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
                <th className="border-b border-zinc-800 py-2 pr-4 font-medium">Metric</th>
                <th className="border-b border-zinc-800 py-2 pr-4 font-medium">Tier</th>
                <th className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">Weight</th>
                <th className="border-b border-zinc-800 py-2 text-right font-medium">Contribution</th>
              </tr>
            </thead>
            <tbody>
              {componentRows.map((row) => (
                <tr key={row.key}>
                  <td className="border-b border-zinc-900 py-2 pr-4 text-zinc-400">{row.label}</td>
                  <td className={`border-b border-zinc-900 py-2 pr-4 font-medium ${tierClass(row.score)}`}>
                    {row.tierLabel}
                  </td>
                  <td className="border-b border-zinc-900 py-2 pr-4 text-right text-zinc-400">
                    {Math.round(row.weight * 100)}%
                  </td>
                  <td className="border-b border-zinc-900 py-2 text-right text-zinc-100">{row.contribution} pts</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CollapsibleContent>
      </Collapsible>

      <div className="space-y-6">
        <FinancialsSection data={data} />
        <MarginSection data={data} />
      </div>
    </div>
  );
}
