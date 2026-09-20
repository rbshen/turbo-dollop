"use client";

import { Bar, BarChart, XAxis, YAxis } from "recharts";

import { ChartLegend } from "@/components/charts/ChartLegend";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { InsiderQuarterActivity } from "@/lib/api/types";
import { fmtCompactNumber } from "@/lib/format";
import { type InsiderView, quarterlyBars } from "@/lib/insiderActivity";

interface Props {
  // Oldest first, as served (already limited to the 12-quarter window).
  activity: InsiderQuarterActivity[];
  view: InsiderView;
}

const SERIES = [
  { key: "acquired", label: "Acquired", color: "var(--color-positive)" },
  { key: "disposed", label: "Disposed", color: "var(--color-negative)" },
] as const;

const chartConfig: ChartConfig = Object.fromEntries(SERIES.map((s) => [s.key, { label: s.label, color: s.color }]));

// Shares acquired vs. disposed per calendar quarter -- two series per category
// (grouped, not stacked). Same hidden-axis/hover-tooltip style as the app's
// other bar charts; the XAxis stays mounted (hidden ticks aside) since the
// tooltip needs it to resolve the category label. The series comes from the
// transactions themselves, so `view` just picks which totals to read: the
// open-market ones, or the all-types ones.
export function InsiderQuarterlyChart({ activity, view }: Props) {
  const data = quarterlyBars(activity, view);
  if (data.length === 0) {
    return <p className="text-sm text-text-tertiary">No quarterly activity available for this ticker.</p>;
  }
  if (data.every((d) => d.acquired === 0 && d.disposed === 0)) {
    return (
      <p className="text-sm text-text-tertiary">
        No open-market buys or sales in these quarters — switch to “All types” to see the other transactions.
      </p>
    );
  }

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
