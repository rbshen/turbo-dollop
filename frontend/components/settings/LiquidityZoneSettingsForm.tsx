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
  const [dailySwingBars, setDailySwingBars] = useState(String(data.daily_swing_bars));
  const [dailyClusterPct, setDailyClusterPct] = useState(String(data.daily_cluster_pct));
  const [dailyNumZones, setDailyNumZones] = useState(String(data.daily_num_zones));
  const [weeklySwingBars, setWeeklySwingBars] = useState(String(data.weekly_swing_bars));
  const [weeklyClusterPct, setWeeklyClusterPct] = useState(String(data.weekly_cluster_pct));
  const [weeklyNumZones, setWeeklyNumZones] = useState(String(data.weekly_num_zones));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const parsed = {
      daily_swing_bars: parseInt(dailySwingBars, 10),
      daily_cluster_pct: parseFloat(dailyClusterPct),
      daily_num_zones: parseInt(dailyNumZones, 10),
      weekly_swing_bars: parseInt(weeklySwingBars, 10),
      weekly_cluster_pct: parseFloat(weeklyClusterPct),
      weekly_num_zones: parseInt(weeklyNumZones, 10),
    };
    if (Object.values(parsed).some((v) => Number.isNaN(v))) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<LiquidityZoneConfigOut>("/config/liquidity-zones", parsed);
      await mutate("/config/liquidity-zones");
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Liquidity Zones</h2>
        <p className="mt-1 text-xs text-zinc-600">
          Swing-based support/resistance detection, computed nightly for watchlists named W1 through W5 only. Daily and
          Weekly each have their own independent settings. Changes here apply on the next nightly run, not retroactively.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <TimeframeFields
          label="Daily"
          swingBars={dailySwingBars}
          setSwingBars={setDailySwingBars}
          clusterPct={dailyClusterPct}
          setClusterPct={setDailyClusterPct}
          numZones={dailyNumZones}
          setNumZones={setDailyNumZones}
          idPrefix="daily"
        />
        <TimeframeFields
          label="Weekly"
          swingBars={weeklySwingBars}
          setSwingBars={setWeeklySwingBars}
          clusterPct={weeklyClusterPct}
          setClusterPct={setWeeklyClusterPct}
          numZones={weeklyNumZones}
          setNumZones={setWeeklyNumZones}
          idPrefix="weekly"
        />
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

interface TimeframeFieldsProps {
  label: string;
  idPrefix: string;
  swingBars: string;
  setSwingBars: (v: string) => void;
  clusterPct: string;
  setClusterPct: (v: string) => void;
  numZones: string;
  setNumZones: (v: string) => void;
}

function TimeframeFields({
  label,
  idPrefix,
  swingBars,
  setSwingBars,
  clusterPct,
  setClusterPct,
  numZones,
  setNumZones,
}: TimeframeFieldsProps) {
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">{label}</h3>
      <div>
        <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor={`${idPrefix}-swing-bars`}>
          Swing bars (each side)
        </label>
        <input
          id={`${idPrefix}-swing-bars`}
          type="number"
          step="1"
          min="1"
          className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
          value={swingBars}
          onChange={(e) => setSwingBars(e.target.value)}
        />
      </div>
      <div>
        <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor={`${idPrefix}-cluster-pct`}>
          Cluster % (0 disables)
        </label>
        <input
          id={`${idPrefix}-cluster-pct`}
          type="number"
          step="0.1"
          min="0"
          className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
          value={clusterPct}
          onChange={(e) => setClusterPct(e.target.value)}
        />
      </div>
      <div>
        <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor={`${idPrefix}-num-zones`}>
          Zones shown per side
        </label>
        <input
          id={`${idPrefix}-num-zones`}
          type="number"
          step="1"
          min="1"
          className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
          value={numZones}
          onChange={(e) => setNumZones(e.target.value)}
        />
      </div>
    </div>
  );
}
