"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
import { SeriesTrendTable } from "@/components/shared/SeriesTrendTable";
import type { Step4Out } from "@/lib/api/types";
import { computeNiceTicksRange } from "@/lib/charts";
import { fmtPlainPct } from "@/lib/format";

type RoeRoicKey = "roe" | "roic";

const ALL_SERIES: (ChartSeries & { key: RoeRoicKey })[] = [
  { key: "roe", label: "Return on Equity", color: "#eb6834" },
  { key: "roic", label: "Return on Invested Capital", color: "#2a78d6" },
];

interface Props {
  data: Step4Out;
}

export function RoeRoicSection({ data }: Props) {
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

      <RechartsGroupedChart
        categories={data.years}
        series={series}
        values={values}
        mode={mode}
        yTicks={yTicks}
        yTickFormat={(v) => `${v}%`}
      />

      {data.roic === null && (
        <p className="text-xs text-zinc-500">ROIC not applicable — {data.roic_exempt_reason}</p>
      )}

      <SeriesTrendTable
        labelHeader="Metric"
        years={data.years}
        series={series}
        values={values}
        formatValue={(v) => fmtPlainPct(v, 2)}
      />
    </div>
  );
}
