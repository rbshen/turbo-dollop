"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
import { SeriesTrendTable } from "@/components/shared/SeriesTrendTable";
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
}

export function RevenueArSection({ data }: Props) {
  const [mode, setMode] = useState<"bar" | "line">("bar");

  if (data.revenue_vs_ar_exempt_reason) {
    return (
      <div className="space-y-3">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Revenue vs Accounts Receivable</h3>
        <p className="text-sm text-zinc-500">Not applicable — {data.revenue_vs_ar_exempt_reason}</p>
      </div>
    );
  }

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

      <RechartsGroupedChart
        categories={data.years}
        series={SERIES}
        values={values}
        mode={mode}
        yTicks={yTicks}
        yTickFormat={(v) => fmtAxisMoney(v, unit)}
      />

      <SeriesTrendTable labelHeader="Metric" years={data.years} series={SERIES} values={values} formatValue={fmtTableMoney} />
    </div>
  );
}
