"use client";

import { useEffect, useRef, useState } from "react";

import { addTickerToWatchlist, bulkAddTickersToWatchlist, createWatchlist, useWatchlists } from "@/lib/hooks/useWatchlists";

interface Props {
  tickers: string[];
  label?: string;
}

type Panel = "idle" | "picking";
type NewListStep = "idle" | "naming";
// Same shape as SavedFiltersBar/MoatSettingsForm's own save-status pattern.
type Status = "idle" | "saving" | "saved" | "error";

const ADD_STATUS_LABELS: Record<Status, string> = {
  idle: "Add",
  saving: "Adding…",
  saved: "Added ✓",
  error: "Failed",
};

const CREATE_STATUS_LABELS: Record<Status, string> = {
  idle: "Create & Add",
  saving: "Adding…",
  saved: "Added ✓",
  error: "Failed",
};

export function AddToWatchlistButton({ tickers, label = "+ Watchlist" }: Props) {
  const { data: watchlists } = useWatchlists();
  const isBulk = tickers.length > 1;
  const [panel, setPanel] = useState<Panel>("idle");
  const [newListStep, setNewListStep] = useState<NewListStep>("idle");
  const [newListName, setNewListName] = useState("");
  const [newListStatus, setNewListStatus] = useState<Status>("idle");
  const [newListError, setNewListError] = useState<string | null>(null);
  const [addStatus, setAddStatus] = useState<Record<number, Status>>({});
  // Bulk-only: which watchlist's "Add" click is pending an Okay/Cancel
  // confirmation -- a stray click here would dump up to 50 tickers into
  // the wrong list, unlike the single-ticker path where that risk doesn't
  // exist, so only bulk gets this extra step.
  const [confirmTarget, setConfirmTarget] = useState<number | null>(null);
  const [bulkResult, setBulkResult] = useState<Record<number, string>>({});
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setPanel("idle");
        setNewListStep("idle");
        setConfirmTarget(null);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function openNewList() {
    setNewListName("");
    setNewListError(null);
    setNewListStatus("idle");
    setNewListStep("naming");
  }

  function cancelNewList() {
    setNewListStep("idle");
    setNewListName("");
    setNewListError(null);
  }

  async function handleAddToExisting(watchlistId: number) {
    setAddStatus((prev) => ({ ...prev, [watchlistId]: "saving" }));
    try {
      await addTickerToWatchlist(watchlistId, tickers[0]);
      setAddStatus((prev) => ({ ...prev, [watchlistId]: "saved" }));
    } catch {
      setAddStatus((prev) => ({ ...prev, [watchlistId]: "error" }));
      setTimeout(() => setAddStatus((prev) => ({ ...prev, [watchlistId]: "idle" })), 3000);
    }
  }

  async function handleBulkAdd(watchlistId: number) {
    setConfirmTarget(null);
    setAddStatus((prev) => ({ ...prev, [watchlistId]: "saving" }));
    try {
      const result = await bulkAddTickersToWatchlist(watchlistId, tickers);
      setBulkResult((prev) => ({
        ...prev,
        [watchlistId]:
          result.already_present > 0
            ? `Added ${result.added} (${result.already_present} already in this watchlist)`
            : `Added ${result.added}`,
      }));
      setAddStatus((prev) => ({ ...prev, [watchlistId]: "saved" }));
      setTimeout(() => {
        setAddStatus((prev) => ({ ...prev, [watchlistId]: "idle" }));
        setBulkResult((prev) => {
          const next = { ...prev };
          delete next[watchlistId];
          return next;
        });
      }, 4000);
    } catch {
      setAddStatus((prev) => ({ ...prev, [watchlistId]: "error" }));
      setTimeout(() => setAddStatus((prev) => ({ ...prev, [watchlistId]: "idle" })), 3000);
    }
  }

  async function handleCreateAndAdd() {
    const trimmedName = newListName.trim();
    if (!trimmedName) return;
    setNewListStatus("saving");
    setNewListError(null);
    try {
      const watchlist = await createWatchlist(trimmedName);
      if (isBulk) {
        await bulkAddTickersToWatchlist(watchlist.id, tickers);
      } else {
        await addTickerToWatchlist(watchlist.id, tickers[0]);
      }
      setNewListStatus("saved");
      setNewListStep("idle");
      setNewListName("");
      setTimeout(() => setNewListStatus("idle"), 3000);
    } catch (e) {
      setNewListStatus("error");
      setNewListError(e instanceof Error && e.message.includes("409") ? `"${trimmedName}" already exists` : "Couldn't create watchlist");
    }
  }

  return (
    <div ref={panelRef} className="relative">
      <button
        type="button"
        onClick={() => setPanel((p) => (p === "idle" ? "picking" : "idle"))}
        className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
      >
        {label}
      </button>

      {panel === "picking" && (
        <div className="absolute right-0 z-20 mt-1 w-64 rounded-md border border-zinc-700 bg-zinc-900 p-1 shadow-lg">
          {!watchlists || watchlists.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-zinc-600">No watchlists yet</p>
          ) : (
            <div className="max-h-56 overflow-y-auto">
              {watchlists.map((w) => {
                const status = addStatus[w.id] ?? "idle";

                if (isBulk && confirmTarget === w.id) {
                  return (
                    <div key={w.id} className="space-y-1 rounded px-2 py-1.5 text-xs">
                      <p className="text-amber-400">
                        Add {tickers.length} tickers to &quot;{w.name}&quot;?
                      </p>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleBulkAdd(w.id)}
                          className="rounded border border-amber-800/60 px-1.5 py-0.5 text-amber-300 hover:border-amber-600"
                        >
                          Okay
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmTarget(null)}
                          className="rounded border border-zinc-700 px-1.5 py-0.5 text-zinc-500 hover:border-zinc-500 hover:text-zinc-300"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  );
                }

                const alreadyAdded = !isBulk && w.tickers.some((t) => t.ticker === tickers[0].toUpperCase());
                const resultMessage = isBulk ? bulkResult[w.id] : undefined;

                return (
                  <div key={w.id} className="flex items-center justify-between gap-2 rounded px-2 py-1.5 text-xs text-zinc-300">
                    <span className="truncate">{w.name}</span>
                    {alreadyAdded ? (
                      <span className="shrink-0 text-zinc-600">Already added</span>
                    ) : status === "saved" && resultMessage ? (
                      <span className="shrink-0 text-emerald-400">{resultMessage}</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => (isBulk ? setConfirmTarget(w.id) : handleAddToExisting(w.id))}
                        disabled={status === "saving" || status === "saved"}
                        className="shrink-0 rounded border border-zinc-700 px-1.5 py-0.5 text-zinc-400 hover:border-zinc-500 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {ADD_STATUS_LABELS[status]}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="mt-1 border-t border-zinc-800 pt-1">
            {newListStep === "idle" ? (
              <button
                type="button"
                onClick={openNewList}
                className="w-full rounded px-2 py-1.5 text-left text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
              >
                + New watchlist
              </button>
            ) : (
              <div className="space-y-1 px-2 py-1.5">
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    autoFocus
                    placeholder="Watchlist name"
                    value={newListName}
                    onChange={(e) => setNewListName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleCreateAndAdd();
                      if (e.key === "Escape") cancelNewList();
                    }}
                    className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
                  />
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={handleCreateAndAdd}
                    disabled={!newListName.trim() || newListStatus === "saving"}
                    className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {CREATE_STATUS_LABELS[newListStatus]}
                  </button>
                  <button
                    type="button"
                    onClick={cancelNewList}
                    className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-500 hover:border-zinc-500 hover:text-zinc-300"
                  >
                    Cancel
                  </button>
                </div>
                {newListError && <p className="text-xs text-red-400">{newListError}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
