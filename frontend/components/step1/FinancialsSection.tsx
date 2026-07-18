"use client";

import { useState } from "react";

import { GroupedBarLineChart, type ChartSeries } from "@/components/charts/GroupedBarLineChart";
import { ModeToggle } from "@/components/charts/ModeToggle";
import type { Step1Out } from "@/lib/api/types";
import { computeNiceTicks } from "@/lib/charts";
import { fmtAxisMoney, fmtTableMoney, pickAxisMoneyUnit } from "@/lib/format";

type FinancialMetricKey = "cfo" | "net_income" | "operating_income" | "revenue";

const ALL_SERIES: (ChartSeries & { key: FinancialMetricKey })[] = [
  { key: "cfo", label: "Net operating cash flow", color: "#eb6834" },
  { key: "net_income", label: "Net income", color: "#2a78d6" },
  { key: "operating_income", label: "Operating income", color: "#008300" },
  { key: "revenue", label: "Revenue", color: "#eda100" },
];

interface Props {
  data: Step1Out;
  chartWidth: number;
}

export function FinancialsSection({ data, chartWidth }: Props) {
  const [mode, setMode] = useState<"bar" | "line">("bar");

  const series = ALL_SERIES.filter((s) => s.key !== "cfo" || data.cfo !== null);
  const values: Record<FinancialMetricKey, (number | null)[]> = {
    revenue: data.revenue,
    net_income: data.net_income,
    operating_income: data.operating_income,
    cfo: data.cfo ?? [],
  };

  const maxValue = Math.max(0, ...series.flatMap((s) => values[s.key].filter((v): v is number => v != null)));
  const yTicks = computeNiceTicks(maxValue);
  const unit = pickAxisMoneyUnit(yTicks[yTicks.length - 1] || 1);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Financials trend</h3>
        <ModeToggle mode={mode} onChange={setMode} />
      </div>

      <GroupedBarLineChart
        categories={data.years}
        series={series}
        values={values}
        mode={mode}
        yTicks={yTicks}
        yTickFormat={(v) => fmtAxisMoney(v, unit)}
        containerWidth={chartWidth}
      />

      {data.cfo === null && (
        <p className="text-xs text-zinc-500">Cash flow from operations not applicable — {data.cfo_exempt_reason}.</p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
              <th className="sticky left-0 z-10 border-b border-zinc-800 bg-zinc-900 py-2 pr-8 font-medium">Metric</th>
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
                <td className="sticky left-0 z-10 border-b border-zinc-900 bg-zinc-900 py-2 pr-8 text-zinc-400">
                  <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ backgroundColor: s.color }} />
                  {s.label}
                </td>
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
  );
}
