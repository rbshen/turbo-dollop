"use client";

import { TICKER_TABS, type TickerTab } from "@/lib/tickerTabs";

interface Props {
  active: TickerTab;
  onChange: (tab: TickerTab) => void;
}

export function TickerTabs({ active, onChange }: Props) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-zinc-800">
      {TICKER_TABS.map(({ key, label }) => {
        const isActive = key === active;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            className={`shrink-0 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
              isActive
                ? "border-zinc-100 text-zinc-100"
                : "border-transparent text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
