"use client";

import { Check, Trash } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { deleteScreenerFilter, saveScreenerFilter, useSavedFilters } from "@/lib/hooks/useSavedFilters";
import type { SavedScreenerFilter, ScreenerUniverse } from "@/lib/api/types";
import type { ScreenerFilterState, SortDirection, SortField } from "@/lib/screenerFilters";
import { cn } from "@/lib/utils";

interface Props {
  universe: ScreenerUniverse;
  sortField: SortField;
  sortDirection: SortDirection;
  filters: ScreenerFilterState;
  onLoad: (saved: SavedScreenerFilter) => void;
  onReset: () => void;
  // "horizontal" (default): the original full-width top-bar layout.
  // "vertical": stacked full-width, for the sidebar's Saved-views group.
  layout?: "horizontal" | "vertical";
}

type SaveStep = "idle" | "naming" | "confirmOverwrite";

// Same shape/labels as DiscountRateSettingsForm/MoatSettingsForm's own
// save-status pattern -- reused here rather than inventing a separate one.
type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function SavedFiltersBar({ universe, sortField, sortDirection, filters, onLoad, onReset, layout = "horizontal" }: Props) {
  const { data: saved } = useSavedFilters();
  const [listOpen, setListOpen] = useState(false);
  const [saveStep, setSaveStep] = useState<SaveStep>("idle");
  const [name, setName] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [deleteState, setDeleteState] = useState<{ name: string; status: "deleting" | "error" } | null>(null);
  // Which saved view is currently loaded, if any -- purely "the last one you
  // picked (or just saved over)", not a live diff against the current
  // filters, so it stays highlighted even after further manual edits. Local
  // to this component (not lifted to page.tsx) since only this component's
  // own list/trigger need to render it.
  const [activeName, setActiveName] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (listRef.current && !listRef.current.contains(e.target as Node)) setListOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function openNaming() {
    setName("");
    setSaveStep("naming");
    setListOpen(false);
  }

  function cancelSave() {
    setSaveStep("idle");
    setName("");
  }

  async function doSave(trimmedName: string) {
    setStatus("saving");
    try {
      await saveScreenerFilter(trimmedName, {
        universe,
        sort_field: sortField,
        sort_direction: sortDirection,
        filters,
      });
      setStatus("saved");
      setSaveStep("idle");
      setName("");
      // The current view now IS this saved view -- reflect that immediately
      // rather than waiting for a subsequent load to show it as active.
      setActiveName(trimmedName);
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  async function handleConfirm() {
    const trimmedName = name.trim();
    if (!trimmedName) return;

    const existing = saved?.find((s) => s.name === trimmedName);
    if (existing && saveStep !== "confirmOverwrite") {
      setSaveStep("confirmOverwrite");
      return;
    }
    await doSave(trimmedName);
  }

  return (
    <div className={cn("flex items-center gap-2", layout === "vertical" && "flex-col items-stretch")}>
      <div ref={listRef} className="relative">
        <button
          type="button"
          onClick={() => setListOpen((o) => !o)}
          className="flex h-8 items-center gap-1.5 rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary"
        >
          {/* Same "show the active selection instead of the generic label"
              convention MultiSelectDropdown's trigger already uses. */}
          <span className="truncate">{activeName ?? `Saved views${saved && saved.length > 0 ? ` (${saved.length})` : ""}`}</span>
          <span className="shrink-0 text-text-tertiary">▾</span>
        </button>

        {listOpen && (
          <div className="absolute z-20 mt-1 max-h-64 w-64 overflow-y-auto rounded-md border border-border-input bg-surface p-1 shadow-lg">
            {!saved || saved.length === 0 ? (
              <p className="px-2 py-1 text-xs text-text-tertiary">No saved views yet</p>
            ) : (
              saved.map((s) => (
                <div
                  key={s.id}
                  role="option"
                  aria-selected={s.name === activeName}
                  className={cn(
                    "flex cursor-pointer items-center justify-between gap-2 rounded px-2 py-1 text-xs hover:bg-surface-2",
                    s.name === activeName ? "bg-surface-2 font-medium text-text-primary" : "text-text-secondary"
                  )}
                  onClick={() => {
                    onLoad(s);
                    setActiveName(s.name);
                    setListOpen(false);
                  }}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    {s.name === activeName && <Check size={12} className="shrink-0 text-brand" />}
                    <span className="truncate">{s.name}</span>
                  </span>
                  <button
                    type="button"
                    onClick={async (e) => {
                      e.stopPropagation();
                      setDeleteState({ name: s.name, status: "deleting" });
                      try {
                        await deleteScreenerFilter(s.name);
                        setDeleteState(null);
                        if (s.name === activeName) setActiveName(null);
                      } catch {
                        setDeleteState({ name: s.name, status: "error" });
                        setTimeout(() => setDeleteState(null), 3000);
                      }
                    }}
                    disabled={deleteState?.name === s.name && deleteState.status === "deleting"}
                    className={`shrink-0 disabled:opacity-50 ${
                      deleteState?.name === s.name && deleteState.status === "error"
                        ? "text-negative"
                        : "text-text-tertiary hover:text-negative"
                    }`}
                    title={
                      deleteState?.name === s.name && deleteState.status === "error"
                        ? `Failed to delete "${s.name}" — try again`
                        : `Delete "${s.name}"`
                    }
                  >
                    <Trash size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {saveStep === "idle" && (
        <button
          type="button"
          onClick={openNaming}
          className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary"
        >
          Save current view
        </button>
      )}

      {saveStep === "idle" && (
        <button
          type="button"
          onClick={() => {
            onReset();
            setActiveName(null);
          }}
          className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary"
        >
          Reset
        </button>
      )}

      {saveStep === "naming" && (
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            autoFocus
            placeholder="View name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleConfirm();
              if (e.key === "Escape") cancelSave();
            }}
            className="h-8 w-40 rounded-md border border-border-input bg-surface px-2 text-xs text-text-primary placeholder:text-text-tertiary focus:border-brand focus:outline-none"
          />
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!name.trim() || status === "saving"}
            className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-2 text-xs text-text-secondary hover:border-brand hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {STATUS_LABELS[status]}
          </button>
          <button
            type="button"
            onClick={cancelSave}
            className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-2 text-xs text-text-tertiary hover:border-brand hover:text-text-secondary"
          >
            Cancel
          </button>
        </div>
      )}

      {saveStep === "confirmOverwrite" && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-warn">A saved view named &quot;{name.trim()}&quot; already exists — overwrite?</span>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={status === "saving"}
            className="inline-flex h-8 items-center rounded-md border border-warn/60 bg-surface px-2 text-xs text-warn hover:border-warn disabled:cursor-not-allowed disabled:opacity-50"
          >
            {status === "idle" ? "Overwrite" : STATUS_LABELS[status]}
          </button>
          <button
            type="button"
            onClick={cancelSave}
            className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-2 text-xs text-text-tertiary hover:border-brand hover:text-text-secondary"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
