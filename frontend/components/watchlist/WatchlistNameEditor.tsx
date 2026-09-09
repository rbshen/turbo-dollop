"use client";

import { useState } from "react";
import { PencilSimple } from "@phosphor-icons/react";

import { errorDetail } from "@/lib/api/client";
import { updateWatchlist } from "@/lib/hooks/useWatchlists";
import type { WatchlistOut } from "@/lib/api/types";

// Mirrors the backend's WatchlistName constraint (core/schemas.py) --
// kept in sync manually since there's no shared schema source between the
// two, same as every other client-side mirror of a backend constraint in
// this app (e.g. WATCHLIST_CAPACITY has no frontend-side equivalent either,
// it just surfaces the backend's own rejection message instead).
const MAX_NAME_LENGTH = 100;

type Status = "idle" | "editing" | "saving";

interface Props {
  watchlist: WatchlistOut;
}

// Inline pencil-icon rename control for the Watchlist page's active-tab
// name/ticker-count subtitle. Same status-machine idiom as
// AddToWatchlistButton's "+ New watchlist" naming flow -- a plain text
// display swaps for an input + Save/Cancel in place, no modal.
export function WatchlistNameEditor({ watchlist }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const [value, setValue] = useState(watchlist.name);
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setValue(watchlist.name);
    setError(null);
    setStatus("editing");
  }

  function cancel() {
    setStatus("idle");
    setValue(watchlist.name);
    setError(null);
  }

  async function save() {
    const trimmed = value.trim();
    if (!trimmed) {
      setError("Name can't be empty");
      return;
    }
    if (trimmed.length > MAX_NAME_LENGTH) {
      setError(`Name must be ${MAX_NAME_LENGTH} characters or fewer`);
      return;
    }
    if (trimmed === watchlist.name) {
      setStatus("idle");
      return;
    }
    setStatus("saving");
    setError(null);
    try {
      await updateWatchlist(watchlist.id, { name: trimmed });
      setStatus("idle");
    } catch (e) {
      setStatus("editing");
      if (e instanceof Error && e.message.includes("409")) {
        setError(`"${trimmed}" already exists`);
      } else {
        setError(errorDetail(e) ?? "Couldn't rename watchlist");
      }
    }
  }

  if (status === "idle") {
    return (
      <div className="flex items-center gap-1.5">
        <p className="text-xs text-text-tertiary">
          {watchlist.name} · {watchlist.tickers.length} ticker{watchlist.tickers.length === 1 ? "" : "s"}
        </p>
        <button
          type="button"
          onClick={startEditing}
          aria-label={`Rename ${watchlist.name}`}
          title="Rename watchlist"
          className="text-text-tertiary transition-colors hover:text-text-primary"
        >
          <PencilSimple size={12} />
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          autoFocus
          value={value}
          maxLength={MAX_NAME_LENGTH}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") cancel();
          }}
          disabled={status === "saving"}
          className="w-48 rounded-md border border-border-input bg-page px-2 py-1 text-xs text-text-primary focus:border-brand focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          onClick={save}
          disabled={status === "saving"}
          className="rounded-md border border-border-input px-2 py-1 text-xs text-text-secondary hover:border-brand hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {status === "saving" ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={cancel}
          disabled={status === "saving"}
          className="rounded-md border border-border-input px-2 py-1 text-xs text-text-tertiary hover:border-brand hover:text-text-secondary disabled:cursor-not-allowed disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
      {error && <p className="text-xs text-negative">{error}</p>}
    </div>
  );
}
