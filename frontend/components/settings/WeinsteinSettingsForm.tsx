"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { WeinsteinConfigOut } from "@/lib/api/types";
import { useWeinsteinConfig } from "@/lib/hooks/useWeinsteinConfig";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function WeinsteinSettingsForm() {
  const { data, error, isLoading } = useWeinsteinConfig();

  if (error) {
    return <p className="text-sm text-red-400">Couldn&apos;t load Weinstein settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save remounts this with fresh initial text --
  // same convention as LiquidityZoneSettingsForm.
  return <WeinsteinForm key={data.updated_at} data={data} />;
}

function WeinsteinForm({ data }: { data: WeinsteinConfigOut }) {
  const [maLength, setMaLength] = useState(String(data.ma_length));
  const [maType, setMaType] = useState<WeinsteinConfigOut["ma_type"]>(data.ma_type);
  const [rangePct, setRangePct] = useState(String(data.within_range_pct));
  const [slopeLookback, setSlopeLookback] = useState(String(data.slope_lookback));
  const [volMult, setVolMult] = useState(String(data.breakout_volume_mult));
  const [volAvgLength, setVolAvgLength] = useState(String(data.volume_avg_length));
  const [benchmark, setBenchmark] = useState(data.rs_benchmark);
  const [rsSmoothing, setRsSmoothing] = useState(String(data.rs_smoothing_length));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const numbers = {
      ma_length: parseInt(maLength, 10),
      within_range_pct: parseFloat(rangePct),
      slope_lookback: parseInt(slopeLookback, 10),
      breakout_volume_mult: parseFloat(volMult),
      volume_avg_length: parseInt(volAvgLength, 10),
      rs_smoothing_length: parseInt(rsSmoothing, 10),
    };
    if (Object.values(numbers).some((v) => Number.isNaN(v)) || benchmark.trim() === "") {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
      return;
    }
    setStatus("saving");
    try {
      await apiPut<WeinsteinConfigOut>("/config/weinstein", {
        ...numbers,
        ma_type: maType,
        rs_benchmark: benchmark.trim(),
      });
      await mutate("/config/weinstein");
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
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Weinstein Stage</h2>
        <p className="mt-1 text-xs text-zinc-600">
          Parameters for the weekly Stage 1-4 engine (Base / Advance / Top / Decline) behind the ticker-header pill, the
          Technical tab card and the Screener filter. Changes apply the next time a ticker is recomputed (the nightly
          trend job, or an on-demand ticker view) — no restart needed. The engine always runs on weekly bars.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Stage</h3>
          <div>
            <label className={labelCls} htmlFor="ws-ma-length">MA length (weeks)</label>
            <input id="ws-ma-length" type="number" step="1" min="2" className={inputCls} value={maLength} onChange={(e) => setMaLength(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="ws-ma-type">MA type</label>
            <select id="ws-ma-type" className={inputCls} value={maType} onChange={(e) => setMaType(e.target.value as WeinsteinConfigOut["ma_type"])}>
              <option value="EMA">EMA</option>
              <option value="SMA">SMA</option>
            </select>
          </div>
          <div>
            <label className={labelCls} htmlFor="ws-range-pct">Within range (%)</label>
            <input id="ws-range-pct" type="number" step="0.5" min="0" className={inputCls} value={rangePct} onChange={(e) => setRangePct(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="ws-slope-lookback">Slope lookback (bars)</label>
            <input id="ws-slope-lookback" type="number" step="1" min="1" className={inputCls} value={slopeLookback} onChange={(e) => setSlopeLookback(e.target.value)} />
          </div>
        </div>

        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Breakout &amp; relative strength</h3>
          <div>
            <label className={labelCls} htmlFor="ws-vol-mult">Breakout volume (x average)</label>
            <input id="ws-vol-mult" type="number" step="0.1" min="0.1" className={inputCls} value={volMult} onChange={(e) => setVolMult(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="ws-vol-avg">Volume average length (weeks)</label>
            <input id="ws-vol-avg" type="number" step="1" min="2" className={inputCls} value={volAvgLength} onChange={(e) => setVolAvgLength(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="ws-benchmark">RS benchmark</label>
            <input id="ws-benchmark" type="text" className={inputCls} value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="ws-rs-smoothing">RS smoothing length (weeks)</label>
            <input id="ws-rs-smoothing" type="number" step="1" min="2" className={inputCls} value={rsSmoothing} onChange={(e) => setRsSmoothing(e.target.value)} />
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
