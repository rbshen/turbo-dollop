"use client";

import { useState } from "react";
import { mutate } from "swr";

import { Button } from "@/components/ui/button";
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
        <span className="text-xs text-text-tertiary">
          {lastSummary.processed} processed
          {lastSummary.failed > 0 ? `, ${lastSummary.failed} failed` : ""} in {lastSummary.duration_seconds.toFixed(1)}s
        </span>
      )}
      <Button variant="outline" size="sm" onClick={handleClick} disabled={status === "loading"}>
        {LABELS[status]}
      </Button>
    </div>
  );
}
