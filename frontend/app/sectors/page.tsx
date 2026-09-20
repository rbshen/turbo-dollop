"use client";

import { PageContainer } from "@/components/layout/PageContainer";
import { SectorHeatmapGrid } from "@/components/sectors/SectorHeatmapGrid";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { useSectorHeatmap } from "@/lib/hooks/useSectorHeatmap";

export default function SectorsPage() {
  const { data, error } = useSectorHeatmap();

  return (
    <PageContainer className="space-y-6 pb-12 pt-6">
      <div>
        <h1 className="font-heading text-xl font-semibold text-text-primary">Sector Heatmap</h1>
        {data?.as_of_date && (
          <p className="text-xs text-text-tertiary">
            As of close {fmtEventDate(data.as_of_date)}
            {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
          </p>
        )}
      </div>

      {error && <p className="text-sm text-negative">Failed to load the sector heatmap.</p>}

      {!error && !data && <p className="text-sm text-text-tertiary animate-pulse">Loading sector heatmap…</p>}

      {!error && data && data.as_of_date === null && (
        <p className="text-sm text-text-tertiary">No data yet — the nightly job hasn&apos;t run.</p>
      )}

      {!error && data && data.as_of_date !== null && <SectorHeatmapGrid data={data} />}

      <div className="space-y-1 border-t border-border-subtle pt-4 text-xs text-text-tertiary">
        <p>
          Trailing total return (price change plus reinvested distributions) of the 11 SPDR sector ETFs over calendar-day windows; YTD is
          measured from the prior year&apos;s final close. Click a column header to sort.
        </p>
        <p>Cell color is scaled within each column — the strongest tint is that window&apos;s largest move, so tints aren&apos;t comparable across columns.</p>
      </div>
    </PageContainer>
  );
}
