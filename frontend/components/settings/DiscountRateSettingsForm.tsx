"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { DiscountRateConfigOut } from "@/lib/api/types";
import { useDiscountRateConfigs } from "@/lib/hooks/useDiscountRateConfig";
import { fmtNumber } from "@/lib/format";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

// A region's own display name, where it differs from its bare code. Only
// US/HK/FR are supported (backend helpers/discount_rate_config.py::
// SUPPORTED_REGIONS) -- US always exists by default; HK/FR are lazily
// seeded the first time a ticker from that country is valued, so either
// may be absent here until then. A ticker from any other country uses the
// US rate directly and never gets its own row.
const REGION_LABELS: Record<string, string> = {
  US: "United States",
  HK: "Hong Kong",
  FR: "France",
};

function regionLabel(region: string): string {
  return REGION_LABELS[region] ?? region;
}

export function DiscountRateSettingsForm() {
  const { data, error, isLoading } = useDiscountRateConfigs();

  if (error) {
    return <p className="text-sm text-red-400">Couldn&apos;t load discount rate settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Discount Rate by Country</h2>
        <p className="mt-1 text-xs text-zinc-600">
          Risk-Free Rate and Market Risk Premium are 5-year trailing averages from market-risk-premia.com — manually
          maintained here, not auto-fetched (see CLAUDE.md). Beta stays sourced live per-ticker from FMP. Feeds a
          ticker&apos;s own country&apos;s Valuation discount rate: <span className="font-mono text-zinc-400">Rf + β × MRP</span>. A
          country appears here once a ticker from it has been valued at least once — its row seeds from the current
          US values as a placeholder until edited. Only United States, Hong Kong, and France get their own rate; a
          ticker from any other country uses the US rate directly.
        </p>
      </div>

      <div className="space-y-4">
        {data.map((row) => (
          // Keyed on region + updated_at so a save (which changes updated_at)
          // remounts just that region's form with fresh initial text --
          // avoids setState-in-effect just to resync local edit state.
          <DiscountRateForm key={`${row.region}-${row.updated_at}`} data={row} />
        ))}
      </div>
    </div>
  );
}

function DiscountRateForm({ data }: { data: DiscountRateConfigOut }) {
  const [rfText, setRfText] = useState(fmtNumber(data.risk_free_rate * 100, 3));
  const [mrpText, setMrpText] = useState(fmtNumber(data.market_risk_premium * 100, 3));
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
        region: data.region,
        risk_free_rate: riskFreeRate / 100,
        market_risk_premium: marketRiskPremium / 100,
      });
      await mutate("/config/discount-rate");
      await mutate("/config/discount-rates");
      // Every ticker's Step 3 discount rate is derived from this config --
      // invalidate every cached Step 3 fetch (and the ticker header, which
      // also reads Step 3's result) so the next view reflects the new rate
      // without a manual page reload. Invalidates every region's cache at
      // once (not just this row's) since there's no cheap way to know from
      // here which cached /step3 responses belong to this region's
      // tickers -- an over-invalidation, not a correctness issue.
      await mutate((key) => typeof key === "string" && (key.includes("/step3") || key.includes("/summary")));
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <h3 className="text-sm font-semibold text-zinc-200">
        {regionLabel(data.region)} <span className="font-mono text-xs text-zinc-500">({data.region})</span>
      </h3>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor={`risk-free-rate-${data.region}`}>
            Risk-Free Rate (%)
          </label>
          <input
            id={`risk-free-rate-${data.region}`}
            type="number"
            step="0.001"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
            value={rfText}
            onChange={(e) => setRfText(e.target.value)}
          />
        </div>
        <div>
          <label
            className="block text-xs uppercase tracking-widest text-zinc-500"
            htmlFor={`market-risk-premium-${data.region}`}
          >
            Market Risk Premium (%)
          </label>
          <input
            id={`market-risk-premium-${data.region}`}
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
