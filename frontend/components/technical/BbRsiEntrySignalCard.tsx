import { ChecklistCard, type ChecklistItem } from "@/components/technical/ChecklistCard";
import type { TechnicalEntrySignalOut } from "@/lib/api/types";

interface Props {
  data: TechnicalEntrySignalOut | null;
}

const DISCLAIMER =
  "Bollinger Band %B + RSI oversold check on 2-hour candles, ported from a reference trading bot's entry condition. Display-only -- Fathom does not execute trades. Informational only, not a trading signal.";

const UNAVAILABLE_MESSAGE =
  'No BB+RSI entry signal tracked for this ticker -- this check only runs nightly for tickers in the "Watchlist" watchlist.';

const SOURCE_LABEL: Record<string, string> = {
  yahoo: "Yahoo Finance",
  fmp: "Financial Modeling Prep",
};

function fmtAsOf(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function BbRsiEntrySignalCard({ data }: Props) {
  if (!data) {
    return (
      <ChecklistCard
        title="BB + RSI Entry Signal (2h)"
        statusLabel="Not tracked"
        statusToneClass="border-border-card bg-surface-2 text-text-tertiary"
        blurb="Bollinger Band %B in the bottom 5% of the band, combined with an oversold prior-bar RSI, on 2-hour session candles."
        items={[]}
        disclaimer={UNAVAILABLE_MESSAGE}
      />
    );
  }

  const items: ChecklistItem[] = [
    {
      key: "pct-b",
      label: "Bollinger Band %B",
      statusText: data.pct_b != null ? data.pct_b.toFixed(4) : "—",
      toneClass: data.pct_b != null && data.pct_b <= 0.05 ? "text-positive" : "text-text-tertiary",
    },
    {
      key: "rsi",
      label: "RSI (prior candle)",
      statusText: data.rsi != null ? data.rsi.toFixed(1) : "—",
      toneClass: data.rsi != null && data.rsi < 30 ? "text-positive" : "text-text-tertiary",
    },
    {
      key: "close",
      label: "Close",
      statusText: data.close != null ? `$${data.close.toFixed(2)}` : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "as-of",
      label: "As of",
      statusText: fmtAsOf(data.as_of),
      toneClass: "text-text-tertiary",
    },
    {
      key: "source",
      label: "Data source",
      statusText: SOURCE_LABEL[data.source] ?? data.source,
      toneClass: "text-text-tertiary",
    },
  ];

  return (
    <ChecklistCard
      title="BB + RSI Entry Signal (2h)"
      statusLabel={data.fired ? "Signal active" : "No signal"}
      statusToneClass={data.fired ? "border-positive/40 bg-positive/10 text-positive" : "border-border-card bg-surface-2 text-text-tertiary"}
      blurb="Bollinger Band %B in the bottom 5% of the band, combined with an oversold prior-bar RSI, on 2-hour session candles."
      items={items}
      disclaimer={DISCLAIMER}
      collapsible
    />
  );
}
