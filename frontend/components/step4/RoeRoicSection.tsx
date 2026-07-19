"use client";

import { useState } from "react";

import { GroupedBarLineChart, type ChartSeries } from "@/components/charts/GroupedBarLineChart";
import { ModeToggle } from "@/components/charts/ModeToggle";
import type { Step4Out } from "@/lib/api/types";
import { computeNiceTicksRange } from "@/lib/charts";

type RoeRoicKey = "roe" | "roic";

const ALL_SERIES: (ChartSeries & { key: RoeRoicKey })[] = [
  { key: "roe", label: "Return on Equity", color: "#eb6834" },
  { key: "roic", label: "Return on Invested Capital", color: "#2a78d6" },
];

interface Props {
  data: Step4Out;
  chartWidth: number;
}

export function RoeRoicSection({ data, chartWidth }: Props) {
  const [mode, setMode] = useState<"bar" | "line">("bar");

  const series = ALL_SERIES.filter((s) => s.key !== "roic" || data.roic !== null);
  const values: Record<RoeRoicKey, (number | null)[]> = {
    roe: data.roe,
    roic: data.roic ?? [],
  };

  const allValues = series.flatMap((s) => values[s.key].filter((v): v is number => v != null));
  const yTicks = computeNiceTicksRange(Math.min(0, ...allValues), Math.max(0, ...allValues));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Return on equity / invested capital</h3>
        <ModeToggle mode={mode} onChange={setMode} />
      </div>

      <GroupedBarLineChart
        categories={data.years}
        series={series}
        values={values}
        mode={mode}
        yTicks={yTicks}
        yTickFormat={(v) => `${v}%`}
        containerWidth={chartWidth}
      />

      {data.roic === null && (
        <p className="text-xs text-zinc-500">ROIC not applicable — {data.roic_exempt_reason}</p>
      )}

      <div className="flex">
        <table className="shrink-0 border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
              <th className="whitespace-nowrap border-b border-zinc-800 py-2 pr-8 font-medium">Metric</th>
            </tr>
          </thead>
          <tbody>
            {series.map((s) => (
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
              </tr>
            </thead>
            <tbody>
              {series.map((s) => (
                <tr key={s.key}>
                  {values[s.key].map((v, i) => (
                    <td key={i} className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                      {v != null ? `${v.toFixed(2)}%` : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
