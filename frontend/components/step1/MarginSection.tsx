"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
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
}

export function MarginSection({ data }: Props) {
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

      <RechartsGroupedChart
        categories={data.years}
        series={MARGIN_SERIES}
        values={values}
        mode={mode}
        yTicks={MARGIN_TICKS}
        yTickFormat={(v) => `${v}%`}
      />

      <div className="flex">
        <table className="shrink-0 border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
              <th className="whitespace-nowrap border-b border-zinc-800 py-2 pr-8 font-medium">Metric</th>
            </tr>
          </thead>
          <tbody>
            {MARGIN_SERIES.map((s) => (
              <tr key={s.key}>
                <td className="whitespace-nowrap border-b border-zinc-900 py-2 pr-8 text-zinc-400">
                  <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ backgroundColor: s.color }} />
                  {s.label}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex-1 overflow-x-auto">
          <table className="w-full min-w-max border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
                {data.years.map((year) => (
                  <th key={year} className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">
                    {year}
                  </th>
                ))}
                <th className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">Avg</th>
              </tr>
            </thead>
            <tbody>
              {MARGIN_SERIES.map((s) => {
                const series = values[s.key];
                const avg = average(series);
                return (
                  <tr key={s.key}>
                    {series.map((v, i) => (
                      <td key={i} className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                        {v != null ? `${v.toFixed(2)}%` : "—"}
                      </td>
                    ))}
                    <td className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                      {avg != null ? `${avg.toFixed(2)}%` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
