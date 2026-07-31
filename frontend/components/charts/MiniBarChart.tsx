"use client";

import { Bar, BarChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { computeNiceTicksRange } from "@/lib/charts";

interface Props {
  categories: string[];
  values: (number | null)[];
  /** Formats a hovered bar's value for the tooltip (2-decimal, signed --
   * see HistoricalTrendsGrid's per-metric fmtCompactMoney/fmtPct/fmtDays
   * choice). No tooltip is shown if omitted. */
  valueFormat?: (v: number) => string;
  color?: string;
  height?: number;
}

// Single-series, axis-free preview bar chart for the Financials tab's
// "Historical Trends" grid -- 11 of these render at once, so it's kept
// deliberately minimal (no gridlines or ticks) unlike the full-size charts
// elsewhere in the app. A hover tooltip (period + formatted value) is the
// only way to read an exact figure off a given bar, since there's no axis.
export function MiniBarChart({ categories, values, valueFormat, color = "var(--color-brand)", height = 64 }: Props) {
  const chartData = categories.map((cat, i) => ({ category: cat, value: values[i] ?? null }));
  const nums = values.filter((v): v is number => v != null);
  const yTicks = computeNiceTicksRange(Math.min(0, ...nums, 0), Math.max(0, ...nums, 0));
  const domain: [number, number] = [yTicks[0] ?? 0, yTicks[yTicks.length - 1] ?? 1];

  const chartConfig: ChartConfig = { value: { label: "Value", color } };

  return (
    <ChartContainer config={chartConfig} className="aspect-auto w-full" style={{ height }} role="img" aria-label="Historical trend">
      <BarChart data={chartData} barCategoryGap="20%">
        {/* No dataKey on YAxis needed, but XAxis's dataKey is what lets
            Recharts resolve the tooltip's `label` to the period string --
            without it (chart previously had no XAxis at all), the tooltip
            fell back to the series config's own "Value" label instead. */}
        <XAxis dataKey="category" hide />
        <YAxis domain={domain} hide />
        {valueFormat && (
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value) => (
                  <span className="font-mono font-semibold tabular-nums text-text-primary">{valueFormat(Number(value))}</span>
                )}
              />
            }
          />
        )}
        <Bar dataKey="value" fill={color} radius={1} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  );
}
