"use client";

import { useState } from "react";

import { PeHistoryChart } from "@/components/ticker/PeHistoryChart";
import { Switch } from "@/components/ui/switch";
import type { PeHistoryOut } from "@/lib/api/types";
import { usePeHistory } from "@/lib/hooks/usePeHistory";
import { peHeadline } from "@/lib/peHistory";

const STOCK_NOTES: Record<Exclude<PeHistoryOut["stock_status"], "ok">, (ticker: string) => string> = {
  adr: (t) => `No stock P/E line: ${t} reports in a different currency than it trades in, so price over EPS would need an FX conversion.`,
  no_eps: () => "No stock P/E line: trailing diluted EPS is zero or negative for the whole last year, or too few quarters are cached.",
  no_prices: (t) => `No stock P/E line: no cached daily prices for ${t}.`,
};

/** The P/E history card on the Ratios tab: fetches, then hands the payload to the panel. */
export function PeHistoryCard({ ticker }: { ticker: string }) {
  const { data, error } = usePeHistory(ticker);
  return (
    <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
      {error ? (
        <p className="text-sm text-negative">Couldn&apos;t load the P/E history — {error.message}</p>
      ) : !data ? (
        <p className="text-sm text-text-tertiary animate-pulse">Loading P/E history…</p>
      ) : (
        <PeHistoryPanel data={data} />
      )}
    </div>
  );
}

export function PeHistoryPanel({ data }: { data: PeHistoryOut }) {
  // null = the viewer has not touched the switch: the overlays start off, except when there is no stock line (then
  // the chart would be empty, so they start on).
  const [sectorPref, setSectorPref] = useState<boolean | null>(null);
  const [industryPref, setIndustryPref] = useState<boolean | null>(null);

  const title = <h2 className="font-heading text-sm font-semibold text-text-primary">P/E history</h2>;
  if (data.status !== "ok") {
    return (
      <>
        {title}
        <p className="text-sm text-text-tertiary">{data.note}</p>
      </>
    );
  }

  const stockOk = data.stock_status === "ok";
  const showSwitchSector = data.sector_available;
  const showSwitchIndustry = data.industry_available;
  const sectorOn = showSwitchSector && (sectorPref ?? !stockOk);
  const industryOn = showSwitchIndustry && (industryPref ?? (!stockOk && !showSwitchSector));
  const hasChart = (stockOk || sectorOn || industryOn) && data.points.length > 0;
  const nothingToShow = !stockOk && !showSwitchSector && !showSwitchIndustry;

  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        {title}
        {!nothingToShow && (
          <span className="font-mono text-xs tabular-nums text-text-secondary">
            {peHeadline(data.latest_stock, data.latest_sector, data.industry_fallback ? null : data.latest_industry)}
          </span>
        )}
      </div>

      {(showSwitchSector || showSwitchIndustry) && (
        <div className="flex min-h-[25px] flex-wrap items-center justify-end gap-x-4 gap-y-1">
          {showSwitchSector && <Switch label="Overlay sector PE" checked={sectorOn} onChange={(e) => setSectorPref(e.target.checked)} />}
          {showSwitchIndustry && <Switch label="Overlay industry PE" checked={industryOn} onChange={(e) => setIndustryPref(e.target.checked)} />}
        </div>
      )}

      {data.industry_fallback && (
        <p className="text-xs text-text-tertiary">
          No industry series for {data.industry ?? "this industry"} on {data.exchange}; the sector line is the nearest overlay.
        </p>
      )}
      {data.stock_status !== "ok" && <p className="text-sm text-text-tertiary">{STOCK_NOTES[data.stock_status](data.ticker)}</p>}
      {nothingToShow && <p className="text-sm text-text-tertiary">No sector or industry P/E series is stored for this ticker either.</p>}

      {hasChart && <PeHistoryChart data={data} showStock={stockOk} showSector={sectorOn} showIndustry={industryOn} />}

      {!nothingToShow && (
        <p className="text-xs text-text-tertiary">
          Last 1 year. Stock P/E is the daily close over the sum of the last four quarterly diluted EPS, so it can differ from the header P/E.
          Sector and industry lines are the {data.label} for {data.exchange}-listed companies; the bases differ, so read the trends, not exact levels.
        </p>
      )}
    </>
  );
}
