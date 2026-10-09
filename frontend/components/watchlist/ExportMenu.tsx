"use client";

import { useEffect, useRef, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";

interface Props {
  disabled?: boolean;
  // Disables just the two single-list items (the active list has no rows to export yet); the trigger stays usable so
  // the multi-list item remains reachable.
  singleDisabled?: boolean;
  // Styleguide seam: draws the menu open. The page never passes it.
  defaultOpen?: boolean;
  onExportTradingView: () => void;
  onExportThinkorswim: () => void;
  // The third item, "Export multiple lists…", which opens the page's inline panel. Omitted = the two-item menu.
  onExportMultiple?: () => void;
}

const ITEM_CLASS =
  "w-full rounded px-2 py-1.5 text-left text-xs text-text-secondary hover:bg-surface-2 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent disabled:hover:text-text-secondary";

export function ExportMenu({
  disabled,
  singleDisabled,
  defaultOpen = false,
  onExportTradingView,
  onExportThinkorswim,
  onExportMultiple,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function select(action: () => void) {
    action();
    close();
  }

  return (
    <div ref={ref} className="relative">
      <Button
        ref={triggerRef}
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.preventDefault();
            close();
          }
        }}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Export list
        <CaretDown size={12} weight="bold" aria-hidden="true" className="text-text-tertiary" />
      </Button>

      {open && (
        <div
          role="menu"
          aria-label="Export list"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          className="absolute right-0 z-20 mt-1 w-52 rounded-md border border-border-input bg-surface p-1 shadow-lg"
        >
          <button type="button" role="menuitem" disabled={singleDisabled} onClick={() => select(onExportTradingView)} className={ITEM_CLASS}>
            TradingView (.txt)
          </button>
          <button type="button" role="menuitem" disabled={singleDisabled} onClick={() => select(onExportThinkorswim)} className={ITEM_CLASS}>
            thinkorswim (.csv)
          </button>
          {onExportMultiple && (
            <>
              <div role="separator" className="my-1 border-t border-border-subtle" />
              <button type="button" role="menuitem" onClick={() => select(onExportMultiple)} className={ITEM_CLASS}>
                Export multiple lists…
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
