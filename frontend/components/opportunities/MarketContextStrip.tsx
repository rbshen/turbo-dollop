import type { ReactNode } from "react";

import type { OpportunityRunSummary } from "@/lib/api/types";
import { pnlClass } from "@/lib/format";
import { fmtBreadthPct, fmtSignedCount } from "@/lib/marketBreadth";

interface Props {
  market: OpportunityRunSummary["market"] | undefined;
  asOf: string;
}

function Stat({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-xs text-text-tertiary">{label}</span>
      <span className="font-mono text-sm tabular-nums text-text-primary">{value}</span>
      {note && <span className="text-xs text-text-tertiary">{note}</span>}
    </div>
  );
}

// The market the run was frozen in: S&P 500 breadth (the latest stored MarketBreadthSnapshot on or before the as-of date) and how many
// of the 11 sector ETFs are in Advance. A hairline strip, not a card.
export function MarketContextStrip({ market, asOf }: Props) {
  const breadth = market?.breadth ?? null;
  const sectors = market?.sector_etfs ? Object.values(market.sector_etfs) : [];
  const stale = breadth != null && breadth.as_of_date !== asOf;
  return (
    <section aria-label="Market context" className="grid grid-cols-2 gap-x-8 gap-y-3 border-y border-border-subtle py-4 sm:grid-cols-4">
      <Stat label="Above 50-day SMA" value={fmtBreadthPct(breadth?.pct_above_sma50 ?? null)} note={stale ? `as of ${breadth?.as_of_date}` : "S&P 500"} />
      <Stat label="Above 200-day SMA" value={fmtBreadthPct(breadth?.pct_above_sma200 ?? null)} note={stale ? `as of ${breadth?.as_of_date}` : "S&P 500"} />
      <Stat
        label="Net new 52-week highs"
        value={breadth ? <span className={pnlClass(breadth.net_new_highs)}>{fmtSignedCount(breadth.net_new_highs)}</span> : "—"}
        note="S&P 500"
      />
      <Stat
        label="Sectors in Advance"
        value={market ? `${market.sectors_in_advance} of ${sectors.length || 11}` : "—"}
        note="SPDR sector ETFs, Stage 2"
      />
    </section>
  );
}
