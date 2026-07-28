"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
import { SeriesTrendTable } from "@/components/shared/SeriesTrendTable";
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

      <SeriesTrendTable
        labelHeader="Metric"
        years={data.years}
        series={SERIES}
        values={values}
        formatValue={(v) => `${v.toFixed(1)}d`}
      />
    </div>
  );
}
