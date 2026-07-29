"use client";

import { useState } from "react";

import { deleteWatchlist, useWatchlists } from "@/lib/hooks/useWatchlists";

type RowState = "idle" | "confirming" | "deleting" | "error";

export function WatchlistSettingsForm() {
  const { data, error, isLoading } = useWatchlists();
  const [rowStates, setRowStates] = useState<Record<number, RowState>>({});

  function stateFor(id: number): RowState {
    return rowStates[id] ?? "idle";
  }

  function setState(id: number, state: RowState) {
    setRowStates((prev) => ({ ...prev, [id]: state }));
  }

  async function handleDelete(id: number) {
    setState(id, "deleting");
    try {
      await deleteWatchlist(id);
    } catch {
      setState(id, "error");
      setTimeout(() => setState(id, "idle"), 3000);
    }
  }

  if (error) {
    return <p className="text-sm text-red-400">Couldn&apos;t load Watchlists — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>;
  }

  return (
    <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Watchlists</h2>

      {data.length === 0 ? (
        <p className="text-xs text-zinc-600">No watchlists yet.</p>
      ) : (
        <div className="space-y-1.5">
          {data.map((w) => {
            const state = stateFor(w.id);
            return (
              <div key={w.id} className="flex items-center justify-between gap-2 rounded px-2 py-1.5 text-sm text-zinc-300">
                <span className="truncate">
                  {w.name} <span className="text-xs text-zinc-600">({w.tickers.length})</span>{" "}
                  <span className="text-xs text-zinc-600">— Created {new Date(w.created_at).toLocaleString()}</span>
                </span>

                {state === "confirming" ? (
                  <div className="flex shrink-0 items-center gap-1.5 text-xs">
                    <span className="text-amber-400">Delete &quot;{w.name}&quot;?</span>
                    <button
                      type="button"
                      onClick={() => handleDelete(w.id)}
                      className="rounded-md border border-amber-800/60 bg-zinc-900 px-2 py-1 text-amber-300 hover:border-amber-600"
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => setState(w.id, "idle")}
                      className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-500 hover:border-zinc-500 hover:text-zinc-300"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setState(w.id, "confirming")}
                    disabled={state === "deleting"}
                    className={`shrink-0 text-xs disabled:opacity-50 ${state === "error" ? "text-red-400" : "text-zinc-600 hover:text-red-400"}`}
                  >
                    {state === "deleting" ? "Deleting…" : state === "error" ? "Failed — retry" : "Delete"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
