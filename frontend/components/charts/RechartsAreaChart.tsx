"use client";

import { useId } from "react";
import { Area, AreaChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { capXAxisTickInterval, computeNiceTicksRange } from "@/lib/charts";

interface Props {
  categories: string[];
  values: (number | null)[];
  /** Formats a hovered point's value for the tooltip. No tooltip is shown
   * if omitted. */
  valueFormat?: (v: number) => string;
  color?: string;
  height?: number;
}

/** Single-series smooth line + gradient-area chart -- for a time series
 * shown at a larger, standalone size (unlike MiniBarChart's dense-grid
 * house style). Visible, thinned x-axis (categories, e.g. dates); hidden
 * y-axis (domain/ticks kept mounted for headroom + tooltip formatting
 * only) -- matches RechartsStackedChart's own "visible x, hidden y"
 * convention, the one this app has established everywhere. A null value
 * produces a genuine gap in the line rather than a fake dip to 0. */
export function RechartsAreaChart({ categories, values, valueFormat, color = "var(--color-brand)", height = 216 }: Props) {
  const gradientId = `area-chart-${useId().replace(/:/g, "")}`;

  const chartData = categories.map((cat, i) => ({ category: cat, value: values[i] ?? null }));
  const nums = values.filter((v): v is number => v != null);
  const yTicks = computeNiceTicksRange(Math.min(0, ...nums, 0), Math.max(0, ...nums, 0));
  const domain: [number, number] = [yTicks[0] ?? 0, yTicks[yTicks.length - 1] ?? 1];

  const chartConfig: ChartConfig = { value: { label: "Value", color } };

  return (
    <ChartContainer config={chartConfig} className="aspect-auto w-full" style={{ height }} role="img" aria-label="Trend chart">
      <AreaChart data={chartData}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="category"
          tickLine={false}
          axisLine={false}
          interval={capXAxisTickInterval(categories.length)}
          tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }}
        />
        {/* Kept mounted (for the same domain/headroom the tooltip's
            valueFormat relies on) but fully hidden -- no ticks, labels, or
            gridlines, matching RechartsStackedChart's own Y axis. */}
        <YAxis domain={domain} ticks={yTicks} hide />
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
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          fill={`url(#${gradientId})`}
          dot={false}
          connectNulls={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}
