"use client";

import Link from "next/link";

import { SECTOR_ETFS } from "@/lib/marketBreadth";
import { cn } from "@/lib/utils";

interface Props {
  // "sp500" or an ETF ticker like "XLK"; an unrecognized value highlights nothing.
  active: string;
}

/** 12-entry tab strip -- "S&P 500" (-> /breadth) plus the 11 SPDR sectors (-> /breadth/<ticker>), in the
 * same order the Sector Heatmap uses. Used only on the sector breadth pages: the sp500 page itself keeps
 * its own small "Browse by sector" link instead, so its already-tested body stays untouched. */
export function BreadthSectorTabs({ active }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-border-subtle pb-2" role="tablist" aria-label="Market breadth universe">
      <Tab href="/breadth" label="S&P 500" isActive={active === "sp500"} />
      {SECTOR_ETFS.map(({ ticker, name }) => (
        <Tab key={ticker} href={`/breadth/${ticker}`} label={ticker} title={name} isActive={active === ticker} />
      ))}
    </div>
  );
}

function Tab({ href, label, title, isActive }: { href: string; label: string; title?: string; isActive: boolean }) {
  return (
    <Link
      href={href}
      title={title}
      role="tab"
      aria-selected={isActive}
      className={cn(
        "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
        isActive ? "bg-brand/15 text-brand" : "text-text-tertiary hover:bg-white/5 hover:text-text-primary"
      )}
    >
      {label}
    </Link>
  );
}
