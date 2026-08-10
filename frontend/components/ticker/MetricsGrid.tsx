import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { fmtCompactMoney, fmtCompactNumber, fmtNumber, fmtPct, fmtRatio } from "@/lib/format";
import type { MetricDef, MetricGroup } from "@/lib/metrics/config";
import type { OutlierWarning, TickerSummaryOut } from "@/lib/api/types";

const FLAG_TITLE = "Looks anomalous compared to trailing history — verify independently before relying on this number";
// Distinct icon from FLAG_TITLE's "⚠" -- a methodology caveat (this figure
// means something slightly different than usual), not a data-quality flag.
const TOOLTIP_ICON = "ⓘ";

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

interface StatColumnProps {
  groups: MetricGroup[];
  values: TickerSummaryOut;
  flaggedKeys: Set<string>;
}

// Each group renders as its own card, stacked within its assigned column
// (see MetricGroup's `column` field in lib/metrics/config.ts) -- groups
// are never split across the two side-by-side columns.
function StatColumn({ groups, values, flaggedKeys }: StatColumnProps) {
  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <div key={group.title} className="rounded-lg border border-border-card bg-surface p-5">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-text-secondary">{group.title}</h3>
          <Table className="border-separate border-spacing-0 text-sm">
            <TableBody>
              {group.metrics.map((metric) => (
                <TableRow key={metric.key} className="hover:bg-transparent">
                  <TableCell className="whitespace-nowrap border-b border-border-subtle py-2 pr-8 text-xs font-medium uppercase tracking-widest text-text-tertiary">
                    {metric.label}
                  </TableCell>
                  <TableCell className="border-b border-border-subtle py-2 text-right font-mono tabular-nums text-text-primary">
                    {formatValue(values[metric.key], metric.format)}
                    {flaggedKeys.has(metric.key) && (
                      <span className="ml-1.5 text-warn" title={FLAG_TITLE}>
                        ⚠
                      </span>
                    )}
                    {metric.tooltip && values[metric.tooltip.when] && (
                      <span className="ml-1.5 text-text-tertiary" title={metric.tooltip.text}>
                        {TOOLTIP_ICON}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ))}
    </div>
  );
}

export function MetricsGrid({ groups, values, outlierWarnings = [] }: Props) {
  const flaggedKeys = new Set(outlierWarnings.map((w) => w.metric));
  const labels = Object.fromEntries(groups.flatMap((g) => g.metrics).map((m) => [m.key, m.label]));

  const leftGroups = groups.filter((g) => g.column === "left");
  const rightGroups = groups.filter((g) => g.column === "right");

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <StatColumn groups={leftGroups} values={values} flaggedKeys={flaggedKeys} />
        <StatColumn groups={rightGroups} values={values} flaggedKeys={flaggedKeys} />
      </div>

      <OutlierWarningNote warnings={outlierWarnings} labels={labels} />
    </div>
  );
}
