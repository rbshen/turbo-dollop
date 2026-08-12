"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { ReitDividendYieldConfigOut } from "@/lib/api/types";
import { useReitDividendYieldConfig } from "@/lib/hooks/useReitDividendYieldConfig";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function ReitDividendYieldSettingsForm() {
  const { data, error, isLoading } = useReitDividendYieldConfig();

  if (error) {
    return <p className="text-sm text-red-400">Couldn&apos;t load REIT dividend yield settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (which changes updated_at) remounts this
  // with fresh initial text -- same pattern as DiscountRateSettingsForm/
  // MoatSettingsForm.
  return <ReitDividendYieldForm key={data.updated_at} data={data} />;
}

function ReitDividendYieldForm({ data }: { data: ReitDividendYieldConfigOut }) {
  const [thresholdText, setThresholdText] = useState(String(data.threshold_pct));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const thresholdPct = parseFloat(thresholdText);
    if (Number.isNaN(thresholdPct)) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<ReitDividendYieldConfigOut>("/config/reit-dividend-yield", { threshold_pct: thresholdPct });
      await mutate("/config/reit-dividend-yield");
      // This threshold feeds Step3Out.dividend_yield_meets_reit_threshold
      // for every REIT ticker -- invalidate every cached Step 3 fetch (and
      // the ticker header, which also reads Step 3's result) so the next
      // view reflects the new threshold without a manual page reload.
      await mutate((key) => typeof key === "string" && (key.includes("/step3") || key.includes("/summary")));
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
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">REIT Dividend Yield Threshold</h2>
        <p className="mt-1 text-xs text-zinc-600">
          Informational bargain-reference check shown on REIT/Property Developer tickers&apos; Valuation tab
          (valuation.md §3.3) — flags whether trailing dividend yield is at or above this threshold. Never affects
          the Price-to-Book calculation or verdict itself.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="reit-dividend-yield-threshold">
            Threshold (%)
          </label>
          <input
            id="reit-dividend-yield-threshold"
            type="number"
            step="0.1"
            min="0"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
            value={thresholdText}
            onChange={(e) => setThresholdText(e.target.value)}
          />
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
