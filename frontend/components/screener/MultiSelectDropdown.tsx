"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  label: string;
  options: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
}

export function MultiSelectDropdown({ label, options, selected, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function toggle(option: string) {
    onChange(selected.includes(option) ? selected.filter((o) => o !== option) : [...selected, option]);
  }

  const summary = selected.length === 0 ? label : selected.length === 1 ? selected[0] : `${label} (${selected.length})`;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
      >
        {summary}
        <span className="text-zinc-500">▾</span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1 max-h-64 w-56 overflow-y-auto rounded-md border border-zinc-700 bg-zinc-900 p-1 shadow-lg">
          {selected.length > 0 && (
            <button
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
            options.map((option) => (
              <label
                key={option}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(option)}
                  onChange={() => toggle(option)}
                  className="size-3.5 rounded border-zinc-600 bg-zinc-800 accent-zinc-400"
                />
                {option}
              </label>
            ))
          )}
        </div>
      )}
    </div>
  );
}
