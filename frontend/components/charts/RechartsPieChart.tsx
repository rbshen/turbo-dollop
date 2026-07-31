"use client";

import { useState } from "react";
import { Cell, Pie, PieChart } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { ChartSeries } from "@/components/charts/RechartsStackedChart";

interface Props {
  series: ChartSeries[];
  values: Record<string, number | null>;
  valueFormat: (v: number) => string;
  height?: number;
}

// Donut-chart sibling to RechartsStackedChart, for the Summary tab's
// latest-FY snapshot row -- a single period's part-of-whole breakdown
// rather than a multi-year trend, so it doesn't fit that sibling's
// categories/array-per-series values shape.
export function RechartsPieChart({ series, values, valueFormat, height = 216 }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  const data = series
    .map((s) => ({ key: s.key, color: s.color, value: values[s.key] }))
    .filter((d): d is { key: string; color: string; value: number } => d.value != null);

  const chartConfig: ChartConfig = Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }]));

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto w-full"
      style={{ height }}
      role="img"
      aria-label="Revenue breakdown donut chart"
    >
      <PieChart>
        <ChartTooltip
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
                    <span className="font-mono font-medium tabular-nums">{valueFormat(Number(value))}</span>
                  </div>
                </div>
              )}
            />
          }
        />
        <Pie
          data={data}
          dataKey="value"
          nameKey="key"
          innerRadius="55%"
          outerRadius="90%"
          paddingAngle={1}
          isAnimationActive={false}
        >
          {data.map((d) => (
            <Cell
              key={d.key}
              fill={d.color}
              fillOpacity={hovered === null || hovered === d.key ? 1 : 0.35}
              stroke="none"
              onMouseEnter={() => setHovered(d.key)}
              onMouseLeave={() => setHovered(null)}
            />
          ))}
        </Pie>
      </PieChart>
    </ChartContainer>
  );
}
