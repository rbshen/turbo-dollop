"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { DiscountRateConfigOut } from "@/lib/api/types";
import { useDiscountRateConfig } from "@/lib/hooks/useDiscountRateConfig";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function DiscountRateSettingsForm() {
  const { data, error, isLoading } = useDiscountRateConfig();

  if (error) {
    return <p className="text-sm text-red-400">Couldn&apos;t load discount rate settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (which changes updated_at) remounts this
  // with fresh initial text -- avoids setState-in-effect just to resync
  // local edit state with a reloaded server value.
  return <DiscountRateForm key={data.updated_at} data={data} />;
}

function DiscountRateForm({ data }: { data: DiscountRateConfigOut }) {
  const [rfText, setRfText] = useState((data.risk_free_rate * 100).toFixed(3));
  const [mrpText, setMrpText] = useState((data.market_risk_premium * 100).toFixed(3));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const riskFreeRate = parseFloat(rfText);
    const marketRiskPremium = parseFloat(mrpText);
    if (Number.isNaN(riskFreeRate) || Number.isNaN(marketRiskPremium)) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<DiscountRateConfigOut>("/config/discount-rate", {
        risk_free_rate: riskFreeRate / 100,
        market_risk_premium: marketRiskPremium / 100,
      });
      await mutate("/config/discount-rate");
      // Every ticker's Step 3 discount rate is derived from this config --
      // invalidate every cached Step 3 fetch (and the ticker header, which
      // also reads Step 3's result) so the next view reflects the new rate
      // without a manual page reload.
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
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">CAPM Discount Rate — US</h2>
        <p className="mt-1 text-xs text-zinc-600">
          Risk-Free Rate and Market Risk Premium are 5-year trailing averages from market-risk-premia.com/us.html — manually
          maintained here, not auto-fetched (see CLAUDE.md). Beta stays sourced live per-ticker from FMP. Feeds every ticker&apos;s
          Step 3 discount rate: <span className="font-mono text-zinc-400">Rf + β × MRP</span>.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="risk-free-rate">
            Risk-Free Rate (%)
          </label>
          <input
            id="risk-free-rate"
            type="number"
            step="0.001"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
            value={rfText}
            onChange={(e) => setRfText(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="market-risk-premium">
            Market Risk Premium (%)
          </label>
          <input
            id="market-risk-premium"
            type="number"
            step="0.001"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
            value={mrpText}
            onChange={(e) => setMrpText(e.target.value)}
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
