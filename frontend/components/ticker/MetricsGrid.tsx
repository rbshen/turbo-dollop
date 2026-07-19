import { Gear } from "@phosphor-icons/react";

import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { fmtCompactMoney, fmtNumber, fmtPct } from "@/lib/format";
import type { MetricDef } from "@/lib/metrics/config";
import type { OutlierWarning, TickerSummaryOut } from "@/lib/api/types";

interface StatCardProps {
  label: string;
  value: string;
  flagged?: boolean;
}

function StatCard({ label, value, flagged }: StatCardProps) {
  return (
    <div className="relative min-w-0 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3">
      {flagged && (
        <span
          className="absolute right-2 top-2 text-xs text-amber-400"
          title="Looks anomalous compared to trailing history — verify independently before relying on this number"
        >
          ⚠
        </span>
      )}
      <p className="text-xs font-medium uppercase tracking-widest text-zinc-500">{label}</p>
      <p className="mt-1 font-mono text-xl font-bold leading-none tabular-nums text-zinc-100">{value}</p>
    </div>
  );
}

function formatValue(value: TickerSummaryOut[keyof TickerSummaryOut], format: MetricDef["format"]): string {
  if (value == null || typeof value !== "number") return "—";
  if (format === "compactMoney") return fmtCompactMoney(value);
  if (format === "percent") return fmtPct(value);
  return fmtNumber(value);
}

interface Props {
  metrics: MetricDef[];
  values: TickerSummaryOut;
  outlierWarnings?: OutlierWarning[];
}

export function MetricsGrid({ metrics, values, outlierWarnings = [] }: Props) {
  const flaggedKeys = new Set(outlierWarnings.map((w) => w.metric));
  const labels = Object.fromEntries(metrics.map((m) => [m.key, m.label]));

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
        {metrics.map((metric) => (
          <StatCard
            key={metric.key}
            label={metric.label}
            value={formatValue(values[metric.key], metric.format)}
            flagged={flaggedKeys.has(metric.key)}
          />
        ))}
        <button
          type="button"
          className="flex min-w-0 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-zinc-700 px-4 py-3 text-zinc-500 transition-colors hover:border-zinc-500 hover:text-zinc-300"
        >
          <Gear size={18} />
          <span className="text-xs font-medium uppercase tracking-widest">Configure</span>
        </button>
      </div>

      <OutlierWarningNote warnings={outlierWarnings} labels={labels} />
    </div>
  );
}
