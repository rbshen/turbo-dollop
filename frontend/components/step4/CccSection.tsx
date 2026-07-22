"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
import type { Step4Out } from "@/lib/api/types";
import { computeNiceTicksRange } from "@/lib/charts";

const SERIES: ChartSeries[] = [{ key: "ccc", label: "Cash Conversion Cycle", color: "#eb6834" }];

interface Props {
  data: Step4Out;
}

export function CccSection({ data }: Props) {
  const [mode, setMode] = useState<"bar" | "line">("bar");

  if (data.ccc === null) {
    return (
      <div className="space-y-3">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Cash Conversion Cycle</h3>
        <p className="text-sm text-zinc-500">Not applicable — {data.ccc_exempt_reason}</p>
      </div>
    );
  }

  const values: Record<"ccc", (number | null)[]> = { ccc: data.ccc };
  const nums = data.ccc.filter((v): v is number => v != null);
  const yTicks = computeNiceTicksRange(Math.min(0, ...nums), Math.max(0, ...nums));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Cash Conversion Cycle</h3>
        <ModeToggle mode={mode} onChange={setMode} />
      </div>

      <RechartsGroupedChart
        categories={data.years}
        series={SERIES}
        values={values}
        mode={mode}
        yTicks={yTicks}
        yTickFormat={(v) => `${v}d`}
      />

      <div className="flex">
        <table className="shrink-0 border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
              <th className="whitespace-nowrap border-b border-zinc-800 py-2 pr-8 font-medium">Metric</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="whitespace-nowrap border-b border-zinc-900 py-2 pr-8 text-zinc-400">
                <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ backgroundColor: SERIES[0].color }} />
                {SERIES[0].label}
              </td>
            </tr>
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
              <tr>
                {data.ccc.map((v, i) => (
                  <td key={i} className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                    {v != null ? `${v.toFixed(1)}d` : "—"}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
