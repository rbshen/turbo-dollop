"use client";

import { useState } from "react";
import { Trash } from "@phosphor-icons/react";

import { AdminOnly } from "@/components/auth/AdminOnly";
import { Button } from "@/components/ui/button";
import { removeWarrenWatchRow } from "@/lib/hooks/useWarrenWatch";
import { cn } from "@/lib/utils";

type Status = "idle" | "confirming" | "removing" | "error";

interface Props {
  ticker: string;
  // Test seam: swaps the request so a test can never reach the backend.
  remove?: (ticker: string) => Promise<void>;
}

// Admin only: a viewer sees nothing. Same inline confirm-before-delete as WatchlistDeleteButton (trash icon, then Confirm / Cancel);
// the row is only hidden (a soft remove), and a newer Warren arrow on a later candle puts the ticker back.
export function WarrenWatchRemoveButton({ ticker, remove = removeWarrenWatchRow }: Props) {
  const [status, setStatus] = useState<Status>("idle");

  async function handleRemove() {
    setStatus("removing");
    try {
      await remove(ticker);
      setStatus("idle"); // the row normally disappears with the refreshed table
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <AdminOnly>
      {status === "confirming" || status === "removing" ? (
        <div className="flex shrink-0 items-center justify-end gap-2 text-xs">
          <span className="text-negative">Remove {ticker}?</span>
          <Button variant="danger" onClick={handleRemove} disabled={status === "removing"}>
            Confirm
          </Button>
          <Button variant="outline" onClick={() => setStatus("idle")} disabled={status === "removing"}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button
          variant={status === "error" ? "danger" : "ghost"}
          size="icon-sm"
          onClick={() => setStatus("confirming")}
          aria-label={`Remove ${ticker}`}
          title={status === "error" ? "Failed to remove — retry" : "Remove from this table"}
          className={cn("shrink-0", status !== "error" && "text-text-tertiary hover:text-negative")}
        >
          <Trash size={16} aria-hidden="true" />
        </Button>
      )}
    </AdminOnly>
  );
}
