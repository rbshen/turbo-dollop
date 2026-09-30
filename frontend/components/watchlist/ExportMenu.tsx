"use client";

import { useEffect, useRef, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";

interface Props {
  disabled?: boolean;
  // Styleguide seam: draws the menu open. The page never passes it.
  defaultOpen?: boolean;
  onExportTradingView: () => void;
  onExportThinkorswim: () => void;
}

export function ExportMenu({ disabled, defaultOpen = false, onExportTradingView, onExportThinkorswim }: Props) {
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
          className="absolute right-0 z-20 mt-1 w-44 rounded-md border border-border-input bg-surface p-1 shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => select(onExportTradingView)}
            className="w-full rounded px-2 py-1.5 text-left text-xs text-text-secondary hover:bg-surface-2 hover:text-text-primary"
          >
            TradingView (.txt)
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => select(onExportThinkorswim)}
            className="w-full rounded px-2 py-1.5 text-left text-xs text-text-secondary hover:bg-surface-2 hover:text-text-primary"
          >
            thinkorswim (.csv)
          </button>
        </div>
      )}
    </div>
  );
}
