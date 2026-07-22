"use client";

import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { BAR_GAP, BAR_WIDTH } from "@/lib/charts";

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
}

interface Props {
  categories: string[];
  series: ChartSeries[];
  values: Record<string, (number | null)[]>;
  mode: "bar" | "line";
  yTicks: number[];
  yTickFormat: (v: number) => string;
  height?: number;
}

// Recharts/shadcn-based chart, replacing the old hand-rolled SVG
// GroupedBarLineChart. ChartContainer's own ResponsiveContainer measures
// width automatically, replacing the old component's manual
// useElementWidth plumbing (no containerWidth prop needed here).
export function RechartsGroupedChart({ categories, series, values, mode, yTicks, yTickFormat, height = 216 }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  const chartData = categories.map((cat, i) => {
    const row: Record<string, string | number | null> = { category: cat };
    for (const s of series) {
      row[s.key] = values[s.key]?.[i] ?? null;
    }
    return row;
  });

  const chartConfig: ChartConfig = Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }]));

  const domain: [number, number] = [yTicks[0] ?? 0, yTicks[yTicks.length - 1] ?? 1];

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto w-full"
      style={{ height }}
      role="img"
      aria-label="Financial trend chart"
    >
      <ComposedChart data={chartData} barGap={BAR_GAP} barCategoryGap="20%">
        <CartesianGrid vertical={false} stroke="#27272a" />
        <XAxis dataKey="category" tickLine={false} axisLine={false} tick={{ fill: "#71717a", fontSize: 10 }} />
        <YAxis
          domain={domain}
          ticks={yTicks}
          tickFormatter={yTickFormat}
          tickLine={false}
          axisLine={false}
          tick={{ fill: "#71717a", fontSize: 10 }}
          width={56}
        />
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
                    <span className="font-mono font-medium tabular-nums">{yTickFormat(Number(value))}</span>
                  </div>
                </div>
              )}
            />
          }
        />
        {series.map((s) => {
          const opacity = hovered === null || hovered === s.key ? 1 : 0.25;
          return mode === "bar" ? (
            <Bar
              key={s.key}
              dataKey={s.key}
              fill={s.color}
              fillOpacity={opacity}
              barSize={BAR_WIDTH}
              radius={2}
              isAnimationActive={false}
              onMouseEnter={() => setHovered(s.key)}
              onMouseLeave={() => setHovered(null)}
            />
          ) : (
            <Line
              key={s.key}
              type="linear"
              dataKey={s.key}
              stroke={s.color}
              strokeOpacity={opacity}
              strokeWidth={2}
              dot={{ r: 3, fill: s.color, fillOpacity: opacity, strokeWidth: 0 }}
              activeDot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={false}
              onMouseEnter={() => setHovered(s.key)}
              onMouseLeave={() => setHovered(null)}
            />
          );
        })}
      </ComposedChart>
    </ChartContainer>
  );
}
