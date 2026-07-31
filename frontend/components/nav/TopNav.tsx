"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageContainer } from "@/components/layout/PageContainer";
import { TickerSearch } from "@/components/nav/TickerSearch";
import { cn } from "@/lib/utils";

interface NavLink {
  label: string;
  href: string;
}

const NAV_LINKS: NavLink[] = [
  { href: "/screener", label: "Screener" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/settings", label: "Settings" },
];

// Ticker Analysis has no landing page of its own -- per the design
// handoff, it's "reached by searching a ticker or navigating from
// Screener/Watchlist," not by clicking this item directly. It renders as
// a plain active-state indicator (highlighted only while already on a
// ticker page), not a link to nowhere.
export function TopNav() {
  const pathname = usePathname();
  const onTickerPage = pathname.startsWith("/tickers/");

  return (
    <nav className="sticky top-0 z-30 border-b border-border-subtle bg-page/90 backdrop-blur">
      <PageContainer className="flex h-12 items-center gap-4">
        <Link href="/screener" className="font-heading shrink-0 text-sm font-semibold tracking-tight text-text-primary">
          Fathom
        </Link>
        <div className="flex min-w-0 items-center gap-0.5">
          <span
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium",
              onTickerPage ? "bg-brand/15 text-brand" : "text-text-tertiary"
            )}
          >
            Ticker Analysis
          </span>
          {NAV_LINKS.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active ? "bg-brand/15 text-brand" : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
                )}
              >
                {label}
              </Link>
            );
          })}
        </div>
        <div className="flex-1" />
        <div className="shrink-0">
          <TickerSearch />
        </div>
      </PageContainer>
    </nav>
  );
}
