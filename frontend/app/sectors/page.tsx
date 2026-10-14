"use client";

import { useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { SectorBarChart } from "@/components/sectors/SectorBarChart";
import { PageHeader } from "@/components/ui/page-header";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { useSectorReturns } from "@/lib/hooks/useSectorReturns";
import { DEFAULT_CHART_WINDOWS } from "@/lib/sectorReturns";

export default function SectorsPage() {
  const { data, error } = useSectorReturns();
  // One window per chart, independent; deliberately not persisted (a reload returns to the defaults).
  const [windows, setWindows] = useState<string[]>([...DEFAULT_CHART_WINDOWS]);

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader
        title="Sectors"
        subtitle={
          data?.as_of_date && (
            <>
              As of close {fmtEventDate(data.as_of_date)}
              {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
            </>
          )
        }
      />

      {error && <p className="text-sm text-negative">Failed to load the sector returns.</p>}

      {!error && !data && <p className="text-sm text-text-tertiary animate-pulse">Loading sector returns…</p>}

      {!error && data && data.as_of_date === null && (
        <p className="text-sm text-text-tertiary">No data yet — the nightly job hasn&apos;t run.</p>
      )}

      {!error && data && data.as_of_date !== null && (
        <div className="space-y-10">
          {windows.map((window, i) => (
            <SectorBarChart
              key={i}
              index={i + 1}
              rows={data.rows}
              window={window}
              onWindowChange={(next) => setWindows((current) => current.map((w, j) => (j === i ? next : w)))}
            />
          ))}
        </div>
      )}

      <div className="border-t border-border-subtle pt-4 text-xs text-text-tertiary">
        <p>
          Returns are split-adjusted price change of the 11 SPDR sector ETFs, with no dividends included.
          {data?.as_of_date && <> Data as of the close on {fmtEventDate(data.as_of_date)}.</>}
        </p>
      </div>
    </PageContainer>
  );
}
