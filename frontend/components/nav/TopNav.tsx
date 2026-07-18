"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageContainer } from "@/components/layout/PageContainer";
import { TickerSearch } from "@/components/nav/TickerSearch";
import { cn } from "@/lib/utils";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/reports", label: "Reports" },
];

export function TopNav() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 z-30 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur">
      <PageContainer className="flex h-12 items-center gap-4">
        <Link href="/" className="shrink-0 text-sm font-semibold tracking-tight text-zinc-100">
          Fathom
        </Link>
        <div className="flex min-w-0 items-center gap-0.5">
          {NAV_LINKS.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
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
