"use client";

import { Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts";

import { ChartLegend } from "@/components/charts/ChartLegend";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { PeHistoryOut } from "@/lib/api/types";
import { capXAxisTickInterval } from "@/lib/charts";
import { fmtPeMonth, peYRange, visibleValues } from "@/lib/peHistory";

interface Props {
  data: PeHistoryOut;
  showStock: boolean;
  showSector: boolean;
  showIndustry: boolean;
}

// Multi-series convention (docs/design-system-charts.md): series-1, -2, -3 in order; one shared P/E axis.
const STOCK_COLOR = "var(--color-series-1)";
const SECTOR_COLOR = "var(--color-series-2)";
const INDUSTRY_COLOR = "var(--color-series-3)";

export function PeHistoryChart({ data, showStock, showSector, showIndustry }: Props) {
  const points = data.points.map((p) => ({
    date: p.date,
    stock: showStock ? p.stock : null,
    sector: showSector ? p.sector : null,
    industry: showIndustry ? p.industry : null,
  }));
  const range = peYRange(
    visibleValues(
      points.map((p) => ({ date: p.date, stock: p.stock, sector: p.sector, industry: p.industry })),
      showSector,
      showIndustry
    )
  );
  const labels = {
    stock: "Stock P/E",
    sector: `${data.sector ?? "Sector"}: ${data.label}`,
    industry: `${data.industry ?? "Industry"}: ${data.label}`,
  };
  const config: ChartConfig = {
    stock: { label: labels.stock, color: STOCK_COLOR },
    sector: { label: labels.sector, color: SECTOR_COLOR },
    industry: { label: labels.industry, color: INDUSTRY_COLOR },
  };
  const legend = [
    ...(showStock ? [{ key: "stock", label: labels.stock, color: STOCK_COLOR }] : []),
    ...(showSector ? [{ key: "sector", label: labels.sector, color: SECTOR_COLOR }] : []),
    ...(showIndustry ? [{ key: "industry", label: labels.industry, color: INDUSTRY_COLOR }] : []),
  ];
  // The ticker line starts after the window does (young listing, few cached quarters): mark where, rather than leave
  // the gap to be read as "no P/E".
  const showStartMarker = showStock && data.stock_starts != null && data.points.length > 0 && data.stock_starts > data.points[0].date;

  const lineProps = { type: "monotone" as const, strokeWidth: 2, dot: false, activeDot: { r: 4, strokeWidth: 0 }, connectNulls: false, isAnimationActive: false };

  return (
    <div className="space-y-3">
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height: 216 }} role="img" aria-label="P/E history chart">
        <LineChart data={points}>
          <XAxis
            dataKey="date"
            tickLine={false}
            axisLine={false}
            interval={capXAxisTickInterval(points.length, 8)}
            tickFormatter={fmtPeMonth}
            tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }}
          />
          <YAxis domain={range.domain} ticks={range.ticks} allowDataOverflow hide />
          {showStartMarker && (
            <ReferenceLine
              x={data.stock_starts as string}
              stroke="var(--color-text-tertiary)"
              strokeDasharray="2 3"
              label={{ value: "Stock P/E starts →", position: "insideTopLeft", fill: "var(--color-text-tertiary)", fontSize: 10 }}
            />
          )}
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value, name) =>
                  value == null ? null : (
                    <div className="flex w-full flex-1 items-center gap-2">
                      <div className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: config[name as string]?.color }} />
                      <div className="flex flex-1 items-center justify-between gap-4">
                        <span className="text-text-secondary">{config[name as string]?.label ?? name}</span>
                        <span className="font-mono font-semibold tabular-nums text-text-primary">{Number(value).toFixed(1)}</span>
                      </div>
                    </div>
                  )
                }
              />
            }
          />
          {showSector && <Line dataKey="sector" stroke={SECTOR_COLOR} {...lineProps} />}
          {showIndustry && <Line dataKey="industry" stroke={INDUSTRY_COLOR} {...lineProps} />}
          {showStock && <Line dataKey="stock" stroke={STOCK_COLOR} {...lineProps} />}
        </LineChart>
      </ChartContainer>
      <ChartLegend items={legend} />
      {range.clippedCount > 0 && (
        <p className="text-xs text-text-tertiary">
          {range.clippedCount} {range.clippedCount === 1 ? "day" : "days"} above {range.domain[1]} not shown; hover for the exact value.
        </p>
      )}
    </div>
  );
}
