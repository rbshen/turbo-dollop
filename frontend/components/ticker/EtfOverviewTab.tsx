"use client";

import { DefinitionRow, Section } from "@/components/ui/section";
import type { EtfOverviewOut } from "@/lib/api/types";
import {
  SECTOR_WEIGHTS_NOT_SHOWN_NOTE,
  fundDataAsOf,
  fundFacts,
  tradingDataCaption,
  tradingDataRows,
  unavailableMessage,
} from "@/lib/etfOverview";
import { useEtfOverview } from "@/lib/hooks/useEtfOverview";

interface Props {
  ticker: string;
}

/** Sector weights as horizontal bars, one series colour (docs/design-system-charts.md: a bar that is one
 * series is `series-1`). Bar length is relative to the largest weight so a 34% leader and a 2% tail both
 * read; the exact figure is always printed. */
function SectorWeightBars({ weights }: { weights: EtfOverviewOut["sector_weights"] }) {
  const max = Math.max(...weights.map((w) => w.weight));
  return (
    <ul className="space-y-3">
      {weights.map((w) => (
        <li key={w.sector} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-3 text-sm">
          <span className="truncate text-text-secondary" title={w.sector}>
            {w.sector}
          </span>
          <span className="h-2 rounded-sm bg-surface-2" aria-hidden="true">
            <span className="block h-2 rounded-sm bg-series-1" style={{ width: `${(w.weight / max) * 100}%` }} />
          </span>
          <span className="text-right font-mono tabular-nums text-text-primary">{w.weight.toFixed(1)}%</span>
        </li>
      ))}
    </ul>
  );
}

/** The presentational Overview: all data arrives as props, so tests (and nothing else) can render every state. */
export function EtfOverviewView({ overview }: { overview: EtfOverviewOut }) {
  if (overview.status !== "ok") {
    return (
      <p className="py-6 text-sm text-text-tertiary" data-testid="etf-overview-unavailable">
        {unavailableMessage(overview)}
      </p>
    );
  }

  const facts = fundFacts(overview);
  const trading = tradingDataRows(overview.trading_data);
  const tradingCaption = tradingDataCaption(overview.trading_data, trading);
  const asOf = fundDataAsOf(overview);

  return (
    <div className="grid grid-cols-1 gap-x-16 gap-y-10 py-6 lg:grid-cols-12">
      <div className="space-y-8 lg:col-span-7">
        {facts.length > 0 && (
          <Section title="Fund facts">
            <div>
              {facts.map((f) => (
                <DefinitionRow key={f.label} label={f.label} value={f.value} />
              ))}
            </div>
          </Section>
        )}
        {trading.length > 0 && (
          <Section title="Trading data">
            <div>
              {trading.map((r) => (
                <DefinitionRow key={r.label} label={r.label} value={r.value} tone={r.tone} />
              ))}
            </div>
            {tradingCaption && <p className="mt-3 text-xs text-text-tertiary">{tradingCaption}</p>}
          </Section>
        )}
        {overview.description && (
          <Section title="About this fund">
            <p className="text-sm leading-relaxed text-text-body">{overview.description}</p>
          </Section>
        )}
      </div>

      <div className="lg:col-span-5">
        <Section title="Sector weights">
          {overview.sector_weights.length > 0 ? (
            <SectorWeightBars weights={overview.sector_weights} />
          ) : (
            <p className="text-xs text-text-tertiary" data-testid="sector-weights-note">
              {SECTOR_WEIGHTS_NOT_SHOWN_NOTE}
            </p>
          )}
        </Section>
        {asOf && <p className="mt-6 text-xs text-text-tertiary">Fund data as of {asOf}</p>}
      </div>
    </div>
  );
}

export function EtfOverviewTab({ ticker }: Props) {
  const { data, error, isLoading } = useEtfOverview(ticker);

  if (error) {
    return <p className="py-6 text-sm text-negative">Couldn&apos;t load fund details — {error.message}</p>;
  }
  if (isLoading || !data) {
    return <p className="py-6 text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }
  return <EtfOverviewView overview={data} />;
}
