"use client";

import { BreadthSectorTabs } from "@/components/breadth/BreadthSectorTabs";
import { MarketBreadthCharts } from "@/components/breadth/MarketBreadthCharts";
import { MarketBreadthStats } from "@/components/breadth/MarketBreadthStats";
import { PageContainer } from "@/components/layout/PageContainer";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { useMarketBreadth } from "@/lib/hooks/useMarketBreadth";
import { firstLiveIndex, isKnownSectorTicker, sectorDisplayName, sectorUniverse } from "@/lib/marketBreadth";

interface Props {
  // An uppercased URL segment (e.g. "XLK") -- may not be one of the 11 known SPDR tickers.
  sector: string;
}

// Deliberately mirrors app/breadth/page.tsx's body structurally rather than sharing a component with it
// (same precedent as WarrenSignalCard "structurally mirroring" BbRsiEntrySignalCard elsewhere in this
// app) -- so the existing, already-tested /breadth page and its test file stay byte-identical and
// zero-risk. Reuses MarketBreadthStats/MarketBreadthCharts/firstLiveIndex as-is: they're already fully
// generic over MarketBreadthPointOut and never reference "S&P 500" internally.
export function BreadthSectorView({ sector }: Props) {
  const known = isKnownSectorTicker(sector);
  const name = sectorDisplayName(sector);
  // known=false skips the fetch entirely (useMarketBreadth's null-universe convention) -- an unrecognized
  // sector never hits the API with a nonsense universe string.
  const { data, error } = useMarketBreadth(known ? sectorUniverse(sector) : null);
  const loaded = known && !error && data && data.latest !== null;
  const liveAt = data ? firstLiveIndex(data.series) : -1;

  return (
    <PageContainer className="space-y-6 pb-12 pt-6">
      <div>
        <h1 className="font-heading text-xl font-semibold text-text-primary">Market Breadth</h1>
        {known ? (
          data?.as_of_date && (
            <p className="text-xs text-text-tertiary">
              {name} ({sector}) · As of close {fmtEventDate(data.as_of_date)}
              {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
            </p>
          )
        ) : (
          <p className="text-xs text-text-tertiary">Unknown sector &quot;{sector}&quot;</p>
        )}
      </div>

      <BreadthSectorTabs active={known ? sector : ""} />

      {!known && (
        <p className="text-sm text-text-tertiary">
          &quot;{sector}&quot; isn&apos;t one of the 11 SPDR sector ETFs this page tracks — pick one from the tabs above.
        </p>
      )}

      {known && error && <p className="text-sm text-negative">Failed to load {name} sector breadth.</p>}

      {known && !error && !data && <p className="text-sm text-text-tertiary animate-pulse">Loading {name} sector breadth…</p>}

      {known && !error && data && data.latest === null && (
        <p className="text-sm text-text-tertiary">
          No data yet — the nightly job hasn&apos;t run for this sector yet, or it hasn&apos;t cleared the coverage gate.
        </p>
      )}

      {loaded && (
        <>
          <MarketBreadthStats latest={data.latest!} />
          <MarketBreadthCharts series={data.series} />
        </>
      )}

      {known && (
        <div className="space-y-1 border-t border-border-subtle pt-4 text-xs text-text-tertiary">
          <p>
            Breadth across the current constituents of the {name} sector ({sector}): the share closing above their own 20-, 50- and
            200-day simple moving average, and the number of stocks at a new 52-week high (intraday) minus those at a new 52-week low.
            Only stocks with a bar that session are counted, and each metric only counts stocks with enough history for its window. A
            sector&apos;s coverage gate is more permissive than the S&amp;P 500 overall gate — it passes on either 97% coverage or at
            most one missing stock, whichever lets more sessions through.
          </p>
          {loaded && liveAt === -1 && (
            <p>
              Every session shown is backfilled from cached price history using today&apos;s constituents, so it is survivorship-biased:
              stocks that joined the sector recently are counted in earlier months and stocks that left it are missing.
            </p>
          )}
          {loaded && liveAt > 0 && data.series[liveAt] && (
            <p>
              Sessions before {fmtEventDate(data.series[liveAt].as_of_date)} are backfilled using today&apos;s constituents, so they are
              survivorship-biased; later sessions are recorded live from the sector as it stood.
            </p>
          )}
        </div>
      )}
    </PageContainer>
  );
}
