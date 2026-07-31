"use client";

import { useState } from "react";
import { mutate } from "swr";

import { SegmentedControl } from "@/components/shared/SegmentedControl";
import { apiPut } from "@/lib/api/client";
import type { TickerMoatOut } from "@/lib/api/types";
import { useTickerMoat } from "@/lib/hooks/useTickerMoat";
import { MOAT_LABELS, type MoatValue } from "@/lib/overallScore";

interface Props {
  ticker: string;
}

const MOAT_OPTIONS: MoatValue[] = ["no_moat", "narrow_moat", "wide_moat"];

const MOAT_DESCRIPTIONS: Record<MoatValue, string> = {
  no_moat: "No durable competitive advantage protecting this business from competitors.",
  narrow_moat: "Some durable advantage, but not strong or broad enough to fend off competition indefinitely.",
  wide_moat: "A strong, durable competitive advantage expected to persist for a decade or more.",
};

export function EconomicMoatTab({ ticker }: Props) {
  const { data, error, isLoading } = useTickerMoat(ticker);

  if (error) {
    return <p className="py-6 text-sm text-negative">Couldn&apos;t load Economic Moat — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="py-6 text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  return <MoatControls key={data.updated_at ?? "unset"} ticker={ticker} data={data} />;
}

function MoatControls({ ticker, data }: { ticker: string; data: TickerMoatOut }) {
  const [pending, setPending] = useState<MoatValue | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function handleConfirm() {
    if (!pending) return;
    setSaving(true);
    setSaveError(null);
    try {
      await apiPut<TickerMoatOut>(`/tickers/${ticker}/moat`, { moat: pending });
      // Every hook on this page keys off "/tickers/{ticker}/..." -- refreshes
      // this tab, the header pill, and Overall Assessment together. The
      // Screener's own row was already updated server-side (see
      // main.py::update_ticker_moat), so revalidate its list too, in case
      // the user navigates there next.
      await mutate((key) => typeof key === "string" && key.startsWith(`/tickers/${ticker}`));
      await mutate("/screener");
      setPending(null);
    } catch {
      setSaveError("Failed to save — please try again.");
    } finally {
      setSaving(false);
    }
  }

  // Segmented control shows the pending selection immediately (a live
  // preview), but nothing actually saves until Confirm -- this app changes
  // Overall Assessment's scoring on save, unlike the design handoff's own
  // prototype which has no such consequence to guard against.
  const displayed = pending ?? data.moat;

  return (
    <div className="space-y-6 py-6">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Economic Moat</h2>
        <p className="mt-1 text-sm text-text-secondary">
          A manually-set classification, not computed from data. Once set, Financials / Growth Rate / Profitability /
          Debt combined occupy 69% of Overall Assessment and Moat occupies the other 31% — see the Overall Assessment
          card for how this ticker is currently blended.
        </p>
      </div>

      <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-widest text-text-tertiary">Current Rating</p>
          <SegmentedControl
            value={displayed ?? "no_moat"}
            onChange={(next) => {
              if (next !== data.moat) setPending(next);
            }}
            options={MOAT_OPTIONS.map((option) => ({ value: option, label: MOAT_LABELS[option] }))}
          />
          <p className="text-sm text-text-secondary">
            {displayed ? MOAT_DESCRIPTIONS[displayed] : "Not set — pick a rating above."}
          </p>
        </div>

        {pending && (
          <div className="space-y-3 rounded-md border border-warn/40 bg-warn/10 p-4">
            <p className="text-sm text-warn">
              Set Economic Moat to <span className="font-semibold">{MOAT_LABELS[pending]}</span>? This changes how
              Overall Assessment is scored for {ticker}.
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
    </div>
  );
}
