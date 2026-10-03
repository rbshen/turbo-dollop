"use client";

import type { ReactNode } from "react";

import { EtfWatchlistButton } from "@/components/ticker/EtfWatchlistButton";
import { PriceChange } from "@/components/ticker/PriceChange";
import { useUniverseControl } from "@/components/ticker/UniverseControl";
import type { EtfOverviewOut, TickerSummaryOut } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";
import { useEtfOverview } from "@/lib/hooks/useEtfOverview";

type HeaderData = Pick<
  TickerSummaryOut,
  "ticker" | "company_name" | "exchange" | "price" | "change" | "change_percent" | "quote_currency"
>;

interface ViewProps {
  data: HeaderData;
  /** From /etf/info; undefined while loading or when unavailable -- the caption then drops the asset class. */
  assetClass: EtfOverviewOut["asset_class"] | undefined;
  actions: ReactNode;
  /** A small line under the action cluster (the universe Add/Remove note or error); never inside the row. */
  actionsNote?: ReactNode;
}

/** ETF header: fund name, ticker, price and daily change, a caption ("Exchange-traded fund" + asset class)
 * and the action slot (the universe control, then the watchlist button). No Assessment/Moat/Valuation/Speculative
 * growth/5Y-vs-SPY pills and no next-earnings line (a fund has none of them), and no sector/industry eyebrow (FMP reports every ETF as
 * "Financial Services · Asset Management", which is misleading). */
export function EtfHeaderView({ data, assetClass, actions, actionsNote }: ViewProps) {
  return (
    <div className="space-y-3 pt-4">
      {/* Never wraps: the title block shrinks (min-w-0), the action cluster is shrink-0 and flex-nowrap. */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="font-heading text-2xl font-medium text-text-primary">{data.company_name ?? data.ticker}</h1>
            <span className="font-mono text-sm text-text-secondary">
              {data.ticker}
              {data.exchange && <> · {data.exchange}</>}
            </span>
          </div>
          <p className="mt-1 text-xs text-text-tertiary">
            Exchange-traded fund{assetClass ? ` · ${assetClass}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <div className="flex flex-nowrap items-center gap-2 whitespace-nowrap">{actions}</div>
          {actionsNote}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 pb-1">
        {data.price != null && (
          <span className="font-mono text-xl font-bold tabular-nums text-text-primary">
            {fmtMoney(data.price, data.quote_currency)}
          </span>
        )}
        <PriceChange change={data.change} changePercent={data.change_percent} currency={data.quote_currency} />
      </div>
    </div>
  );
}

export function EtfHeader({ data }: { data: TickerSummaryOut }) {
  const { data: overview } = useEtfOverview(data.ticker);
  const universe = useUniverseControl(data.ticker);
  return (
    <EtfHeaderView
      data={data}
      assetClass={overview?.status === "ok" ? overview.asset_class : undefined}
      actions={
        <>
          {universe.control}
          <EtfWatchlistButton ticker={data.ticker} />
        </>
      }
      actionsNote={universe.note}
    />
  );
}
