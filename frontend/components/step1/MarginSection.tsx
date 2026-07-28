"use client";

import { useState } from "react";

import { ModeToggle } from "@/components/charts/ModeToggle";
import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
import { SeriesTrendTable } from "@/components/shared/SeriesTrendTable";
import type { Step1Out } from "@/lib/api/types";
import { fmtPlainPct } from "@/lib/format";

type MarginMetricKey = "gross_margin" | "net_margin";

const MARGIN_SERIES: (ChartSeries & { key: MarginMetricKey })[] = [
  { key: "gross_margin", label: "Gross Profit Margin", color: "#eb6834" },
  { key: "net_margin", label: "Net Profit Margin", color: "#2a78d6" },
];

const MARGIN_TICKS = [0, 25, 50, 75, 100];

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

      <SeriesTrendTable
        labelHeader="Metric"
        years={data.years}
        series={MARGIN_SERIES}
        values={values}
        formatValue={(v) => fmtPlainPct(v, 2)}
        showAverage
      />
    </div>
  );
}
