"use client";

import { useState } from "react";
import { Trash } from "@phosphor-icons/react";

import { deleteWatchlist } from "@/lib/hooks/useWatchlists";
import type { WatchlistOut } from "@/lib/api/types";

type Status = "idle" | "confirming" | "deleting" | "error";

interface Props {
  watchlist: WatchlistOut;
  // Called after a successful delete so the page can move off the
  // now-gone tab (e.g. reset to the default/most-recently-created
  // watchlist) -- the list-of-watchlists Settings view this control was
  // relocated from never needed an equivalent, since it never singled out
  // one watchlist as "active."
  onDeleted: () => void;
}

// Relocated from the old Settings > Watchlists list (WatchlistSettingsForm)
// to sit next to the rename control on the Watchlist page itself -- same
// idle/confirming/deleting/error state machine and inline
// confirm-before-delete UX, just re-styled to match WatchlistNameEditor's
// design tokens instead of that section's now-removed hardcoded zinc/amber
// classes.
export function WatchlistDeleteButton({ watchlist, onDeleted }: Props) {
  const [status, setStatus] = useState<Status>("idle");

  async function handleDelete() {
    setStatus("deleting");
    try {
      await deleteWatchlist(watchlist.id);
      onDeleted();
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  if (status === "confirming") {
    return (
      <div className="flex shrink-0 items-center gap-1.5 text-xs">
        <span className="text-negative">Delete &quot;{watchlist.name}&quot;?</span>
        <button
          type="button"
          onClick={handleDelete}
          className="rounded-md border border-negative/60 bg-page px-2 py-1 text-negative hover:border-negative"
        >
          Confirm
        </button>
        <button
          type="button"
          onClick={() => setStatus("idle")}
          className="rounded-md border border-border-input px-2 py-1 text-text-tertiary hover:border-brand hover:text-text-secondary"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setStatus("confirming")}
      disabled={status === "deleting"}
      aria-label={`Delete ${watchlist.name}`}
      title={status === "error" ? "Failed to delete — retry" : "Delete watchlist"}
      className={`shrink-0 transition-colors disabled:opacity-50 ${
        status === "error" ? "text-negative" : "text-text-tertiary hover:text-negative"
      }`}
    >
      <Trash size={12} />
    </button>
  );
}
