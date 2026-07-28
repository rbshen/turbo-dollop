"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
import { SeriesTrendTable } from "@/components/shared/SeriesTrendTable";
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

      <SeriesTrendTable labelHeader="Metric" years={data.years} series={series} values={values} formatValue={fmtTableMoney} />
    </div>
  );
}
