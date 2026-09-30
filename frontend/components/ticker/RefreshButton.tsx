"use client";

import { useState } from "react";
import { mutate } from "swr";
import { Check } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api/client";
import type { RefreshResult } from "@/lib/api/types";

interface Props {
  ticker: string;
}

type Status = "idle" | "loading" | "success" | "error";

const LABELS: Record<Status, string> = {
  idle: "Refresh data",
  loading: "Refreshing…",
  success: "Refreshed",
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
    <Button variant="outline" size="sm" onClick={handleClick} disabled={status === "loading"}>
      {status === "success" && <Check size={12} weight="bold" aria-hidden="true" />}
      {LABELS[status]}
    </Button>
  );
}
