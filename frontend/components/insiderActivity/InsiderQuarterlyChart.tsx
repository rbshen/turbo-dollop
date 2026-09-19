"use client";

import { Bar, BarChart, XAxis, YAxis } from "recharts";

import { ChartLegend } from "@/components/charts/ChartLegend";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { InsiderQuarterStat } from "@/lib/api/types";
import { fmtCompactNumber } from "@/lib/format";
import { quarterLabel } from "@/lib/insiderActivity";

interface Props {
  // Oldest first, as served.
  stats: InsiderQuarterStat[];
}

// Three years of quarters -- the statistics endpoint returns every quarter
// on record, far more than reads well as a trend.
const MAX_QUARTERS = 12;

const SERIES = [
  { key: "total_acquired", label: "Acquired", color: "var(--color-positive)" },
  { key: "total_disposed", label: "Disposed", color: "var(--color-negative)" },
] as const;

const chartConfig: ChartConfig = Object.fromEntries(SERIES.map((s) => [s.key, { label: s.label, color: s.color }]));

// Shares acquired vs. disposed per filed quarter -- two series per category
// (grouped, not stacked). Same hidden-axis/hover-tooltip style as the app's
// other bar charts; the XAxis stays mounted (hidden ticks aside) since the
// tooltip needs it to resolve the category label.
export function InsiderQuarterlyChart({ stats }: Props) {
  const recent = stats.slice(-MAX_QUARTERS);
  if (recent.length === 0) {
    return <p className="text-sm text-text-tertiary">No quarterly statistics available for this ticker.</p>;
  }

  const data = recent.map((s) => ({
    category: quarterLabel(s.year, s.quarter),
    total_acquired: s.total_acquired,
    total_disposed: s.total_disposed,
  }));

  return (
    <div className="space-y-3">
      <ChartContainer
        config={chartConfig}
        className="aspect-auto w-full"
        style={{ height: 216 }}
        role="img"
        aria-label="Shares acquired and disposed by insiders per quarter"
      >
        <BarChart data={data} barCategoryGap="12%" barGap={2}>
          <XAxis
            dataKey="category"
            tickLine={false}
            axisLine={false}
            interval={0}
            tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }}
          />
          <YAxis hide />
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value, name) => (
                  <div className="flex w-full flex-1 items-center gap-2">
                    <div
                      className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                      style={{ backgroundColor: chartConfig[name as string]?.color }}
                    />
                    <div className="flex flex-1 items-center justify-between gap-4">
                      <span className="text-muted-foreground">{chartConfig[name as string]?.label ?? name}</span>
                      <span className="font-mono font-medium tabular-nums">{fmtCompactNumber(Number(value))}</span>
                    </div>
                  </div>
                )}
              />
            }
          />
          {SERIES.map((s) => (
            <Bar key={s.key} dataKey={s.key} fill={s.color} isAnimationActive={false} />
          ))}
        </BarChart>
      </ChartContainer>
      <ChartLegend items={SERIES.map((s) => ({ key: s.key, label: s.label, color: s.color }))} layout="row" />
    </div>
  );
}
