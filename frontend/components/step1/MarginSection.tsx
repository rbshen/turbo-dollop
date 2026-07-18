"use client";

import { useState } from "react";

import { GroupedBarLineChart, type ChartSeries } from "@/components/charts/GroupedBarLineChart";
import { ModeToggle } from "@/components/charts/ModeToggle";
import type { Step1Out } from "@/lib/api/types";

type MarginMetricKey = "gross_margin" | "net_margin";

const MARGIN_SERIES: (ChartSeries & { key: MarginMetricKey })[] = [
  { key: "gross_margin", label: "Gross Profit Margin", color: "#eb6834" },
  { key: "net_margin", label: "Net Profit Margin", color: "#2a78d6" },
];

const MARGIN_TICKS = [0, 25, 50, 75, 100];

function average(values: (number | null)[]): number | null {
  const nums = values.filter((v): v is number => v != null);
  if (!nums.length) return null;
  return nums.reduce((sum, v) => sum + v, 0) / nums.length;
}

interface Props {
  data: Step1Out;
  chartWidth: number;
}

export function MarginSection({ data, chartWidth }: Props) {
  const [mode, setMode] = useState<"bar" | "line">("bar");

  const values: Record<MarginMetricKey, (number | null)[]> = {
    gross_margin: data.gross_margin,
    net_margin: data.net_margin,
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Margins</h3>
        <ModeToggle mode={mode} onChange={setMode} />
      </div>

      <GroupedBarLineChart
        categories={data.years}
        series={MARGIN_SERIES}
        values={values}
        mode={mode}
        yTicks={MARGIN_TICKS}
        yTickFormat={(v) => `${v}%`}
        containerWidth={chartWidth}
      />

      <div className="overflow-x-auto">
        <table className="w-full min-w-max text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-widest text-zinc-500">
              <th className="sticky left-0 z-10 bg-zinc-900 py-2 pr-4 font-medium">Metric</th>
              {data.years.map((year) => (
                <th key={year} className="py-2 pr-4 text-right font-medium">
                  {year}
                </th>
              ))}
              <th className="py-2 pr-4 text-right font-medium">Avg</th>
            </tr>
          </thead>
          <tbody>
            {MARGIN_SERIES.map((s) => {
              const series = values[s.key];
              const avg = average(series);
              return (
                <tr key={s.key} className="border-b border-zinc-900">
                  <td className="sticky left-0 z-10 bg-zinc-900 py-2 pr-4 text-zinc-400">
                    <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ backgroundColor: s.color }} />
                    {s.label}
                  </td>
                  {series.map((v, i) => (
                    <td key={i} className="py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                      {v != null ? `${v.toFixed(2)}%` : "—"}
                    </td>
                  ))}
                  <td className="py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                    {avg != null ? `${avg.toFixed(2)}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
