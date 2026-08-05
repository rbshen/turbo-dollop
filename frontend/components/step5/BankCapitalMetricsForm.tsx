"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { Step5Out, TickerBankCapitalMetricsIn, TickerBankCapitalMetricsOut } from "@/lib/api/types";
import { useTickerBankCapitalMetrics } from "@/lib/hooks/useTickerBankCapitalMetrics";
import { fmtPct } from "@/lib/format";

interface Props {
  ticker: string;
  step5: Step5Out;
}

export function BankCapitalMetricsForm({ ticker, step5 }: Props) {
  const { data, error, isLoading } = useTickerBankCapitalMetrics(ticker);

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load CET1/NPL inputs — {error.message}</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }
  return <BankCapitalMetricsControls key={data.updated_at ?? "unset"} ticker={ticker} data={data} step5={step5} />;
}

interface PendingState {
  cet1: string;
  cet1AsOf: string;
  npl: string;
  nplAsOf: string;
}

function BankCapitalMetricsControls({ ticker, data, step5 }: { ticker: string; data: TickerBankCapitalMetricsOut; step5: Step5Out }) {
  const [pending, setPending] = useState<PendingState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const initial: PendingState = {
    cet1: data.cet1_ratio_pct != null ? String(data.cet1_ratio_pct) : "",
    cet1AsOf: data.cet1_as_of ?? "",
    npl: data.npl_ratio_pct != null ? String(data.npl_ratio_pct) : "",
    nplAsOf: data.npl_as_of ?? "",
  };
  const displayed = pending ?? initial;
  const dirty =
    pending !== null &&
    (pending.cet1 !== initial.cet1 ||
      pending.cet1AsOf !== initial.cet1AsOf ||
      pending.npl !== initial.npl ||
      pending.nplAsOf !== initial.nplAsOf);

  function update(field: keyof PendingState, value: string) {
    setPending({ ...displayed, [field]: value });
  }

  async function handleConfirm() {
    if (!pending) return;
    setSaving(true);
    setSaveError(null);
    try {
      const cet1 = pending.cet1.trim() === "" ? null : parseFloat(pending.cet1);
      const npl = pending.npl.trim() === "" ? null : parseFloat(pending.npl);
      if ((pending.cet1.trim() !== "" && Number.isNaN(cet1)) || (pending.npl.trim() !== "" && Number.isNaN(npl))) {
        setSaveError("Enter a valid number.");
        setSaving(false);
        return;
      }
      const body: TickerBankCapitalMetricsIn = {
        cet1_ratio_pct: cet1,
        cet1_as_of: pending.cet1AsOf.trim() === "" ? null : pending.cet1AsOf,
        npl_ratio_pct: npl,
        npl_as_of: pending.nplAsOf.trim() === "" ? null : pending.nplAsOf,
      };
      await apiPut<TickerBankCapitalMetricsOut>(`/tickers/${ticker}/bank-capital-metrics`, body);
      // Same mutate pattern as EconomicMoatTab -- refreshes this form, the
      // Step 5 card, and Overall Assessment together; also revalidate the
      // Screener since its TickerScore row was updated server-side too.
      await mutate((key) => typeof key === "string" && key.startsWith(`/tickers/${ticker}`));
      await mutate("/screener");
      setPending(null);
    } catch {
      setSaveError("Failed to save — please try again.");
    } finally {
      setSaving(false);
    }
  }

  // Only shown while npl_source is "auto" -- once a manual override is
  // active, Step5Out only carries the resolved (overridden) value, not the
  // live auto-computed one, so the helper text degrades to a generic note
  // rather than showing a stale/unavailable auto number.
  const autoNpl = step5.npl_source === "auto" ? step5.ratios.npl_ratio?.value ?? null : null;

  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">CET1 &amp; NPL Ratios</h3>
        <p className="mt-1 text-sm text-text-secondary">
          CET1 has no automated source (manual entry only). NPL is auto-computed where available; entering a value here
          overrides it.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <label className="block text-xs uppercase tracking-widest text-text-tertiary" htmlFor={`${ticker}-cet1`}>
            CET1 Ratio (%)
          </label>
          <input
            id={`${ticker}-cet1`}
            type="number"
            step="0.01"
            value={displayed.cet1}
            onChange={(e) => update("cet1", e.target.value)}
            placeholder="Not yet entered"
            className="w-full rounded-md border border-border-input bg-surface-2 px-2 py-1.5 font-mono text-sm text-text-primary focus:border-brand focus:outline-none"
          />
          <input
            type="text"
            value={displayed.cet1AsOf}
            onChange={(e) => update("cet1AsOf", e.target.value)}
            placeholder="As of (e.g. Q2 2026)"
            className="w-full rounded-md border border-border-input bg-surface-2 px-2 py-1.5 text-xs text-text-secondary focus:border-brand focus:outline-none"
          />
        </div>

        <div className="space-y-2">
          <label className="block text-xs uppercase tracking-widest text-text-tertiary" htmlFor={`${ticker}-npl`}>
            NPL Ratio override (%)
          </label>
          <input
            id={`${ticker}-npl`}
            type="number"
            step="0.01"
            value={displayed.npl}
            onChange={(e) => update("npl", e.target.value)}
            placeholder={autoNpl != null ? `auto: ${fmtPct(autoNpl, 1)}` : "Not available"}
            className="w-full rounded-md border border-border-input bg-surface-2 px-2 py-1.5 font-mono text-sm text-text-primary focus:border-brand focus:outline-none"
          />
          <input
            type="text"
            value={displayed.nplAsOf}
            onChange={(e) => update("nplAsOf", e.target.value)}
            placeholder="As of (leave blank to keep auto)"
            className="w-full rounded-md border border-border-input bg-surface-2 px-2 py-1.5 text-xs text-text-secondary focus:border-brand focus:outline-none"
          />
          {autoNpl != null && (
            <p className="text-xs text-text-tertiary">
              Auto-computed: {fmtPct(autoNpl, 1)} (as of {step5.npl_as_of}) — editable above.
            </p>
          )}
        </div>
      </div>

      {dirty && (
        <div className="space-y-3 rounded-md border border-warn/40 bg-warn/10 p-4">
          <p className="text-sm text-warn">
            Save these CET1/NPL values? This recomputes Debt and Overall Assessment for {ticker}.
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleConfirm}
              disabled={saving}
              className="rounded-md border border-warn/60 bg-warn/15 px-4 py-1.5 text-sm font-medium text-warn transition-colors hover:border-warn disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Saving…" : "Confirm"}
            </button>
            <button
              type="button"
              onClick={() => setPending(null)}
              disabled={saving}
              className="rounded-md border border-border-input bg-surface-2 px-4 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
          {saveError && <p className="text-sm text-negative">{saveError}</p>}
        </div>
      )}
    </div>
  );
}
