import { useLiquidityZoneConfig } from "@/lib/hooks/useLiquidityZoneConfig";
import type { LiquidityZoneOut, LiquidityZonesOut, ZoneOut } from "@/lib/api/types";

interface Props {
  data: LiquidityZonesOut | null;
}

// Matches backend's helpers/liquidity_zone_config.py::DEFAULT_NUM_ZONES --
// used only until useLiquidityZoneConfig() resolves, so slots still render
// sensibly on first paint.
const DEFAULT_NUM_ZONES = 3;

const DISCLAIMER =
  'Unbreached swing-low support / swing-high resistance levels, clustered by price -- only a LATER swing of the same kind invalidates an earlier one, an ordinary price move through a level does not. Computed nightly for tickers in the "W1" or "W2" watchlists only. Informational only, not a trading signal.';

const UNAVAILABLE_MESSAGE =
  'No Liquidity Zone data tracked for this ticker -- this check only runs nightly for tickers in the "W1" or "W2" watchlists.';

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

// A slot with no real zone in it -- mirrors ZoneRow's exact box model (same
// flex/padding/text sizing) so its height matches a real row precisely, but
// styled as an obviously empty placeholder (dashed, faint) rather than fully
// invisible, so it reads as "an empty slot by design," not a stray gap.
function BlankZoneSlot() {
  return (
    <li
      className="flex items-center justify-between gap-3 rounded-md border border-dashed border-border-card/30 px-3 py-2 text-sm text-text-tertiary/30"
      aria-hidden="true"
    >
      <span>&mdash;</span>
    </li>
  );
}

// Always renders exactly `numSlots` rows -- real zones first, then blank
// filler slots -- so a side with fewer real zones than the configured cap
// still occupies the same vertical space as a full side, keeping the
// current-price divider below it at a fixed row position.
function ZoneList({ zones, tone, numSlots }: { zones: ZoneOut[]; tone: "support" | "resistance"; numSlots: number }) {
  const shown = zones.slice(0, numSlots);
  const blanks = Math.max(0, numSlots - shown.length);
  return (
    <ul className="space-y-1">
      {shown.map((z) => (
        <ZoneRow key={`${tone}-${z.price}`} zone={z} tone={tone} />
      ))}
      {Array.from({ length: blanks }, (_, i) => (
        <BlankZoneSlot key={`${tone}-blank-${i}`} />
      ))}
    </ul>
  );
}

function TimeframeSection({ label, tf, numSlots }: { label: string; tf: LiquidityZoneOut; numSlots: number }) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">{label}</h3>
        <span className="text-xs text-text-tertiary">
          Last {fmtPrice(tf.last_price)} · Computed {fmtDate(tf.computed_at)}
        </span>
      </div>

      <div className="space-y-1">
        <p className="text-[11px] uppercase tracking-wide text-text-tertiary">Resistance</p>
        <ZoneList zones={tf.resistance_zones} tone="resistance" numSlots={numSlots} />
      </div>

      <div className="border-t border-border-card/60 pt-1 text-center text-[11px] uppercase tracking-wide text-text-tertiary">
        current price
      </div>

      <div className="space-y-1">
        <p className="text-[11px] uppercase tracking-wide text-text-tertiary">Support</p>
        <ZoneList zones={tf.support_zones} tone="support" numSlots={numSlots} />
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
  // Independent per-timeframe caps (daily_num_zones/weekly_num_zones CAN
  // differ -- see the settings form) -- fixed-slot alignment across the two
  // columns below only holds when they're set to the same value. Falls back
  // to DEFAULT_NUM_ZONES while config is still loading.
  const { data: config } = useLiquidityZoneConfig();
  const dailyNumSlots = config?.daily_num_zones ?? DEFAULT_NUM_ZONES;
  const weeklyNumSlots = config?.weekly_num_zones ?? DEFAULT_NUM_ZONES;

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
        {data.daily ? (
          <TimeframeSection label="Daily" tf={data.daily} numSlots={dailyNumSlots} />
        ) : (
          <EmptyTimeframe label="Daily" />
        )}
        {data.weekly ? (
          <TimeframeSection label="Weekly" tf={data.weekly} numSlots={weeklyNumSlots} />
        ) : (
          <EmptyTimeframe label="Weekly" />
        )}
      </div>

      <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">{DISCLAIMER}</p>
    </div>
  );
}
