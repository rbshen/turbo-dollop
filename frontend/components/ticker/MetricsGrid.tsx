import { Fragment } from "react";

import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { fmtCompactMoney, fmtCompactNumber, fmtNumber, fmtPct, fmtRatio } from "@/lib/format";
import type { MetricDef, MetricGroup } from "@/lib/metrics/config";
import type { OutlierWarning, TickerSummaryOut } from "@/lib/api/types";

const FLAG_TITLE = "Looks anomalous compared to trailing history — verify independently before relying on this number";

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

// Each group renders whole within its assigned column (see MetricGroup's
// `column` field in lib/metrics/config.ts) -- groups are never split
// across the two side-by-side tables.
function StatColumn({ groups, values, flaggedKeys }: StatColumnProps) {
  return (
    <Table className="border-separate border-spacing-0 text-sm">
      <TableBody>
        {groups.map((group) => (
          <Fragment key={group.title}>
            <TableRow className="hover:bg-transparent">
              <TableCell
                colSpan={2}
                className="border-b border-zinc-900 pt-4 pb-1 text-xs font-semibold uppercase tracking-widest text-zinc-500"
              >
                {group.title}
              </TableCell>
            </TableRow>
            {group.metrics.map((metric) => (
              <TableRow key={metric.key} className="hover:bg-transparent">
                <TableCell className="whitespace-nowrap border-b border-zinc-900 py-2 pr-8 text-xs font-medium uppercase tracking-widest text-zinc-500">
                  {metric.label}
                </TableCell>
                <TableCell className="border-b border-zinc-900 py-2 text-right font-mono tabular-nums text-zinc-100">
                  {formatValue(values[metric.key], metric.format)}
                  {flaggedKeys.has(metric.key) && (
                    <span className="ml-1.5 text-amber-400" title={FLAG_TITLE}>
                      ⚠
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </Fragment>
        ))}
      </TableBody>
    </Table>
  );
}

export function MetricsGrid({ groups, values, outlierWarnings = [] }: Props) {
  const flaggedKeys = new Set(outlierWarnings.map((w) => w.metric));
  const labels = Object.fromEntries(groups.flatMap((g) => g.metrics).map((m) => [m.key, m.label]));

  const leftGroups = groups.filter((g) => g.column === "left");
  const rightGroups = groups.filter((g) => g.column === "right");

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-x-8 lg:grid-cols-2">
        <StatColumn groups={leftGroups} values={values} flaggedKeys={flaggedKeys} />
        <StatColumn groups={rightGroups} values={values} flaggedKeys={flaggedKeys} />
      </div>

      <OutlierWarningNote warnings={outlierWarnings} labels={labels} />
    </div>
  );
}
