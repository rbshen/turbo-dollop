"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { LiquidityZoneConfigOut } from "@/lib/api/types";
import { useLiquidityZoneConfig } from "@/lib/hooks/useLiquidityZoneConfig";

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

  // Keyed on updated_at so a save remounts this with fresh initial text --
  // same convention as DiscountRateSettingsForm.
  return <LiquidityZoneForm key={data.updated_at} data={data} />;
}

function LiquidityZoneForm({ data }: { data: LiquidityZoneConfigOut }) {
  const [swingBars, setSwingBars] = useState(String(data.swing_bars_each_side));
  const [clusterPct, setClusterPct] = useState(String(data.cluster_pct));
  const [maxLps, setMaxLps] = useState(String(data.max_lps_per_side));
  const [priority, setPriority] = useState<LiquidityZoneConfigOut["over_cap_priority"]>(data.over_cap_priority);
  const [keepSupport, setKeepSupport] = useState(data.keep_last_breached_support);
  const [keepResistance, setKeepResistance] = useState(data.keep_last_breached_resistance);
  const [onlyRecent, setOnlyRecent] = useState(data.only_keep_if_breached_recently);
  const [recencyBars, setRecencyBars] = useState(String(data.breach_recency_bars));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const numbers = {
      swing_bars_each_side: parseInt(swingBars, 10),
      cluster_pct: parseFloat(clusterPct),
      max_lps_per_side: parseInt(maxLps, 10),
      breach_recency_bars: parseInt(recencyBars, 10),
    };
    if (Object.values(numbers).some((v) => Number.isNaN(v))) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<LiquidityZoneConfigOut>("/config/liquidity-zones", {
        ...numbers,
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

  const labelCls = "block text-xs uppercase tracking-widest text-zinc-500";
  const inputCls =
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

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Detection</h3>
          <div>
            <label className={labelCls} htmlFor="lz-swing-bars">Swing bars (each side)</label>
            <input id="lz-swing-bars" type="number" step="1" min="1" className={inputCls} value={swingBars} onChange={(e) => setSwingBars(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="lz-cluster-pct">Cluster % (0 disables)</label>
            <input id="lz-cluster-pct" type="number" step="0.1" min="0" className={inputCls} value={clusterPct} onChange={(e) => setClusterPct(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="lz-max-lps">Max zones per side</label>
            <input id="lz-max-lps" type="number" step="1" min="1" className={inputCls} value={maxLps} onChange={(e) => setMaxLps(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="lz-priority">When over the cap, keep</label>
            <select id="lz-priority" className={inputCls} value={priority} onChange={(e) => setPriority(e.target.value as LiquidityZoneConfigOut["over_cap_priority"])}>
              <option value="nearest_price">Nearest to price</option>
              <option value="most_recent">Most recent</option>
            </select>
          </div>
        </div>

        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Last breached LP</h3>
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
          <div>
            <label className={labelCls} htmlFor="lz-recency">Breach recency (bars)</label>
            <input id="lz-recency" type="number" step="1" min="0" className={inputCls} value={recencyBars} onChange={(e) => setRecencyBars(e.target.value)} disabled={!onlyRecent} />
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
