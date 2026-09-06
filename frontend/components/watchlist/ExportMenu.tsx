"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  disabled?: boolean;
  onExportTradingView: () => void;
  onExportThinkorswim: () => void;
}

export function ExportMenu({ disabled, onExportTradingView, onExportThinkorswim }: Props) {
  const [open, setOpen] = useState(false);
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
      <button
        ref={triggerRef}
        type="button"
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
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        Export List
        <span className="text-text-tertiary">▾</span>
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Export List"
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
