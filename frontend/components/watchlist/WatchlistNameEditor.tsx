"use client";

import { useId, useState } from "react";
import { PencilSimple } from "@phosphor-icons/react";

import { errorDetail } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { FIELD_ERROR_CLASS } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { updateWatchlist } from "@/lib/hooks/useWatchlists";
import { WATCHLIST_NAME_MAX_LENGTH } from "@/lib/watchlistName";
import type { WatchlistOut } from "@/lib/api/types";

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
  const errorId = useId();

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
    if (trimmed.length > WATCHLIST_NAME_MAX_LENGTH) {
      setError(`Name must be ${WATCHLIST_NAME_MAX_LENGTH} characters or fewer`);
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
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={startEditing}
          aria-label={`Rename ${watchlist.name}`}
          title="Rename watchlist"
          className="text-text-tertiary"
        >
          <PencilSimple size={16} aria-hidden="true" />
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="text"
          size="wide"
          autoFocus
          value={value}
          maxLength={WATCHLIST_NAME_MAX_LENGTH}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") cancel();
          }}
          disabled={status === "saving"}
          invalid={error != null}
          aria-label="Watchlist name"
          aria-describedby={error ? errorId : undefined}
        />
        <Button variant="outline" onClick={save} disabled={status === "saving"}>
          {status === "saving" ? "Saving…" : "Save"}
        </Button>
        <Button variant="outline" onClick={cancel} disabled={status === "saving"}>
          Cancel
        </Button>
      </div>
      {error && (
        <p id={errorId} role="alert" className={FIELD_ERROR_CLASS}>
          {error}
        </p>
      )}
    </div>
  );
}
