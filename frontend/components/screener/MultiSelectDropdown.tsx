"use client";

import { type KeyboardEvent, useEffect, useRef, useState } from "react";

export interface MultiSelectOption {
  value: string;
  label: string;
}

interface Props {
  label: string;
  options: MultiSelectOption[];
  selected: string[];
  onChange: (selected: string[]) => void;
}

export function MultiSelectDropdown({ label, options, selected, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const clearRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  // Move focus into the panel on open, same as a native <select>'s popup --
  // lands on Clear when present, otherwise the first option.
  useEffect(() => {
    if (!open) return;
    (clearRef.current ?? optionRefs.current[0])?.focus();
  }, [open]);

  function toggle(value: string) {
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);
  }

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function panelFocusables(): HTMLElement[] {
    const els: HTMLElement[] = [];
    if (clearRef.current) els.push(clearRef.current);
    for (const el of optionRefs.current) if (el) els.push(el);
    return els;
  }

  function handlePanelKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }

    if (e.key === "Tab") {
      // Focus trap: Tab/Shift+Tab cycles within the panel instead of
      // escaping to the rest of the page while it's open.
      const els = panelFocusables();
      if (els.length === 0) return;
      const currentIndex = els.indexOf(document.activeElement as HTMLElement);
      const lastIndex = els.length - 1;
      if (!e.shiftKey && currentIndex === lastIndex) {
        e.preventDefault();
        els[0].focus();
      } else if (e.shiftKey && currentIndex <= 0) {
        e.preventDefault();
        els[lastIndex].focus();
      }
      return;
    }

    // Arrow/Home/End roving focus is scoped to the option checkboxes --
    // Enter/Space toggling is already native <input type="checkbox"> behavior.
    const count = optionRefs.current.length;
    if (count === 0) return;
    const optionIndex = optionRefs.current.indexOf(document.activeElement as HTMLInputElement);
    if (optionIndex === -1) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      optionRefs.current[(optionIndex + 1) % count]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      optionRefs.current[(optionIndex - 1 + count) % count]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      optionRefs.current[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      optionRefs.current[count - 1]?.focus();
    }
  }

  const selectedLabel = selected.length === 1 ? (options.find((o) => o.value === selected[0])?.label ?? selected[0]) : "";
  const summary = selected.length === 0 ? label : selected.length === 1 ? selectedLabel : `${label} (${selected.length})`;

  return (
    <div ref={ref} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.preventDefault();
            close();
          }
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
      >
        {summary}
        <span className="text-zinc-500">▾</span>
      </button>

      {open && (
        <div
          role="listbox"
          aria-multiselectable="true"
          aria-label={label}
          onKeyDown={handlePanelKeyDown}
          className="absolute z-20 mt-1 max-h-64 w-56 overflow-y-auto rounded-md border border-zinc-700 bg-zinc-900 p-1 shadow-lg"
        >
          {selected.length > 0 && (
            <button
              ref={clearRef}
              type="button"
              onClick={() => onChange([])}
              className="mb-1 w-full rounded px-2 py-1 text-left text-xs text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
            >
              Clear
            </button>
          )}
          {options.length === 0 ? (
            <p className="px-2 py-1 text-xs text-zinc-600">No options</p>
          ) : (
            options.map((option, i) => (
              <label
                key={option.value}
                role="option"
                aria-selected={selected.includes(option.value)}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
              >
                <input
                  ref={(el) => {
                    optionRefs.current[i] = el;
                  }}
                  type="checkbox"
                  checked={selected.includes(option.value)}
                  onChange={() => toggle(option.value)}
                  className="size-3.5 rounded border-zinc-600 bg-zinc-800 accent-zinc-400"
                />
                {option.label}
              </label>
            ))
          )}
        </div>
      )}
    </div>
  );
}
