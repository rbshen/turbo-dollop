"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
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
}

export function FinancialsSection({ data }: Props) {
  const [mode, setMode] = useState<"bar" | "line">("bar");

  const series = ALL_SERIES.filter((s) => s.key !== "cfo" || data.cfo !== null).map((s) =>
    s.key === "revenue" ? { ...s, label: data.revenue_label } : s
  );
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

      <RechartsGroupedChart
        categories={data.years}
        series={series}
        values={values}
        mode={mode}
        yTicks={yTicks}
        yTickFormat={(v) => fmtAxisMoney(v, unit)}
      />

      {data.cfo === null && (
        <p className="text-xs text-zinc-500">
          Cash flow from operations and free cash flow not applicable — {data.cfo_exempt_reason}.
        </p>
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
