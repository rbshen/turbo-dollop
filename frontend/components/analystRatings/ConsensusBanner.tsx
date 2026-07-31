import type { ConsensusBanner as ConsensusBannerData } from "@/lib/api/types";

interface Props {
  data: ConsensusBannerData;
}

// Same fixed status-palette steps (good/warning/critical) as
// AnalystDistributionBar's own segments -- kept in sync by convention, not
// a shared import, since it's a handful of CSS-var references used in 2
// places with slightly different category counts (3 here, 5 there).
const STATUS_COLORS = { buy: "var(--color-positive)", hold: "var(--color-warn)", sell: "var(--color-negative)" };

export function ConsensusBanner({ data }: Props) {
  const total = data.buy_count + data.hold_count + data.sell_count;
  const buyPct = total ? (data.buy_count / total) * 100 : 0;
  const holdPct = total ? (data.hold_count / total) * 100 : 0;
  const sellPct = total ? (data.sell_count / total) * 100 : 0;

  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="text-xs uppercase tracking-widest text-text-tertiary">Consensus Rating</p>
          <p className="font-mono text-3xl font-bold tabular-nums text-text-primary">{data.rating}</p>
        </div>
        <p className="text-sm text-text-tertiary">{data.analyst_count} analysts</p>
      </div>

      <div className="flex h-2 overflow-hidden rounded-full bg-surface-2">
        {buyPct > 0 && <div style={{ width: `${buyPct}%`, backgroundColor: STATUS_COLORS.buy }} />}
        {holdPct > 0 && <div style={{ width: `${holdPct}%`, backgroundColor: STATUS_COLORS.hold }} />}
        {sellPct > 0 && <div style={{ width: `${sellPct}%`, backgroundColor: STATUS_COLORS.sell }} />}
      </div>

      <div className="flex gap-6 text-sm">
        <span className="flex items-center gap-1.5 text-text-secondary">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: STATUS_COLORS.buy }} />
          Buy <span className="text-text-primary">{data.buy_count}</span>
        </span>
        <span className="flex items-center gap-1.5 text-text-secondary">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: STATUS_COLORS.hold }} />
          Hold <span className="text-text-primary">{data.hold_count}</span>
        </span>
        <span className="flex items-center gap-1.5 text-text-secondary">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: STATUS_COLORS.sell }} />
          Sell <span className="text-text-primary">{data.sell_count}</span>
        </span>
      </div>
    </div>
  );
}
