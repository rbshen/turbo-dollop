"use client";

import type { SectorHeatmapRowOut } from "@/lib/api/types";
import { Select } from "@/components/ui/Select";
import { fmtPct } from "@/lib/format";
import {
  axisPercent,
  fmtAxisTick,
  RETURN_WINDOW_OPTIONS,
  returnOf,
  sortByReturn,
  windowLabel,
  type ReturnAxis,
} from "@/lib/sectorReturns";

interface Props {
  rows: SectorHeatmapRowOut[];
  window: string;
  /** Fitted by the parent, with the zero position shared across all three charts. */
  axis: ReturnAxis;
  onWindowChange: (window: string) => void;
  /** 1-based position on the page, for the dropdown's accessible name. */
  index: number;
}

// The one layout every chart uses: a fixed label column and a plot that fills the rest, inset
// by a gutter on BOTH sides so an end-of-bar value label (longest negative bar included) never
// clips. Same container width + same constants = same zero x in every chart.
const LABEL_GUTTER = "mx-[4.5rem]";
export const SECTOR_CHART_COLUMNS = "grid grid-cols-[9rem_1fr] sm:grid-cols-[12rem_1fr] items-center gap-x-3";
const COLUMNS = SECTOR_CHART_COLUMNS;
// Same proportions as the Historical Trends bars (MiniBarChart: recharts barCategoryGap 10%, so the
// bar is 90% of its band and the gap 10%; radius 1px, solid fill).
const ROW_HEIGHT = "h-8";
const BAR_INSET = "inset-y-[5%]";

/** One horizontal diverging bar chart: a bar per sector from a center zero line (positive
 * right/green, negative left/red), sorted descending, on an axis fitted to this chart's own
 * values. Plain CSS (percent-positioned divs), no charting library. */
export function SectorBarChart({ rows, window, axis, onWindowChange, index }: Props) {
  const sorted = sortByReturn(rows, window);
  const zero = axisPercent(0, axis);

  return (
    <section aria-label={`${windowLabel(window)} sector returns`} data-window={window} className="space-y-3">
      <Select
        size="short"
        aria-label={`Return window, chart ${index}`}
        value={window}
        onChange={(e) => onWindowChange(e.target.value)}
      >
        {RETURN_WINDOW_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>

      <ol className="m-0 list-none p-0">
        {sorted.map((row) => {
          const value = returnOf(row, window);
          return (
            <li key={row.ticker} className={COLUMNS}>
              <div className="flex items-baseline gap-2 py-1.5">
                <span className="font-mono text-sm font-bold text-text-primary">{row.ticker}</span>
                <span className="truncate text-xs text-text-secondary">{row.name}</span>
              </div>
              <div className={`relative ${ROW_HEIGHT}`}>
                <div className={`relative h-full ${LABEL_GUTTER}`}>
                  <div
                    data-testid="zero-line"
                    className="absolute inset-y-0 w-px bg-text-tertiary"
                    style={{ left: `${zero}%` }}
                  />
                  {value == null ? (
                    <span
                      className="absolute top-1/2 ml-2 -translate-y-1/2 font-mono text-xs text-text-tertiary"
                      style={{ left: `${zero}%` }}
                    >
                      n/a
                    </span>
                  ) : (
                    <Bar value={value} label={`${row.name} ${fmtPct(value, 2)}`} axis={axis} zero={zero} />
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <div className={COLUMNS} aria-hidden="true" data-testid="axis">
        <div />
        <div className="relative h-5">
          <div className={`relative h-full ${LABEL_GUTTER}`}>
            {axis.ticks.map((tick) => (
              <span
                key={tick}
                data-tick={tick}
                className="absolute top-0 -translate-x-1/2 font-mono text-xs text-text-secondary"
                style={{ left: `${axisPercent(tick, axis)}%` }}
              >
                {fmtAxisTick(tick, axis)}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Bar({ value, label, axis, zero }: { value: number; label: string; axis: ReturnAxis; zero: number }) {
  const end = axisPercent(value, axis);
  const positive = value >= 0;
  const left = Math.min(zero, end);
  const width = Math.abs(end - zero);
  return (
    <>
      <div
        role="img"
        aria-label={label}
        data-direction={positive ? "positive" : "negative"}
        className={`absolute ${BAR_INSET} rounded-[1px] ${positive ? "bg-positive" : "bg-negative"}`}
        style={{ left: `${left}%`, width: `${width}%` }}
      />
      <span
        className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap font-mono text-xs tabular-nums text-text-primary"
        style={positive ? { left: `${end}%`, marginLeft: "0.375rem" } : { right: `${100 - end}%`, marginRight: "0.375rem" }}
      >
        {fmtPct(value, 2)}
      </span>
    </>
  );
}
