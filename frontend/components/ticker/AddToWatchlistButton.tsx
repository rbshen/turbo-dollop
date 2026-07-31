"use client";

import { useEffect, useRef, useState } from "react";

import { addTickerToWatchlist, bulkAddTickersToWatchlist, createWatchlist, useWatchlists } from "@/lib/hooks/useWatchlists";

interface Props {
  tickers: string[];
  label?: string;
  // Overrides the bulk confirmation's default "{n} tickers" wording, e.g.
  // "all 37 filtered tickers" for the Screener's whole-result-set case.
  confirmDescription?: string;
  disabled?: boolean;
}

// Extracts the backend's own detail text appended by lib/api/client.ts's
// request() (" - <detail>" suffix) so a capacity/validation rejection shows
// its real message instead of a bare "Failed" label.
function errorDetail(e: unknown): string | undefined {
  if (!(e instanceof Error)) return undefined;
  const idx = e.message.indexOf(" - ");
  return idx === -1 ? undefined : e.message.slice(idx + 3);
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

export function AddToWatchlistButton({ tickers, label = "+ Watchlist", confirmDescription, disabled }: Props) {
  const { data: watchlists } = useWatchlists();
  const isBulk = tickers.length > 1;
  const [panel, setPanel] = useState<Panel>("idle");
  const [newListStep, setNewListStep] = useState<NewListStep>("idle");
  const [newListName, setNewListName] = useState("");
  const [newListStatus, setNewListStatus] = useState<Status>("idle");
  const [newListError, setNewListError] = useState<string | null>(null);
  const [addStatus, setAddStatus] = useState<Record<number, Status>>({});
  // Populated alongside an "error" addStatus with the backend's own detail
  // text (e.g. a capacity-cap rejection's exact counts) when available.
  const [addErrorMessage, setAddErrorMessage] = useState<Record<number, string>>({});
  // Bulk-only: which watchlist's "Add" click is pending an Okay/Cancel
  // confirmation -- a stray click here would dump the whole result set into
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
    } catch (e) {
      setAddStatus((prev) => ({ ...prev, [watchlistId]: "error" }));
      setAddErrorMessage((prev) => ({ ...prev, [watchlistId]: errorDetail(e) ?? "Something went wrong" }));
      setTimeout(() => setAddStatus((prev) => ({ ...prev, [watchlistId]: "idle" })), 4000);
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
    } catch (e) {
      setAddStatus((prev) => ({ ...prev, [watchlistId]: "error" }));
      setAddErrorMessage((prev) => ({ ...prev, [watchlistId]: errorDetail(e) ?? "Something went wrong" }));
      setTimeout(() => setAddStatus((prev) => ({ ...prev, [watchlistId]: "idle" })), 4000);
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
      if (e instanceof Error && e.message.includes("409")) {
        setNewListError(`"${trimmedName}" already exists`);
      } else {
        setNewListError(errorDetail(e) ?? "Couldn't create watchlist");
      }
    }
  }

  return (
    <div ref={panelRef} className="relative">
      <button
        type="button"
        onClick={() => setPanel((p) => (p === "idle" ? "picking" : "idle"))}
        disabled={disabled}
        className="rounded-full bg-brand px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        {label}
      </button>

      {panel === "picking" && (
        <div className="absolute right-0 z-20 mt-1 w-64 rounded-md border border-border-input bg-surface p-1 shadow-lg">
          {!watchlists || watchlists.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-text-tertiary">No watchlists yet</p>
          ) : (
            <div className="max-h-56 overflow-y-auto">
              {watchlists.map((w) => {
                const status = addStatus[w.id] ?? "idle";

                if (isBulk && confirmTarget === w.id) {
                  return (
                    <div key={w.id} className="space-y-1 rounded px-2 py-1.5 text-xs">
                      <p className="text-warn">
                        Add {confirmDescription ?? `${tickers.length} tickers`} to &quot;{w.name}&quot;?
                      </p>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleBulkAdd(w.id)}
                          className="rounded border border-warn/50 px-1.5 py-0.5 text-warn hover:border-warn"
                        >
                          Okay
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmTarget(null)}
                          className="rounded border border-border-input px-1.5 py-0.5 text-text-tertiary hover:border-brand hover:text-text-secondary"
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
                  <div key={w.id} className="space-y-0.5 rounded px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2 text-xs text-text-secondary">
                      <span className="truncate">{w.name}</span>
                      {alreadyAdded ? (
                        <span className="shrink-0 text-text-tertiary">Already added</span>
                      ) : status === "saved" && resultMessage ? (
                        <span className="shrink-0 text-positive">{resultMessage}</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => (isBulk ? setConfirmTarget(w.id) : handleAddToExisting(w.id))}
                          disabled={status === "saving" || status === "saved"}
                          className="shrink-0 rounded border border-border-input px-1.5 py-0.5 text-text-secondary hover:border-brand hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {ADD_STATUS_LABELS[status]}
                        </button>
                      )}
                    </div>
                    {status === "error" && addErrorMessage[w.id] && (
                      <p className="text-xs text-negative">{addErrorMessage[w.id]}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="mt-1 border-t border-border-subtle pt-1">
            {newListStep === "idle" ? (
              <button
                type="button"
                onClick={openNewList}
                className="w-full rounded px-2 py-1.5 text-left text-xs text-text-secondary hover:bg-surface-2 hover:text-text-primary"
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
                    className="w-full rounded-md border border-border-input bg-page px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary focus:border-brand focus:outline-none"
                  />
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={handleCreateAndAdd}
                    disabled={!newListName.trim() || newListStatus === "saving"}
                    className="rounded-md border border-border-input bg-surface px-2 py-1 text-xs text-text-secondary hover:border-brand hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {CREATE_STATUS_LABELS[newListStatus]}
                  </button>
                  <button
                    type="button"
                    onClick={cancelNewList}
                    className="rounded-md border border-border-input bg-surface px-2 py-1 text-xs text-text-tertiary hover:border-brand hover:text-text-secondary"
                  >
                    Cancel
                  </button>
                </div>
                {newListError && <p className="text-xs text-negative">{newListError}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
