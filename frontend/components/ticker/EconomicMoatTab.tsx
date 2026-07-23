"use client";

import { useState } from "react";
import { mutate } from "swr";

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
    return <p className="py-6 text-sm text-red-400">Couldn&apos;t load Economic Moat — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="py-6 text-sm text-zinc-600 animate-pulse">Loading…</p>;
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

  return (
    <div className="space-y-6 py-6">
      <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Economic Moat</h2>
          <p className="mt-1 text-xs text-zinc-600">
            A manually-set classification, not computed from data. Once set, Steps 1/2/4/5 combined occupy 69% of
            Overall Assessment and Moat occupies the other 31% — see the Overall Assessment card for how this ticker
            is currently blended.
          </p>
        </div>

        <p className="text-sm text-zinc-300">
          Current state:{" "}
          <span className="font-semibold text-zinc-100">{data.moat ? MOAT_LABELS[data.moat] : "Not set"}</span>
        </p>

        {pending ? (
          <div className="space-y-3 rounded-md border border-amber-800/40 bg-amber-950/20 p-4">
            <p className="text-sm text-amber-200">
              Set Economic Moat to <span className="font-semibold">{MOAT_LABELS[pending]}</span>? This changes how
              Overall Assessment is scored for {ticker}.
            </p>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleConfirm}
                disabled={saving}
                className="rounded-md border border-amber-700 bg-amber-900/40 px-4 py-1.5 text-sm font-medium text-amber-200 transition-colors hover:border-amber-500 hover:bg-amber-900/60 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? "Saving…" : "Confirm"}
              </button>
              <button
                type="button"
                onClick={() => setPending(null)}
                disabled={saving}
                className="rounded-md border border-zinc-700 bg-zinc-900 px-4 py-1.5 text-sm font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
            {saveError && <p className="text-sm text-red-400">{saveError}</p>}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {MOAT_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setPending(option)}
                disabled={data.moat === option}
                className="rounded-md border border-zinc-700 bg-zinc-900 p-4 text-left transition-colors hover:border-zinc-500 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:border-zinc-600 disabled:bg-zinc-800/60"
              >
                <p className="text-sm font-semibold text-zinc-100">
                  {MOAT_LABELS[option]}
                  {data.moat === option && <span className="ml-2 text-xs font-normal text-zinc-500">(current)</span>}
                </p>
                <p className="mt-1 text-xs text-zinc-500">{MOAT_DESCRIPTIONS[option]}</p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
