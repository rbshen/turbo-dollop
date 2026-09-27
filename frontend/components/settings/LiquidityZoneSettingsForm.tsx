"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { LiquidityZoneConfigOut } from "@/lib/api/types";
import { useLiquidityZoneConfig } from "@/lib/hooks/useLiquidityZoneConfig";
import { InfoTooltip } from "@/components/ui/InfoTooltip";
import { NumberStepper } from "@/components/ui/NumberStepper";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function LiquidityZoneSettingsForm() {
  const { data, error, isLoading } = useLiquidityZoneConfig();

  if (error) {
    return <p className="text-sm text-red-400">Couldn&apos;t load Liquidity Zone settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save remounts this with fresh initial state --
  // same convention as DiscountRateSettingsForm.
  return <LiquidityZoneForm key={data.updated_at} data={data} />;
}

function LiquidityZoneForm({ data }: { data: LiquidityZoneConfigOut }) {
  const [swingBars, setSwingBars] = useState(data.swing_bars_each_side);
  const [clusterPct, setClusterPct] = useState(data.cluster_pct);
  const [maxLps, setMaxLps] = useState(data.max_lps_per_side);
  const [priority, setPriority] = useState<LiquidityZoneConfigOut["over_cap_priority"]>(data.over_cap_priority);
  const [keepSupport, setKeepSupport] = useState(data.keep_last_breached_support);
  const [keepResistance, setKeepResistance] = useState(data.keep_last_breached_resistance);
  const [onlyRecent, setOnlyRecent] = useState(data.only_keep_if_breached_recently);
  const [recencyBars, setRecencyBars] = useState(data.breach_recency_bars);
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    setStatus("saving");
    try {
      await apiPut<LiquidityZoneConfigOut>("/config/liquidity-zones", {
        swing_bars_each_side: swingBars,
        cluster_pct: clusterPct,
        max_lps_per_side: maxLps,
        breach_recency_bars: recencyBars,
        over_cap_priority: priority,
        keep_last_breached_support: keepSupport,
        keep_last_breached_resistance: keepResistance,
        only_keep_if_breached_recently: onlyRecent,
      });
      await mutate("/config/liquidity-zones");
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  const labelCls = "flex items-center gap-1.5 text-xs uppercase tracking-widest text-zinc-500";
  const selectCls =
    "mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none";

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Liquidity Zones</h2>
        <p className="mt-1 text-xs text-zinc-600">
          Swing-based support/resistance detection, computed nightly for watchlists named W1 through W5 only. One set of
          settings is shared by the Daily and Weekly computations. Changes here apply on the next nightly run, not
          retroactively.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <div className="space-y-4">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Detection</h3>
          <div>
            <label className={labelCls} htmlFor="lz-swing-bars">
              Swing bars (each side)
              <InfoTooltip
                label="About swing bars"
                text="Bars on EACH side of the pivot. 2 = a 5-bar window (2 left + pivot + 2 right). A swing needs this many bars to its right before it is confirmed."
              />
            </label>
            <NumberStepper id="lz-swing-bars" value={swingBars} onChange={setSwingBars} min={1} max={3} step={1} />
          </div>
          <div>
            <label className={labelCls} htmlFor="lz-cluster-pct">
              Cluster % (0 disables)
              <InfoTooltip
                label="About cluster %"
                text="Merge consecutive valid liquidity zones within this % of each other into one zone. Support zones are represented by their LOWEST price; resistance zones by their HIGHEST price. 0 = clustering off."
              />
            </label>
            <NumberStepper id="lz-cluster-pct" value={clusterPct} onChange={setClusterPct} min={0} max={3} step={0.1} />
          </div>
        </div>

        <div className="space-y-4">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Display</h3>
          <div>
            <label className={labelCls} htmlFor="lz-max-lps">
              Max zones per side
              <InfoTooltip
                label="About max zones per side"
                text="Cap on how many valid zones to show per side. The last-breached zone (if enabled below) is shown separately and does not count toward this cap."
              />
            </label>
            <NumberStepper id="lz-max-lps" value={maxLps} onChange={setMaxLps} min={1} max={10} step={1} />
          </div>
          <div>
            <label className={labelCls} htmlFor="lz-priority">
              When over the cap, keep
              <InfoTooltip
                label="About over-cap priority"
                text="When there are more valid zones than the cap allows, choose which to keep: 'Nearest price' keeps the zones closest to the current price; 'Most recent' keeps the newest ones instead, regardless of price distance."
              />
            </label>
            <select
              id="lz-priority"
              className={selectCls}
              value={priority}
              onChange={(e) => setPriority(e.target.value as LiquidityZoneConfigOut["over_cap_priority"])}
            >
              <option value="nearest_price">Nearest to price</option>
              <option value="most_recent">Most recent</option>
            </select>
          </div>
        </div>

        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Last breached Liquidity</h3>
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input type="checkbox" checked={keepSupport} onChange={(e) => setKeepSupport(e.target.checked)} />
            Keep last breached support
          </label>
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input type="checkbox" checked={keepResistance} onChange={(e) => setKeepResistance(e.target.checked)} />
            Keep last breached resistance
          </label>
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input type="checkbox" checked={onlyRecent} onChange={(e) => setOnlyRecent(e.target.checked)} />
            Only keep if breached recently
          </label>
          <div className={`ml-3 border-l border-zinc-800 pl-3 transition-opacity ${onlyRecent ? "" : "opacity-40"}`}>
            <label className={labelCls} htmlFor="lz-recency">
              Breach recency (bars)
              <InfoTooltip
                label="About breach recency"
                text="A breached zone is only eligible to be kept and shown if its breach happened within this many bars of the most recent bar."
              />
            </label>
            <NumberStepper
              id="lz-recency"
              value={recencyBars}
              onChange={setRecencyBars}
              min={1}
              max={52}
              step={1}
              disabled={!onlyRecent}
            />
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={status === "saving"}
          className="rounded-md border border-zinc-700 bg-zinc-800 px-4 py-1.5 text-sm font-medium text-zinc-200 transition-colors hover:border-zinc-500 hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {STATUS_LABELS[status]}
        </button>
        <p className="text-xs text-zinc-600">Last updated {new Date(data.updated_at).toLocaleString()}</p>
      </div>
    </div>
  );
}
