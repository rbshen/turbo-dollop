import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { fmtCompactMoney, fmtCompactNumber, fmtNumber, fmtPct, fmtRatio } from "@/lib/format";
import type { MetricDef, MetricGroup } from "@/lib/metrics/config";
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
      <p className="mt-1 truncate font-mono text-xl font-bold leading-none tabular-nums text-zinc-100">{value}</p>
    </div>
  );
}

function formatValue(value: TickerSummaryOut[keyof TickerSummaryOut], format: MetricDef["format"]): string {
  if (value == null) return "—";
  if (format === "text") return typeof value === "string" ? value : "—";
  if (typeof value !== "number") return "—";
  if (format === "compactMoney") return fmtCompactMoney(value);
  if (format === "compactNumber") return fmtCompactNumber(value);
  if (format === "percent") return fmtPct(value);
  if (format === "ratio") return fmtRatio(value);
  return fmtNumber(value);
}

interface Props {
  groups: MetricGroup[];
  values: TickerSummaryOut;
  outlierWarnings?: OutlierWarning[];
}

export function MetricsGrid({ groups, values, outlierWarnings = [] }: Props) {
  const flaggedKeys = new Set(outlierWarnings.map((w) => w.metric));
  const labels = Object.fromEntries(groups.flatMap((g) => g.metrics).map((m) => [m.key, m.label]));

  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <div key={group.title} className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">{group.title}</h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {group.metrics.map((metric) => (
              <StatCard
                key={metric.key}
                label={metric.label}
                value={formatValue(values[metric.key], metric.format)}
                flagged={flaggedKeys.has(metric.key)}
              />
            ))}
          </div>
        </div>
      ))}

      <OutlierWarningNote warnings={outlierWarnings} labels={labels} />
    </div>
  );
}
