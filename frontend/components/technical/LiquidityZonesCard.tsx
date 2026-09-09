import type { LiquidityZoneOut, LiquidityZonesOut, ZoneOut } from "@/lib/api/types";

interface Props {
  data: LiquidityZonesOut | null;
}

const DISCLAIMER =
  'Unbreached swing-low support / swing-high resistance levels, clustered by price -- only a LATER swing of the same kind invalidates an earlier one, an ordinary price move through a level does not. Computed nightly for tickers in the "Watchlist" watchlist only. Informational only, not a trading signal.';

const UNAVAILABLE_MESSAGE =
  'No Liquidity Zone data tracked for this ticker -- this check only runs nightly for tickers in the "Watchlist" watchlist.';

function fmtPrice(price: number): string {
  return `$${price.toFixed(2)}`;
}

function fmtDistance(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function ZoneRow({ zone, tone }: { zone: ZoneOut; tone: "support" | "resistance" }) {
  const priceClass = tone === "support" ? "text-positive" : "text-negative";
  return (
    <li className="flex items-center justify-between gap-3 rounded-md border border-border-card/60 px-3 py-2 text-sm">
      <div className="min-w-0">
        <span className={`font-mono ${priceClass}`}>{fmtPrice(zone.price)}</span>
        <span className="ml-2 text-xs text-text-tertiary">
          {zone.cluster_size > 1 ? `${zone.cluster_size} swings merged` : "single swing"} · since {fmtDate(zone.formed_at)}
        </span>
      </div>
      <span className={`shrink-0 text-xs font-medium ${priceClass}`}>{fmtDistance(zone.distance_pct)}</span>
    </li>
  );
}

function ZoneList({ zones, tone, emptyLabel }: { zones: ZoneOut[]; tone: "support" | "resistance"; emptyLabel: string }) {
  if (zones.length === 0) {
    return <p className="text-xs text-text-tertiary">No confirmed {emptyLabel} levels yet.</p>;
  }
  return (
    <ul className="space-y-1">
      {zones.map((z) => (
        <ZoneRow key={`${tone}-${z.price}`} zone={z} tone={tone} />
      ))}
    </ul>
  );
}

function TimeframeSection({ label, tf }: { label: string; tf: LiquidityZoneOut }) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">{label}</h3>
        <span className="text-xs text-text-tertiary">Last {fmtPrice(tf.last_price)}</span>
      </div>

      <div className="space-y-1">
        <p className="text-[11px] uppercase tracking-wide text-text-tertiary">Resistance</p>
        <ZoneList zones={tf.resistance_zones} tone="resistance" emptyLabel="resistance" />
      </div>

      <div className="border-t border-border-card/60 pt-1 text-center text-[11px] uppercase tracking-wide text-text-tertiary">
        current price
      </div>

      <div className="space-y-1">
        <p className="text-[11px] uppercase tracking-wide text-text-tertiary">Support</p>
        <ZoneList zones={tf.support_zones} tone="support" emptyLabel="support" />
      </div>
    </div>
  );
}

function EmptyTimeframe({ label }: { label: string }) {
  return (
    <div className="space-y-1">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">{label}</h3>
      <p className="text-xs text-text-tertiary">Not yet computed for this timeframe.</p>
    </div>
  );
}

export function LiquidityZonesCard({ data }: Props) {
  if (!data || (!data.daily && !data.weekly)) {
    return (
      <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <h2 className="font-heading text-sm font-semibold text-text-primary">Liquidity Zones</h2>
            <p className="text-sm text-text-secondary">Swing-based support/resistance levels, Daily and Weekly.</p>
          </div>
          <span className="shrink-0 rounded-full border border-border-card bg-surface-2 px-3 py-1 text-xs font-semibold text-text-tertiary">
            Not tracked
          </span>
        </div>
        <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">{UNAVAILABLE_MESSAGE}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <div className="space-y-1">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Liquidity Zones</h2>
        <p className="text-sm text-text-secondary">Nearest unbreached swing-based support/resistance levels, clustered by price.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {data.daily ? <TimeframeSection label="Daily" tf={data.daily} /> : <EmptyTimeframe label="Daily" />}
        {data.weekly ? <TimeframeSection label="Weekly" tf={data.weekly} /> : <EmptyTimeframe label="Weekly" />}
      </div>

      <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">{DISCLAIMER}</p>
    </div>
  );
}
