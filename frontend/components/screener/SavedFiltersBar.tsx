"use client";

import { CaretDown, Check, Trash } from "@phosphor-icons/react";
import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { deleteScreenerFilter, saveScreenerFilter, useSavedFilters, type SaveScreenerFilterBody } from "@/lib/hooks/useSavedFilters";
import type { SavedScreenerFilter, ScreenerUniverse } from "@/lib/api/types";
import type { ScreenerFilterState, SortDirection, SortField } from "@/lib/screenerFilters";
import { cn } from "@/lib/utils";

interface Props {
  universe: ScreenerUniverse;
  sortField: SortField;
  sortDirection: SortDirection;
  filters: ScreenerFilterState;
  // The WATCHLIST universe filter's current selection, persisted alongside
  // universe/sortField/etc. on save -- see SavedScreenerFilter.watchlist_id.
  watchlistId: number | null;
  onLoad: (saved: SavedScreenerFilter) => void;
  onReset: () => void;
}

export type SaveStep = "idle" | "naming" | "confirmOverwrite";

// Same shape/labels as DiscountRateSettingsForm/MoatSettingsForm's own
// save-status pattern -- reused here rather than inventing a separate one.
type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

// The view name is one URL path segment (PUT/DELETE /screener/filters/{name}),
// and the server decodes %2F back to "/" before routing, so a name containing
// "/" can be neither saved nor deleted (404) -- verified 2026-09-30, see
// docs/decisions.md. Every other character tried works (spaces, ? # % + & ;
// backslash, accented letters), so "/" is the only one blocked. The text is
// never altered: the box shows this message and Save stays off.
export const NAME_SLASH_ERROR = 'A view name cannot contain "/".';

export interface SavedFiltersBarViewProps extends Props {
  saved: SavedScreenerFilter[] | undefined;
  onSave: (name: string, body: SaveScreenerFilterBody) => Promise<unknown>;
  onDelete: (name: string) => Promise<unknown>;
  // Initial state, so the /styleguide can show the popover, the naming step and
  // the overwrite confirm without clicking. The app never sets these.
  defaultListOpen?: boolean;
  defaultSaveStep?: SaveStep;
  defaultName?: string;
  defaultActiveName?: string | null;
}

// The data-wired bar the Screener renders: the saved views from SWR and the
// real save/delete calls. All of the UI is SavedFiltersBarView below.
export function SavedFiltersBar(props: Props) {
  const { data: saved } = useSavedFilters();
  return <SavedFiltersBarView {...props} saved={saved} onSave={saveScreenerFilter} onDelete={deleteScreenerFilter} />;
}

export function SavedFiltersBarView({
  universe,
  sortField,
  sortDirection,
  filters,
  watchlistId,
  onLoad,
  onReset,
  saved,
  onSave,
  onDelete,
  defaultListOpen = false,
  defaultSaveStep = "idle",
  defaultName = "",
  defaultActiveName = null,
}: SavedFiltersBarViewProps) {
  const [listOpen, setListOpen] = useState(defaultListOpen);
  const [saveStep, setSaveStep] = useState<SaveStep>(defaultSaveStep);
  const [name, setName] = useState(defaultName);
  const [status, setStatus] = useState<Status>("idle");
  const [deleteState, setDeleteState] = useState<{ name: string; status: "deleting" | "error" } | null>(null);
  // Which saved view is currently loaded, if any -- purely "the last one you
  // picked (or just saved over)", not a live diff against the current
  // filters, so it stays highlighted even after further manual edits. Local
  // to this component (not lifted to page.tsx) since only this component's
  // own list/trigger need to render it.
  const [activeName, setActiveName] = useState<string | null>(defaultActiveName);
  const listRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const rowRefs = useRef(new Map<string, HTMLButtonElement>());
  const panelId = useId();
  const nameId = useId();

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (listRef.current && !listRef.current.contains(e.target as Node)) setListOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function closeList() {
    setListOpen(false);
    triggerRef.current?.focus();
  }

  // Escape anywhere in the trigger/popover closes the popover and returns
  // focus to the trigger.
  function handleListKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape" && listOpen) {
      e.preventDefault();
      closeList();
    }
  }

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
      await onSave(trimmedName, {
        universe,
        sort_field: sortField,
        sort_direction: sortDirection,
        filters,
        watchlist_id: watchlistId,
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

  const nameError = name.includes("/") ? NAME_SLASH_ERROR : undefined;

  async function handleConfirm() {
    const trimmedName = name.trim();
    if (!trimmedName || nameError) return;

    const existing = saved?.find((s) => s.name === trimmedName);
    if (existing && saveStep !== "confirmOverwrite") {
      setSaveStep("confirmOverwrite");
      return;
    }
    await doSave(trimmedName);
  }

  async function handleDelete(s: SavedScreenerFilter, index: number) {
    if (deleteState?.name === s.name && deleteState.status === "deleting") return;
    // Where focus goes once this row is gone: the next row, else the previous
    // one, else the trigger -- so it is never dropped onto <body>.
    const neighbour = saved?.[index + 1] ?? saved?.[index - 1];
    setDeleteState({ name: s.name, status: "deleting" });
    try {
      await onDelete(s.name);
      setDeleteState(null);
      if (s.name === activeName) setActiveName(null);
      (neighbour ? rowRefs.current.get(neighbour.name) : triggerRef.current)?.focus();
    } catch {
      setDeleteState({ name: s.name, status: "error" });
      setTimeout(() => setDeleteState(null), 3000);
    }
  }

  return (
    <div className="flex flex-col items-stretch gap-2">
      <div ref={listRef} className="relative" onKeyDown={handleListKeyDown}>
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setListOpen((o) => !o)}
          aria-expanded={listOpen}
          aria-controls={listOpen ? panelId : undefined}
          className="flex h-8 items-center gap-1.5 rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary"
        >
          {/* Same "show the active selection instead of the generic label"
              convention MultiSelectDropdown's trigger already uses. */}
          <span className="truncate">{activeName ?? `Saved views${saved && saved.length > 0 ? ` (${saved.length})` : ""}`}</span>
          <CaretDown size={12} weight="bold" aria-hidden="true" className="shrink-0 text-text-tertiary" />
        </button>

        {listOpen && (
          <div
            id={panelId}
            role="group"
            aria-label="Saved views"
            className="absolute z-20 mt-1 max-h-64 w-64 overflow-y-auto rounded-md border border-border-input bg-surface p-1 shadow-lg"
          >
            {!saved || saved.length === 0 ? (
              <p className="px-2 py-1 text-xs text-text-tertiary">No saved views yet</p>
            ) : (
              saved.map((s, index) => {
                const active = s.name === activeName;
                const deleting = deleteState?.name === s.name && deleteState.status === "deleting";
                const failed = deleteState?.name === s.name && deleteState.status === "error";
                const deleteLabel = failed ? `Failed to delete view "${s.name}" — try again` : `Delete view "${s.name}"`;
                return (
                  <div key={s.id} className={cn("flex items-center gap-1 rounded hover:bg-surface-2", active && "bg-surface-2")}>
                    {/* Two sibling buttons (a button cannot nest a button): the
                        name loads the view, the trash deletes it. */}
                    <button
                      ref={(el) => {
                        if (el) rowRefs.current.set(s.name, el);
                        else rowRefs.current.delete(s.name);
                      }}
                      type="button"
                      aria-current={active ? "true" : undefined}
                      onClick={() => {
                        onLoad(s);
                        setActiveName(s.name);
                        closeList();
                      }}
                      className={cn(
                        "flex min-w-0 flex-1 items-center gap-1.5 rounded px-2 py-1 text-left text-xs",
                        active ? "font-medium text-text-primary" : "text-text-secondary"
                      )}
                    >
                      {active && <Check size={12} aria-hidden="true" className="shrink-0 text-text-primary" />}
                      <span className="truncate">{s.name}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(s, index)}
                      // aria-disabled, not disabled, while deleting: the button keeps
                      // focus, and the click is ignored in handleDelete.
                      aria-disabled={deleting || undefined}
                      aria-label={deleteLabel}
                      title={deleteLabel}
                      className={cn(
                        "mr-1 shrink-0 rounded p-1",
                        deleting && "opacity-50",
                        failed ? "text-negative" : "text-text-tertiary hover:text-negative"
                      )}
                    >
                      <Trash size={14} aria-hidden="true" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      {saveStep === "idle" && (
        <Button variant="outline" size="sm" onClick={openNaming}>
          Save current view
        </Button>
      )}

      {saveStep === "idle" && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            onReset();
            setActiveName(null);
          }}
        >
          Reset
        </Button>
      )}

      {saveStep === "naming" && (
        <div className="flex flex-col gap-2">
          <FormField density="compact" label="View name" htmlFor={nameId} error={nameError}>
            <Input
              size="full"
              type="text"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleConfirm();
                if (e.key === "Escape") cancelSave();
              }}
            />
          </FormField>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleConfirm} disabled={!name.trim() || !!nameError || status === "saving"}>
              {STATUS_LABELS[status]}
            </Button>
            <Button variant="outline" size="sm" onClick={cancelSave}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {saveStep === "confirmOverwrite" && (
        <div className="flex flex-col gap-2">
          <p className="break-words text-xs text-warn">A saved view named &quot;{name.trim()}&quot; already exists — overwrite?</p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleConfirm}
              disabled={status === "saving"}
              className="border-warn/60 text-warn hover:border-warn hover:text-warn"
            >
              {status === "idle" ? "Overwrite" : STATUS_LABELS[status]}
            </Button>
            <Button variant="outline" size="sm" onClick={cancelSave}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
