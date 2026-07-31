"use client";

import { TICKER_TABS, type TickerTab } from "@/lib/tickerTabs";

interface Props {
  active: TickerTab;
  onChange: (tab: TickerTab) => void;
}

export function TickerTabs({ active, onChange }: Props) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-border-card">
      {TICKER_TABS.map(({ key, label }) => {
        const isActive = key === active;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            className={`shrink-0 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
              isActive
                ? "border-brand text-brand"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
