"use client";

import { useState } from "react";

import type { SectorHeatmapOut } from "@/lib/api/types";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { fmtPct } from "@/lib/format";
import { cellBackground, columnScale, DEFAULT_HEATMAP_SORT, nextSort, sortHeatmapRows, windowLabel } from "@/lib/sectorHeatmap";

interface Props {
  data: SectorHeatmapOut;
}

/** ETFs as rows, return windows as columns -- a plain CSS grid, no charting
 * library. Ticker labels are deliberately NOT links: /tickers/<ETF> still
 * renders the stock-shaped page. Sorting is client-side, so a re-sort never
 * refetches. */
export function SectorHeatmapGrid({ data }: Props) {
  const [sort, setSort] = useState(DEFAULT_HEATMAP_SORT);
  const rows = sortHeatmapRows(data.rows, sort);
  const scales = Object.fromEntries(data.windows.map((w) => [w, columnScale(data.rows, w)]));

  return (
    <div className="overflow-x-auto">
      <div
        role="table"
        aria-label="Sector ETF total returns"
        className="grid min-w-[44rem] gap-1"
        style={{ gridTemplateColumns: `minmax(11rem, 1.6fr) repeat(${data.windows.length}, minmax(4.5rem, 1fr))` }}
      >
        <div role="row" className="contents">
          <div role="columnheader" className="px-2 py-1 text-xs font-semibold uppercase tracking-widest text-text-tertiary">
            Sector
          </div>
          {data.windows.map((window) => {
            const active = sort.window === window;
            return (
              <div
                key={window}
                role="columnheader"
                aria-sort={active ? (sort.direction === "desc" ? "descending" : "ascending") : "none"}
                className="text-right"
              >
                <button
                  type="button"
                  onClick={() => setSort((current) => nextSort(current, window))}
                  className={`w-full rounded-md px-2 py-1 text-right text-xs font-semibold uppercase tracking-widest transition-colors hover:text-text-primary ${
                    active ? "text-brand" : "text-text-tertiary"
                  }`}
                >
                  {windowLabel(window)}
                  {active && <span aria-hidden> {sort.direction === "desc" ? "↓" : "↑"}</span>}
                </button>
              </div>
            );
          })}
        </div>

        {rows.map((row) => (
          <div key={row.ticker} role="row" className="contents">
            <div role="rowheader" className="flex items-baseline gap-2 px-2 py-2.5">
              <span className="font-mono text-sm font-bold text-text-primary">{row.ticker}</span>
              <span className="truncate text-xs text-text-secondary">{row.name}</span>
            </div>
            {data.windows.map((window) => {
              const cell = row.cells[window];
              const value = cell?.return_pct ?? null;
              return (
                <div
                  key={window}
                  role="cell"
                  data-window={window}
                  title={value != null && cell?.base_date ? `${windowLabel(window)}: from the ${fmtEventDate(cell.base_date)} close` : undefined}
                  style={{ backgroundColor: cellBackground(value, scales[window]) }}
                  className={`rounded-md px-2 py-2.5 text-right font-mono text-sm ${value == null ? "text-text-tertiary" : "text-text-primary"}`}
                >
                  {value == null ? "—" : fmtPct(value, 1)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
