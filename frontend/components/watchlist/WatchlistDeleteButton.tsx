"use client";

import { useState } from "react";
import { Trash } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { deleteWatchlist } from "@/lib/hooks/useWatchlists";
import { cn } from "@/lib/utils";
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
  // Styleguide seams (the page passes neither): `remove` swaps the request so
  // a mock can never reach the backend, `defaultStatus` starts the control in
  // a given state so each can be drawn at once.
  remove?: (id: number) => Promise<void>;
  defaultStatus?: "idle" | "confirming" | "error";
}

// Relocated from the old Settings > Watchlists list (WatchlistSettingsForm)
// to sit next to the rename control on the Watchlist page itself -- same
// idle/confirming/deleting/error state machine and inline
// confirm-before-delete UX, just re-styled to match WatchlistNameEditor's
// design tokens instead of that section's now-removed hardcoded zinc/amber
// classes. Session 11: Confirm is the danger Button, Cancel an outline
// Button, and the trash trigger an icon Button (ghost; danger once a delete
// has failed). There has never been a window.confirm here -- the confirm is
// the inline state below.
export function WatchlistDeleteButton({ watchlist, onDeleted, remove = deleteWatchlist, defaultStatus = "idle" }: Props) {
  const [status, setStatus] = useState<Status>(defaultStatus);

  async function handleDelete() {
    setStatus("deleting");
    try {
      await remove(watchlist.id);
      onDeleted();
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  if (status === "confirming") {
    return (
      <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs">
        <span className="text-negative">Delete &quot;{watchlist.name}&quot;?</span>
        <Button variant="danger" onClick={handleDelete}>
          Confirm
        </Button>
        <Button variant="outline" onClick={() => setStatus("idle")}>
          Cancel
        </Button>
      </div>
    );
  }

  return (
    <Button
      variant={status === "error" ? "danger" : "ghost"}
      size="icon-sm"
      onClick={() => setStatus("confirming")}
      disabled={status === "deleting"}
      aria-label={`Delete ${watchlist.name}`}
      title={status === "error" ? "Failed to delete — retry" : "Delete watchlist"}
      className={cn("shrink-0", status !== "error" && "text-text-tertiary hover:text-negative")}
    >
      <Trash size={16} aria-hidden="true" />
    </Button>
  );
}
