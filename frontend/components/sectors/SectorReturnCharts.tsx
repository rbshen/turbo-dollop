"use client";

import { useState } from "react";

import { SectorBarChart } from "@/components/sectors/SectorBarChart";
import type { SectorHeatmapRowOut } from "@/lib/api/types";
import { computeReturnAxis, computeSharedZero, DEFAULT_CHART_WINDOWS, returnOf } from "@/lib/sectorReturns";

interface Props {
  rows: SectorHeatmapRowOut[];
}

/** The three stacked charts. One container owns the layout (SectorBarChart's SECTOR_CHART_COLUMNS
 * and plot gutters are single constants used by every chart, in this one container, so the label
 * column and plot width are identical by construction) and one shared zero position computed from
 * the three currently selected windows, so the 0% line sits at the same x in all three. Each chart
 * keeps its own scale. A dropdown change recomputes the zero and every chart's scale together.
 * Selections are page state only, never persisted. */
export function SectorReturnCharts({ rows }: Props) {
  const [windows, setWindows] = useState<string[]>([...DEFAULT_CHART_WINDOWS]);
  const values = windows.map((w) => rows.map((row) => returnOf(row, w)));
  const zero = computeSharedZero(values);

  return (
    <div className="space-y-10">
      {windows.map((window, i) => (
        <SectorBarChart
          key={i}
          index={i + 1}
          rows={rows}
          window={window}
          axis={computeReturnAxis(values[i], zero)}
          onWindowChange={(next) => setWindows((current) => current.map((w, j) => (j === i ? next : w)))}
        />
      ))}
    </div>
  );
}
