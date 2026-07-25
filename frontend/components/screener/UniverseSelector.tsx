"use client";

import type { ScreenerUniverse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const UNIVERSE_OPTIONS: { value: ScreenerUniverse; label: string }[] = [
  { value: "sp500", label: "S&P 500" },
  { value: "dow", label: "Dow 30" },
];

interface Props {
  value: ScreenerUniverse;
  onChange: (universe: ScreenerUniverse) => void;
}

export function UniverseSelector({ value, onChange }: Props) {
  return (
    <div className="inline-flex items-center rounded-md border border-zinc-700 bg-zinc-900 p-0.5">
      {UNIVERSE_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium transition-colors",
            option.value === value ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
