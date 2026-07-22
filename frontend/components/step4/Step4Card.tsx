"use client";

import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { CccSection } from "@/components/step4/CccSection";
import { RevenueArSection } from "@/components/step4/RevenueArSection";
import { RoeRoicSection } from "@/components/step4/RoeRoicSection";
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
};

function tierClass(points: number): string {
  if (points === 0) return "text-red-400";
  if (points < 70) return "text-amber-300";
  return "text-zinc-100";
}

export function Step4Card({ ticker }: Props) {
  const { data, error } = useStep4(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-red-400">Couldn&apos;t load Step 4 data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Step 4…</p>
      </div>
    );
  }

  if (data.verdict === "insufficient_data" || data.score == null) {
    return (
      <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">
          Step 4 · Profitable and operationally efficient
        </h2>
        <p className="text-sm text-zinc-500">Required figures were unavailable for {ticker}.</p>
      </div>
    );
  }

  const componentRows = Object.entries(data.components)
    .filter((entry): entry is [string, { label?: string; pattern?: string; points: number }] => entry[1] != null)
    .map(([key, c]) => ({ key, points: c.points, tierKey: c.label ?? c.pattern ?? "" }));

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">
          Step 4 · Profitable and operationally efficient
        </h2>
        <ScoreBadge score={data.score} verdict={data.verdict} />
      </div>

      <div className="space-y-1">
        <p className="text-sm text-zinc-300">
          Classified as <span className="font-medium text-zinc-100">{data.company_type}</span>
        </p>
        <p className="text-xs text-zinc-600">{data.classification_note}</p>
        {data.roic_exempt_reason && <p className="text-xs text-zinc-600">{data.roic_exempt_reason}</p>}
        {data.ccc_exempt_reason && <p className="text-xs text-zinc-600">{data.ccc_exempt_reason}</p>}
      </div>

      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
            <th className="border-b border-zinc-800 py-2 pr-4 font-medium">Metric</th>
            <th className="border-b border-zinc-800 py-2 text-right font-medium">Tier</th>
          </tr>
        </thead>
        <tbody>
          {componentRows.map((row) => (
            <tr key={row.key}>
              <td className="border-b border-zinc-900 py-2 pr-4 text-zinc-400">{METRIC_LABELS[row.key] ?? row.key}</td>
              <td className={`border-b border-zinc-900 py-2 text-right font-medium ${tierClass(row.points)}`}>
                {TIER_LABELS[row.tierKey] ?? row.tierKey}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="text-sm text-zinc-400">
        {data.hard_fail
          ? "ROE or ROIC landed in its Fail tier, so this fails regardless of the blended score shown above."
          : "Neither ROE nor ROIC breached its Fail tier."}
      </p>

      <div className="space-y-6">
        <RoeRoicSection data={data} />
        <RevenueArSection data={data} />
        <CccSection data={data} />
      </div>
    </div>
  );
}
