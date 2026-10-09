"use client";

import { PageContainer } from "@/components/layout/PageContainer";
import { SectorHeatmapGrid } from "@/components/sectors/SectorHeatmapGrid";
import { PageHeader } from "@/components/ui/page-header";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { useSectorHeatmap } from "@/lib/hooks/useSectorHeatmap";

export default function SectorsPage() {
  const { data, error } = useSectorHeatmap();

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader
        title="Sector Heatmap"
        subtitle={
          data?.as_of_date && (
            <>
              As of close {fmtEventDate(data.as_of_date)}
              {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
            </>
          )
        }
      />

      {error && <p className="text-sm text-negative">Failed to load the sector heatmap.</p>}

      {!error && !data && <p className="text-sm text-text-tertiary animate-pulse">Loading sector heatmap…</p>}

      {!error && data && data.as_of_date === null && (
        <p className="text-sm text-text-tertiary">No data yet — the nightly job hasn&apos;t run.</p>
      )}

      {!error && data && data.as_of_date !== null && <SectorHeatmapGrid data={data} />}

      <div className="space-y-1 border-t border-border-subtle pt-4 text-xs text-text-tertiary">
        <p>
          Trailing price change (excludes dividends) of the 11 SPDR sector ETFs, rolling back from the last completed
          close: 1D = the prior close, 1W = 7 days, 1M to 9M = the same date N months earlier, 1Y = the same date one
          year earlier; a weekend or holiday baseline uses the prior close. YTD is measured from the prior
          year&apos;s final close. Click a column header to sort.
        </p>
        <p>Cell color is scaled within each column — the strongest tint is that window&apos;s largest move, so tints aren&apos;t comparable across columns.</p>
      </div>
    </PageContainer>
  );
}
