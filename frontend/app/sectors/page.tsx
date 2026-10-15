"use client";

import { PageContainer } from "@/components/layout/PageContainer";
import { SectorReturnCharts } from "@/components/sectors/SectorReturnCharts";
import { PageHeader } from "@/components/ui/page-header";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { useSectorReturns } from "@/lib/hooks/useSectorReturns";

export default function SectorsPage() {
  const { data, error } = useSectorReturns();

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

      {!error && data && data.as_of_date !== null && <SectorReturnCharts rows={data.rows} />}

      <div className="border-t border-border-subtle pt-4 text-xs text-text-tertiary">
        <p>
          Returns are split-adjusted price change of the 11 SPDR sector ETFs, with no dividends included.
          {data?.as_of_date && <> Data as of the close on {fmtEventDate(data.as_of_date)}.</>}
        </p>
      </div>
    </PageContainer>
  );
}
