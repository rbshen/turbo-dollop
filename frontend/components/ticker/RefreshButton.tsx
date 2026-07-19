"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPost } from "@/lib/api/client";
import type { RefreshResult } from "@/lib/api/types";

interface Props {
  ticker: string;
}

type Status = "idle" | "loading" | "success" | "error";

const LABELS: Record<Status, string> = {
  idle: "Refresh data",
  loading: "Refreshing…",
  success: "Refreshed ✓",
  error: "Refresh failed",
};

export function RefreshButton({ ticker }: Props) {
  const [status, setStatus] = useState<Status>("idle");

  async function handleClick() {
    setStatus("loading");
    try {
      await apiPost<RefreshResult>(`/tickers/${ticker}/refresh`, undefined);
      // Every hook on this page keys off "/tickers/{ticker}/..." -- one
      // filtered mutate revalidates the header, Overall Assessment, and
      // all 4 step cards together, so the user sees fresh numbers without
      // a manual page reload.
      await mutate((key) => typeof key === "string" && key.startsWith(`/tickers/${ticker}`));
      setStatus("success");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={status === "loading"}
      className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {LABELS[status]}
    </button>
  );
}
