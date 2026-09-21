"use client";

import { MarketBreadthCharts } from "@/components/breadth/MarketBreadthCharts";
import { MarketBreadthStats } from "@/components/breadth/MarketBreadthStats";
import { PageContainer } from "@/components/layout/PageContainer";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { useMarketBreadth } from "@/lib/hooks/useMarketBreadth";
import { firstLiveIndex } from "@/lib/marketBreadth";

export default function BreadthPage() {
  const { data, error } = useMarketBreadth();
  const loaded = !error && data && data.latest !== null;
  const liveAt = data ? firstLiveIndex(data.series) : -1;

  return (
    <PageContainer className="space-y-6 pb-12 pt-6">
      <div>
        <h1 className="font-heading text-xl font-semibold text-text-primary">Market Breadth</h1>
        {data?.as_of_date && (
          <p className="text-xs text-text-tertiary">
            S&amp;P 500 · As of close {fmtEventDate(data.as_of_date)}
            {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
          </p>
        )}
      </div>

      {error && <p className="text-sm text-negative">Failed to load market breadth.</p>}

      {!error && !data && <p className="text-sm text-text-tertiary animate-pulse">Loading market breadth…</p>}

      {!error && data && data.latest === null && (
        <p className="text-sm text-text-tertiary">No data yet — the nightly job hasn&apos;t run.</p>
      )}

      {loaded && (
        <>
          <MarketBreadthStats latest={data.latest!} />
          <MarketBreadthCharts series={data.series} />
        </>
      )}

      <div className="space-y-1 border-t border-border-subtle pt-4 text-xs text-text-tertiary">
        <p>
          Breadth across the current S&amp;P 500 constituents: the share closing above their own 50- and 200-day simple moving average, and
          the number of stocks at a new 52-week high (intraday) minus those at a new 52-week low. Only stocks with a bar that session are
          counted, and each metric only counts stocks with enough history for its window.
        </p>
        {loaded && liveAt === -1 && (
          <p>
            Every session shown is backfilled from cached price history using today&apos;s constituents, so it is survivorship-biased:
            stocks that joined the index recently are counted in earlier months and stocks that left it are missing.
          </p>
        )}
        {loaded && liveAt > 0 && data.series[liveAt] && (
          <p>
            Sessions before {fmtEventDate(data.series[liveAt].as_of_date)} are backfilled using today&apos;s constituents, so they are
            survivorship-biased; later sessions are recorded live from the index as it stood.
          </p>
        )}
      </div>
    </PageContainer>
  );
}
