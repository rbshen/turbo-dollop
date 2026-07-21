"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPost } from "@/lib/api/client";
import type { RecomputeSummary } from "@/lib/api/types";

type Status = "idle" | "loading" | "success" | "error";

const LABELS: Record<Status, string> = {
  idle: "Recompute all scores",
  loading: "Recomputing…",
  success: "Recomputed ✓",
  error: "Recompute failed",
};

export function RecomputeButton() {
  const [status, setStatus] = useState<Status>("idle");
  const [lastSummary, setLastSummary] = useState<RecomputeSummary | null>(null);

  async function handleClick() {
    setStatus("loading");
    try {
      const summary = await apiPost<RecomputeSummary>("/screener/recompute", undefined);
      setLastSummary(summary);
      await mutate((key) => typeof key === "string" && key.startsWith("/screener"));
      setStatus("success");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 4000);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {status === "success" && lastSummary && (
        <span className="text-xs text-zinc-500">
          {lastSummary.processed} processed
          {lastSummary.failed > 0 ? `, ${lastSummary.failed} failed` : ""} in {lastSummary.duration_seconds.toFixed(1)}s
        </span>
      )}
      <button
        type="button"
        onClick={handleClick}
        disabled={status === "loading"}
        className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {LABELS[status]}
      </button>
    </div>
  );
}
