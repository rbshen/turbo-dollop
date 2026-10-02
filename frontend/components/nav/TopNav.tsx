"use client";

import Link from "next/link";
import type { MouseEvent as ReactMouseEvent } from "react";
import { usePathname } from "next/navigation";

import { PageContainer } from "@/components/layout/PageContainer";
import { TickerSearch } from "@/components/nav/TickerSearch";
import { cn } from "@/lib/utils";

interface NavLink {
  label: string;
  href: string;
}

const NAV_LINKS: NavLink[] = [
  { href: "/screener", label: "Stocks" },
  { href: "/etfs", label: "ETFs" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/momentum", label: "Momentum" },
  { href: "/sectors", label: "Sectors" },
  { href: "/breadth", label: "Breadth" },
  { href: "/settings", label: "Settings" },
];

// Nav links open in a new tab, except on the pages below. A script can't open a tab without taking focus (window.open and target="_blank" both
// foreground it), but a modifier-click is the browser's own "open in background tab" gesture -- so a plain click is
// replayed as one (Cmd on Mac, Ctrl elsewhere). The real href/target stay on the <a> for middle-click, keyboard and
// no-JS. Safari ignores modifiers on a synthetic click and just foregrounds the tab, same as before.
// On these pages (and their sub-routes) every nav item, the logo included, navigates in the same tab instead.
const SAME_TAB_PREFIXES = ["/momentum", "/sectors", "/breadth", "/settings"];
const NEW_TAB_PROPS = { target: "_blank", rel: "noopener noreferrer", onClick: openInBackgroundTab } as const;

function openInBackgroundTab(e: ReactMouseEvent<HTMLAnchorElement>) {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // already a deliberate gesture
  e.preventDefault();
  const a = document.createElement("a");
  a.href = e.currentTarget.href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.style.display = "none";
  document.body.appendChild(a);
  const mac = /Mac|iPhone|iPad/.test(navigator.platform);
  a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: !mac, metaKey: mac }));
  a.remove();
}

// Ticker Analysis has no landing page of its own -- per the design
// handoff, it's "reached by searching a ticker or navigating from
// Stocks/ETFs/Watchlist," not by clicking this item directly. It renders as
// a plain active-state indicator (highlighted only while already on a
// ticker page), not a link to nowhere.
export function TopNav() {
  const pathname = usePathname();
  const onTickerPage = pathname.startsWith("/tickers/");
  const sameTab = SAME_TAB_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  return (
    <nav className="sticky top-0 z-30 border-b border-border-subtle bg-page/90 backdrop-blur">
      <PageContainer className="flex h-12 items-center gap-4">
        <Link href="/screener" {...(sameTab ? {} : NEW_TAB_PROPS)} className="font-heading shrink-0 text-sm font-semibold tracking-tight text-text-primary">
          Fathom
        </Link>
        <div className="flex min-w-0 items-center gap-0.5">
          <span
            aria-current={onTickerPage ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium",
              onTickerPage ? "bg-surface-2 text-text-primary" : "text-text-tertiary"
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
                aria-current={active ? "page" : undefined}
                {...(sameTab ? {} : NEW_TAB_PROPS)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active ? "bg-surface-2 text-text-primary" : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
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
