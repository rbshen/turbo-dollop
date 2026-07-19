"use client";

import { useState } from "react";

import { GroupedBarLineChart, type ChartSeries } from "@/components/charts/GroupedBarLineChart";
import { ModeToggle } from "@/components/charts/ModeToggle";
import type { Step4Out } from "@/lib/api/types";
import { computeNiceTicks } from "@/lib/charts";
import { fmtAxisMoney, fmtTableMoney, pickAxisMoneyUnit } from "@/lib/format";

type RevenueArKey = "revenue" | "accounts_receivable";

const SERIES: (ChartSeries & { key: RevenueArKey })[] = [
  { key: "revenue", label: "Revenue", color: "#eda100" },
  { key: "accounts_receivable", label: "Accounts Receivable", color: "#2a78d6" },
];

interface Props {
  data: Step4Out;
  chartWidth: number;
}

export function RevenueArSection({ data, chartWidth }: Props) {
  const [mode, setMode] = useState<"bar" | "line">("bar");

  const values: Record<RevenueArKey, (number | null)[]> = {
    revenue: data.revenue,
    accounts_receivable: data.accounts_receivable,
  };

  const maxValue = Math.max(0, ...SERIES.flatMap((s) => values[s.key].filter((v): v is number => v != null)));
  const yTicks = computeNiceTicks(maxValue);
  const unit = pickAxisMoneyUnit(yTicks[yTicks.length - 1] || 1);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Revenue vs Accounts Receivable</h3>
        <ModeToggle mode={mode} onChange={setMode} />
      </div>

      <GroupedBarLineChart
        categories={data.years}
        series={SERIES}
        values={values}
        mode={mode}
        yTicks={yTicks}
        yTickFormat={(v) => fmtAxisMoney(v, unit)}
        containerWidth={chartWidth}
      />

      <div className="flex">
        <table className="shrink-0 border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
              <th className="whitespace-nowrap border-b border-zinc-800 py-2 pr-8 font-medium">Metric</th>
            </tr>
          </thead>
          <tbody>
            {SERIES.map((s) => (
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
              {SERIES.map((s) => (
                <tr key={s.key}>
                  {values[s.key].map((v, i) => (
                    <td key={i} className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                      {v != null ? fmtTableMoney(v) : "—"}
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
