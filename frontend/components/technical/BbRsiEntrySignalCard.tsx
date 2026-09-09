import { ChecklistCard, type ChecklistItem } from "@/components/technical/ChecklistCard";
import type { TechnicalEntrySignalOut } from "@/lib/api/types";

interface Props {
  data: TechnicalEntrySignalOut | null;
}

const DISCLAIMER =
  "Bollinger Band %B + RSI oversold check on 2-hour candles, ported from a reference trading bot's entry condition. A fire stays \"active\" for 7 days after it happens. Stop price is a single computed reference level (close - ATR x 2 on the firing bar), not a live/trailing stop -- there's no position being tracked. Display-only -- Fathom does not execute trades. Informational only, not a trading signal.";

const UNAVAILABLE_MESSAGE =
  'No BB+RSI entry signal tracked for this ticker -- this check only runs nightly for tickers in the "Main" or "Secondary" watchlists.';

const SOURCE_LABEL: Record<string, string> = {
  yahoo: "Yahoo Finance",
  fmp: "Financial Modeling Prep",
};

function fmtDateTime(iso: string): string {
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
      key: "last-fired",
      label: "Last fired",
      statusText: data.fired_at != null ? fmtDateTime(data.fired_at) : "Never fired",
      toneClass: "text-text-tertiary",
    },
    {
      key: "pct-b",
      label: "Bollinger Band %B (at last fire)",
      statusText: data.pct_b != null ? data.pct_b.toFixed(4) : "—",
      toneClass: data.pct_b != null && data.pct_b <= 0.05 ? "text-positive" : "text-text-tertiary",
    },
    {
      key: "rsi",
      label: "RSI (at last fire)",
      statusText: data.rsi != null ? data.rsi.toFixed(1) : "—",
      toneClass: data.rsi != null && data.rsi < 30 ? "text-positive" : "text-text-tertiary",
      // The check itself requires the PRIOR candle's RSI to have been
      // oversold -- this is the firing candle's OWN RSI, not the value
      // that actually satisfied the check (see
      // analysis/entry_signal/indicators.py::check_buy_signal).
      detail: "The signal check uses the prior candle's RSI, not this one.",
    },
    {
      key: "close",
      label: "Close (at last fire)",
      statusText: data.close != null ? `$${data.close.toFixed(2)}` : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "stop-price",
      label: "Stop price",
      statusText: data.stop_price != null ? `$${data.stop_price.toFixed(2)}` : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "last-checked",
      label: "Last checked",
      statusText: fmtDateTime(data.as_of),
      toneClass: "text-text-tertiary",
    },
    {
      key: "computed-at",
      label: "Data computed",
      statusText: fmtDateTime(data.computed_at),
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
      statusLabel={data.active ? "Signal active" : "No active signal"}
      statusToneClass={data.active ? "border-positive/40 bg-positive/10 text-positive" : "border-border-card bg-surface-2 text-text-tertiary"}
      blurb="Bollinger Band %B in the bottom 5% of the band, combined with an oversold prior-bar RSI, on 2-hour session candles."
      items={items}
      disclaimer={DISCLAIMER}
      collapsible
    />
  );
}
