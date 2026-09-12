import { ChecklistCard, type ChecklistItem } from "@/components/technical/ChecklistCard";
import type { TechnicalEntrySignalOut } from "@/lib/api/types";

interface Props {
  data: TechnicalEntrySignalOut | null;
}

const DISCLAIMER =
  "RSI/ADX/WVF buy-and-sell state machine (Yellow/Gray/Blue Up and Down arrows, a trailing stop line, and a gray-suppression latch after 2 stop-outs since the last Blue trigger), ported from a reference trading bot. \"Active\" tracks the state machine's own in-trade status (the last event was a buy-side arrow), not a fixed time window. The stop line is a live computed reference level, not a trailing/executed stop -- there's no position being tracked. Display-only -- Fathom does not execute trades. Informational only, not a trading signal.";

const UNAVAILABLE_MESSAGE =
  'No Warren RSI/ADX/WVF entry signal tracked for this ticker -- this check only runs nightly for tickers in a "W1"-"W5" watchlist.';

const SOURCE_LABEL: Record<string, string> = {
  yahoo: "Yahoo Finance",
  fmp: "Financial Modeling Prep",
};

const KIND_LABELS: Record<string, string> = {
  blue_up: "Blue Up",
  yellow_up: "Yellow Up",
  gray_up: "Gray Up",
  blue_down: "Blue Down",
  yellow_down: "Yellow Down",
  gray_down: "Gray Down",
};

const UP_KINDS = new Set(["blue_up", "yellow_up", "gray_up"]);

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function WarrenSignalCard({ data }: Props) {
  if (!data) {
    return (
      <ChecklistCard
        title="Warren RSI/ADX/WVF Entry Signal (2h)"
        statusLabel="Not tracked"
        statusToneClass="border-border-card bg-surface-2 text-text-tertiary"
        blurb="RSI/ADX/WVF buy-and-sell state machine with a trailing stop line and gray-suppression latch, on 2-hour session candles."
        items={[]}
        disclaimer={UNAVAILABLE_MESSAGE}
      />
    );
  }

  const kindLabel = data.signal_kind != null ? (KIND_LABELS[data.signal_kind] ?? data.signal_kind) : null;
  const kindIsBuy = data.signal_kind != null && UP_KINDS.has(data.signal_kind);

  const items: ChecklistItem[] = [
    {
      key: "last-signal",
      label: "Last signal",
      statusText: kindLabel != null && data.fired_at != null ? `${kindLabel} — ${fmtDateTime(data.fired_at)}` : "Never fired",
      toneClass: kindIsBuy ? "text-positive" : data.signal_kind != null ? "text-negative" : "text-text-tertiary",
    },
    {
      key: "gray-suppression",
      label: "Gray suppression",
      statusText:
        data.gray_suppressed === true
          ? `Suppressed — stopped out ${data.stop_count ?? "?"}x since the last Blue trigger`
          : data.gray_suppressed === false
            ? "Not suppressed"
            : "—",
      toneClass: data.gray_suppressed ? "text-text-tertiary" : "text-positive",
      detail: "A Yellow trigger renders Gray instead once 2 stop-outs have occurred since the last Blue trigger.",
    },
    {
      key: "stop-price",
      label: "Stop line",
      statusText: data.stop_price != null ? `$${data.stop_price.toFixed(2)}` : "—",
      toneClass: "text-text-tertiary",
      detail: "The live reference stop from the most recently held Yellow/Gray entry -- not necessarily tied to the last signal shown above.",
    },
    {
      key: "rsi",
      label: "RSI (at last signal)",
      statusText: data.rsi != null ? data.rsi.toFixed(1) : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "close",
      label: "Close (at last signal)",
      statusText: data.close != null ? `$${data.close.toFixed(2)}` : "—",
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
      title="Warren RSI/ADX/WVF Entry Signal (2h)"
      statusLabel={data.active ? "Signal active" : "No active signal"}
      statusToneClass={data.active ? "border-positive/40 bg-positive/10 text-positive" : "border-border-card bg-surface-2 text-text-tertiary"}
      blurb="RSI/ADX/WVF buy-and-sell state machine with a trailing stop line and gray-suppression latch, on 2-hour session candles."
      items={items}
      disclaimer={DISCLAIMER}
      collapsible
    />
  );
}
