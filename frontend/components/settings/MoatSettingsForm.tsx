"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { MoatScoreConfigOut } from "@/lib/api/types";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function MoatSettingsForm() {
  const { data, error, isLoading } = useMoatConfig();

  if (error) {
    return <p className="text-sm text-red-400">Couldn&apos;t load Economic Moat settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (which changes updated_at) remounts this
  // with fresh initial text -- same pattern as DiscountRateSettingsForm.
  return <MoatScoreForm key={data.updated_at} data={data} />;
}

function MoatScoreForm({ data }: { data: MoatScoreConfigOut }) {
  const [wideText, setWideText] = useState(String(data.wide_moat_score));
  const [narrowText, setNarrowText] = useState(String(data.narrow_moat_score));
  const [noMoatText, setNoMoatText] = useState(String(data.no_moat_score));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const wideMoatScore = parseFloat(wideText);
    const narrowMoatScore = parseFloat(narrowText);
    const noMoatScore = parseFloat(noMoatText);
    if (Number.isNaN(wideMoatScore) || Number.isNaN(narrowMoatScore) || Number.isNaN(noMoatScore)) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<MoatScoreConfigOut>("/config/moat", {
        wide_moat_score: wideMoatScore,
        narrow_moat_score: narrowMoatScore,
        no_moat_score: noMoatScore,
      });
      // Every mounted OverallAssessmentCard reads this same global SWR key
      // -- one revalidation reflows every open ticker's blended score
      // without a manual page reload.
      await mutate("/config/moat");
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
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Economic Moat Point Values</h2>
        <p className="mt-1 text-xs text-zinc-600">
          Point values (0-100 scale) each Economic Moat state contributes to Overall Assessment once a ticker has a
          moat set. Applied as: <span className="font-mono text-zinc-400">0.69 × Steps 1/2/4/5 blend + 0.31 × moat score</span>.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div>
          <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="wide-moat-score">
            Wide Moat
          </label>
          <input
            id="wide-moat-score"
            type="number"
            step="0.1"
            min="0"
            max="100"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
            value={wideText}
            onChange={(e) => setWideText(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="narrow-moat-score">
            Narrow Moat
          </label>
          <input
            id="narrow-moat-score"
            type="number"
            step="0.1"
            min="0"
            max="100"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
            value={narrowText}
            onChange={(e) => setNarrowText(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="no-moat-score">
            No Moat
          </label>
          <input
            id="no-moat-score"
            type="number"
            step="0.1"
            min="0"
            max="100"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
            value={noMoatText}
            onChange={(e) => setNoMoatText(e.target.value)}
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
