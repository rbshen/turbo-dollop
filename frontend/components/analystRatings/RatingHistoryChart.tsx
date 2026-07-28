"use client";

import { useState } from "react";

import { type ChartSeries, RechartsGroupedChart } from "@/components/charts/RechartsGroupedChart";
import { SegmentedControl } from "@/components/shared/SegmentedControl";
import type { RatingHistoryPoint } from "@/lib/api/types";
import { computeNiceTicks } from "@/lib/charts";
import { fmtAxisMoney, pickAxisMoneyUnit } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
}

type ViewMode = "distribution" | "avgRating" | "avgTarget";

// Buy/Hold/Sell reads as a status (good/neutral/bad), not an arbitrary
// series identity -- these are the dataviz skill's fixed status-palette
// steps (good/warning/critical), validated for dark-surface contrast.
const DISTRIBUTION_SERIES: ChartSeries[] = [
  { key: "buy_pct", label: "Buy %", color: "#0ca30c" },
  { key: "hold_pct", label: "Hold %", color: "#fab219" },
  { key: "sell_pct", label: "Sell %", color: "#d03b3b" },
];

// Neutral (non-status) hues, same pair MarginSection already uses for a
// two-series numeric comparison -- these are magnitudes, not a status.
const AVG_RATING_SERIES: ChartSeries[] = [{ key: "avg_rating", label: "Avg Rating (1-5)", color: "#2a78d6" }];
const AVG_TARGET_SERIES: ChartSeries[] = [{ key: "avg_price_target", label: "Avg Price Target", color: "#eb6834" }];

const VIEW_TABS: { key: ViewMode; label: string }[] = [
  { key: "distribution", label: "Rating Distribution" },
  { key: "avgRating", label: "Avg Rating" },
  { key: "avgTarget", label: "Avg Price Target" },
];

export function RatingHistoryChart({ history }: Props) {
  const [mode, setMode] = useState<ViewMode>("distribution");

  if (history.length === 0) {
    return <p className="text-sm text-zinc-600">No rating history available yet.</p>;
  }

  const categories = history.map((point) => point.date);
  const hasPriceTargetHistory = history.some((point) => point.avg_price_target != null);
  const maxTarget = Math.max(0, ...history.map((point) => point.avg_price_target ?? 0));
  const targetUnit = pickAxisMoneyUnit(maxTarget);

  const values: Record<string, (number | null)[]> = {
    buy_pct: history.map((point) => point.buy_pct),
    hold_pct: history.map((point) => point.hold_pct),
    sell_pct: history.map((point) => point.sell_pct),
    avg_rating: history.map((point) => point.avg_rating),
    avg_price_target: history.map((point) => point.avg_price_target),
  };

  const series = mode === "distribution" ? DISTRIBUTION_SERIES : mode === "avgRating" ? AVG_RATING_SERIES : AVG_TARGET_SERIES;
  const yTicks =
    mode === "distribution" ? [0, 25, 50, 75, 100] : mode === "avgRating" ? [1, 2, 3, 4, 5] : computeNiceTicks(maxTarget);
  const yTickFormat =
    mode === "distribution"
      ? (v: number) => `${v}%`
      : mode === "avgRating"
        ? (v: number) => v.toFixed(1)
        : (v: number) => fmtAxisMoney(v, targetUnit);

  return (
    <div className="space-y-3">
      <SegmentedControl
        value={mode}
        onChange={setMode}
        options={VIEW_TABS.map(({ key, label }) => ({ value: key, label }))}
      />

      {mode === "avgTarget" && !hasPriceTargetHistory ? (
        <p className="text-sm text-zinc-600">
          Price target history hasn&apos;t accumulated yet — this line fills in as the monthly snapshot job runs.
        </p>
      ) : (
        <RechartsGroupedChart
          categories={categories}
          series={series}
          values={values}
          mode="line"
          yTicks={yTicks}
          yTickFormat={yTickFormat}
          xAxisInterval="preserveStartEnd"
        />
      )}
    </div>
  );
}
