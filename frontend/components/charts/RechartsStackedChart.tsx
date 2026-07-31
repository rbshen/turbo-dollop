"use client";

import { useState } from "react";
import { Bar, BarChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { ChartSeries } from "@/components/charts/RechartsGroupedChart";

// Thicker bars with a small fixed gap between years, not the shared
// lib/charts.ts BAR_WIDTH/BAR_GAP (tuned for the denser grouped-metric
// charts elsewhere) -- this chart has only one bar per category (segments
// stack into it), so it can afford to run wide.
const STACKED_BAR_SIZE = 44;

interface Props {
  categories: string[];
  series: ChartSeries[];
  values: Record<string, (number | null)[]>;
  yTicks: number[];
  yTickFormat: (v: number) => string;
  height?: number;
}

/** Stacked-bar sibling to RechartsGroupedChart -- same categories/series/
 * values prop shape, but every Bar shares one stackId instead of being
 * grouped side by side. Used for the Summary tab's revenue-by-segment and
 * revenue-by-geography charts, where the segment list is dynamic
 * per-company free text rather than a fixed metric set. */
export function RechartsStackedChart({ categories, series, values, yTicks, yTickFormat, height = 216 }: Props) {
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
      aria-label="Revenue breakdown chart"
    >
      <BarChart data={chartData} barCategoryGap="12%">
        <XAxis dataKey="category" tickLine={false} axisLine={false} tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }} />
        {/* Y-axis kept mounted (for the same domain/headroom the tooltip's
            yTickFormat relies on) but fully hidden -- no ticks, labels, or
            gridlines. */}
        <YAxis domain={domain} ticks={yTicks} hide />
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
          return (
            <Bar
              key={s.key}
              dataKey={s.key}
              stackId="segments"
              fill={s.color}
              fillOpacity={opacity}
              barSize={STACKED_BAR_SIZE}
              isAnimationActive={false}
              onMouseEnter={() => setHovered(s.key)}
              onMouseLeave={() => setHovered(null)}
            />
          );
        })}
      </BarChart>
    </ChartContainer>
  );
}
