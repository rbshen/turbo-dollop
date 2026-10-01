"use client";

import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Check, Plus } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { FIELD_ERROR_CLASS } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { errorDetail } from "@/lib/api/client";
import {
  addTickerToWatchlist,
  bulkAddTickersToWatchlist,
  createWatchlist,
  removeTickerFromWatchlist,
  useWatchlists,
} from "@/lib/hooks/useWatchlists";
import { WATCHLIST_NAME_MAX_LENGTH } from "@/lib/watchlistName";

interface Props {
  tickers: string[];
  // Default: a Plus icon and "Watchlist" (the ticker header). A custom label
  // (the Screener's "Add to watchlist") is shown as plain text.
  label?: string;
  // Overrides the bulk confirmation's default "{n} tickers" wording, e.g.
  // "all 37 filtered tickers" for the Screener's whole-result-set case.
  confirmDescription?: string;
  disabled?: boolean;
}

type Panel = "idle" | "picking";
type NewListStep = "idle" | "naming";
// Same shape as SavedFiltersBar/MoatSettingsForm's own save-status pattern.
type Status = "idle" | "saving" | "saved" | "error";
// Remove has no "saved" terminal state to display -- once the DELETE
// resolves, useWatchlists.ts's own mutate(KEY) flips `alreadyAdded` to
// false and the row switches to the "Add" branch below on its own.
type RemoveStatus = "idle" | "removing" | "error";

// "saved" is drawn with a Check icon in front of the word (see StatusLabel).
const ADD_STATUS_LABELS: Record<Status, string> = {
  idle: "Add",
  saving: "Adding…",
  saved: "Added",
  error: "Failed",
};

const REMOVE_STATUS_LABELS: Record<RemoveStatus, string> = {
  idle: "Remove",
  removing: "Removing…",
  error: "Failed — retry",
};

const CREATE_STATUS_LABELS: Record<Status, string> = {
  idle: "Create and add",
  saving: "Adding…",
  saved: "Added",
  error: "Failed",
};

function StatusLabel({ status, labels }: { status: Status; labels: Record<Status, string> }) {
  return (
    <>
      {status === "saved" && <Check size={12} weight="bold" aria-hidden="true" />}
      {labels[status]}
    </>
  );
}

// Shared by the row buttons: outline at sm (32px), with a tone on hover or at rest.
const WARN_BUTTON_CLASS = "border-warn/50 text-warn hover:border-warn hover:text-warn";
const REMOVE_BUTTON_CLASS = "hover:border-negative hover:text-negative";

export function AddToWatchlistButton({ tickers, label, confirmDescription, disabled }: Props) {
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
  // Single-ticker-only mirror of confirmTarget above, for the "already
  // added" -> Remove confirmation (see the alreadyAdded branch below) --
  // kept separate since add and remove confirmation can never both be
  // showing for the same watchlist row at once.
  const [removeConfirmTarget, setRemoveConfirmTarget] = useState<number | null>(null);
  const [removeStatus, setRemoveStatus] = useState<Record<number, RemoveStatus>>({});
  const [removeErrorMessage, setRemoveErrorMessage] = useState<Record<number, string>>({});
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const newListTriggerRef = useRef<HTMLButtonElement>(null);
  // Set when the naming step is cancelled, so focus lands on the "New watchlist" button once it is back.
  const restoreNewListFocus = useRef(false);
  const panelId = useId();
  const newListErrorId = useId();

  const closePanel = useCallback(() => {
    setPanel("idle");
    setNewListStep("idle");
    setConfirmTarget(null);
    setRemoveConfirmTarget(null);
  }, []);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) closePanel();
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [closePanel]);

  // Escape anywhere in the open popover (the trigger included) closes it and
  // puts focus back on the trigger. The naming input handles its own Escape
  // (it only cancels the naming step) and stops it here.
  function onPopoverKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Escape" || panel !== "picking") return;
    closePanel();
    triggerRef.current?.focus();
  }

  function openNewList() {
    setNewListName("");
    setNewListError(null);
    setNewListStatus("idle");
    setNewListStep("naming");
  }

  useEffect(() => {
    if (newListStep === "idle" && restoreNewListFocus.current) {
      restoreNewListFocus.current = false;
      newListTriggerRef.current?.focus();
    }
  }, [newListStep]);

  function cancelNewList() {
    restoreNewListFocus.current = true;
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

  async function handleRemove(watchlistId: number) {
    setRemoveConfirmTarget(null);
    setRemoveStatus((prev) => ({ ...prev, [watchlistId]: "removing" }));
    try {
      await removeTickerFromWatchlist(watchlistId, tickers[0]);
      // No "removed" terminal state needed -- the mutate() inside
      // removeTickerFromWatchlist already flips alreadyAdded to false,
      // which switches this row to the "Add" branch on its own.
      setRemoveStatus((prev) => ({ ...prev, [watchlistId]: "idle" }));
    } catch (e) {
      setRemoveStatus((prev) => ({ ...prev, [watchlistId]: "error" }));
      setRemoveErrorMessage((prev) => ({ ...prev, [watchlistId]: errorDetail(e) ?? "Something went wrong" }));
      setTimeout(() => setRemoveStatus((prev) => ({ ...prev, [watchlistId]: "idle" })), 4000);
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
    <div ref={panelRef} className="relative" onKeyDown={onPopoverKeyDown}>
      <Button
        ref={triggerRef}
        variant="primary"
        // primary at sm is 32px, like the outline RefreshButton beside it in the
        // ticker header and the Screener results-header buttons.
        size="sm"
        onClick={() => setPanel((p) => (p === "idle" ? "picking" : "idle"))}
        disabled={disabled}
        aria-expanded={panel === "picking"}
        aria-controls={panel === "picking" ? panelId : undefined}
        aria-label={label === undefined ? "Add to watchlist" : undefined}
      >
        {label === undefined ? (
          <>
            <Plus size={12} weight="bold" aria-hidden="true" />
            Watchlist
          </>
        ) : (
          label
        )}
      </Button>

      {panel === "picking" && (
        <div id={panelId} className="absolute right-0 z-20 mt-1 w-64 rounded-md border border-border-input bg-surface p-1 shadow-lg">
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
                        <Button variant="outline" size="sm" onClick={() => handleBulkAdd(w.id)} className={WARN_BUTTON_CLASS}>
                          Okay
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setConfirmTarget(null)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  );
                }

                if (!isBulk && removeConfirmTarget === w.id) {
                  return (
                    <div key={w.id} className="space-y-1 rounded px-2 py-1.5 text-xs">
                      <p className="text-warn">
                        Remove {tickers[0].toUpperCase()} from &quot;{w.name}&quot;?
                      </p>
                      <div className="flex items-center gap-1.5">
                        <Button variant="outline" size="sm" onClick={() => handleRemove(w.id)} className={WARN_BUTTON_CLASS}>
                          Okay
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setRemoveConfirmTarget(null)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  );
                }

                const alreadyAdded = !isBulk && w.tickers.some((t) => t.ticker === tickers[0].toUpperCase());
                const resultMessage = isBulk ? bulkResult[w.id] : undefined;
                const removeState = removeStatus[w.id] ?? "idle";

                return (
                  <div key={w.id} className="space-y-0.5 rounded px-2 py-0.5">
                    <div className="flex items-center justify-between gap-2 text-xs text-text-secondary">
                      <span className="truncate">{w.name}</span>
                      {alreadyAdded ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setRemoveConfirmTarget(w.id)}
                          disabled={removeState === "removing"}
                          className={`shrink-0 ${REMOVE_BUTTON_CLASS}`}
                        >
                          {REMOVE_STATUS_LABELS[removeState]}
                        </Button>
                      ) : status === "saved" && resultMessage ? (
                        <span className="shrink-0 text-positive">{resultMessage}</span>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => (isBulk ? setConfirmTarget(w.id) : handleAddToExisting(w.id))}
                          disabled={status === "saving" || status === "saved"}
                          className="shrink-0"
                        >
                          <StatusLabel status={status} labels={ADD_STATUS_LABELS} />
                        </Button>
                      )}
                    </div>
                    {status === "error" && addErrorMessage[w.id] && (
                      <p className="text-xs text-negative">{addErrorMessage[w.id]}</p>
                    )}
                    {removeState === "error" && removeErrorMessage[w.id] && (
                      <p className="text-xs text-negative">{removeErrorMessage[w.id]}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="mt-1 border-t border-border-subtle pt-1">
            {newListStep === "idle" ? (
              <Button ref={newListTriggerRef} variant="ghost" size="sm" onClick={openNewList} className="w-full justify-start px-2">
                <Plus size={12} weight="bold" aria-hidden="true" />
                New watchlist
              </Button>
            ) : (
              <div className="space-y-2 px-2 py-1.5">
                <Input
                  type="text"
                  size="full"
                  autoFocus
                  aria-label="New watchlist name"
                  placeholder="Watchlist name"
                  maxLength={WATCHLIST_NAME_MAX_LENGTH}
                  value={newListName}
                  invalid={newListError != null}
                  aria-describedby={newListError ? newListErrorId : undefined}
                  onChange={(e) => setNewListName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCreateAndAdd();
                    if (e.key === "Escape") {
                      e.stopPropagation();
                      cancelNewList();
                    }
                  }}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="primary"
                    onClick={handleCreateAndAdd}
                    disabled={!newListName.trim() || newListStatus === "saving"}
                  >
                    <StatusLabel status={newListStatus} labels={CREATE_STATUS_LABELS} />
                  </Button>
                  <Button variant="outline" onClick={cancelNewList}>
                    Cancel
                  </Button>
                </div>
                {newListError && (
                  <p id={newListErrorId} role="alert" className={FIELD_ERROR_CLASS}>
                    {newListError}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
