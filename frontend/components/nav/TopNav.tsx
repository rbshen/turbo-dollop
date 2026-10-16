"use client";

import Link from "next/link";
import { Fragment, type MouseEvent as ReactMouseEvent } from "react";
import { usePathname } from "next/navigation";
import { Menu } from "@base-ui/react/menu";
import { CaretDown } from "@phosphor-icons/react";

import { PageContainer } from "@/components/layout/PageContainer";
import { TickerSearch } from "@/components/nav/TickerSearch";
import { useAuth } from "@/lib/auth/AuthProvider";
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
];

// "Investing" and "Markets" are dropdowns, not pages: both sit after Momentum, Investing first. Each is active on any of its routes
// and their sub-routes (/breadth/[sector]). Investing groups the idea lists; Markets the two market-wide views.
const INVESTING_LINKS: NavLink[] = [
  { href: "/opportunities", label: "Opportunities" },
  { href: "/technical-ideas", label: "Technical Ideas" },
];
const MARKETS_LINKS: NavLink[] = [
  { href: "/sectors", label: "Sectors" },
  { href: "/breadth", label: "Breadth" },
];
const MENUS_AFTER = "/momentum";
const SETTINGS_HREF = "/settings";

function isUnder(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

// Nav links open in a new tab, except on the pages below. A script can't open a tab without taking focus (window.open and target="_blank" both
// foreground it), but a modifier-click is the browser's own "open in background tab" gesture -- so a plain click is
// replayed as one (Cmd on Mac, Ctrl elsewhere). The real href/target stay on the <a> for middle-click, keyboard and
// no-JS. Safari ignores modifiers on a synthetic click and just foregrounds the tab, same as before.
// On these pages (and their sub-routes) every nav item, the logo included, navigates in the same tab instead.
const SAME_TAB_PREFIXES = ["/opportunities", "/technical-ideas", "/momentum", "/sectors", "/breadth", "/settings"];
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

// Base UI's Menu supplies the disclosure behaviour: Enter/Space/ArrowDown open it, arrow keys move, Esc closes and returns focus to
// the trigger, an outside click closes it, and it sets aria-haspopup / aria-expanded. The popup is portalled, so the link group's
// overflow-x-auto does not clip it. Items are real links and carry the same new-tab behaviour as the other nav links.
function NavMenu({ label, links, pathname, sameTab }: { label: string; links: NavLink[]; pathname: string; sameTab: boolean }) {
  const active = links.some(({ href }) => isUnder(pathname, href));
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-current={active ? "page" : undefined}
        className={cn(
          "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
          active
            ? "bg-surface-2 text-text-primary"
            : "text-text-secondary hover:bg-white/5 hover:text-text-primary data-[popup-open]:bg-white/5 data-[popup-open]:text-text-primary"
        )}
      >
        {label}
        <CaretDown size={12} weight="bold" aria-hidden="true" className="text-text-tertiary" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side="bottom" align="start" sideOffset={6} className="z-40">
          <Menu.Popup className="min-w-36 rounded-md border border-border-input bg-surface p-1 shadow-popover outline-none">
            {links.map(({ href, label }) => {
              const current = isUnder(pathname, href);
              return (
                <Menu.LinkItem
                  key={href}
                  href={href}
                  closeOnClick
                  aria-current={current ? "page" : undefined}
                  {...(sameTab ? {} : NEW_TAB_PROPS)}
                  className={cn(
                    "block rounded px-2 py-1.5 text-sm outline-none transition-colors data-[highlighted]:bg-surface-2 data-[highlighted]:text-text-primary",
                    current ? "bg-surface-2 text-text-primary" : "text-text-secondary"
                  )}
                >
                  {label}
                </Menu.LinkItem>
              );
            })}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

// The account menu: its trigger is labelled with the login id ("User" until the id is known), truncated with an ellipsis when long, the full
// id in the title and the accessible name. It opens Settings (admin only; a viewer has no Settings page) and Sign out. Same Base UI Menu as Markets, so the
// keyboard and dismiss behaviour is the same: Enter/Space/ArrowDown open it, arrow keys move, Esc closes and returns focus to the trigger,
// an outside click closes it. The Settings item is a real link and follows the nav's new-tab rule.
function UserMenu({
  pathname,
  sameTab,
  isAdmin,
  loginId,
  onSignOut,
}: {
  pathname: string;
  sameTab: boolean;
  isAdmin: boolean;
  loginId?: string;
  onSignOut: () => void;
}) {
  const label = loginId?.trim() ? loginId : "User";
  const onSettings = isUnder(pathname, SETTINGS_HREF);
  const itemClass =
    "block w-full rounded px-2 py-1.5 text-left text-sm text-text-secondary outline-none transition-colors data-[highlighted]:bg-surface-2 data-[highlighted]:text-text-primary";
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-current={onSettings ? "page" : undefined}
        aria-label={label}
        title={label}
        className={cn(
          "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
          onSettings
            ? "bg-surface-2 text-text-primary"
            : "text-text-secondary hover:bg-white/5 hover:text-text-primary data-[popup-open]:bg-white/5 data-[popup-open]:text-text-primary"
        )}
      >
        <span className="max-w-28 truncate">{label}</span>
        <CaretDown size={12} weight="bold" aria-hidden="true" className="text-text-tertiary" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side="bottom" align="end" sideOffset={6} className="z-40">
          <Menu.Popup className="min-w-36 rounded-md border border-border-input bg-surface p-1 shadow-popover outline-none">
            {isAdmin && (
              <Menu.LinkItem
                href={SETTINGS_HREF}
                closeOnClick
                aria-current={onSettings ? "page" : undefined}
                {...(sameTab ? {} : NEW_TAB_PROPS)}
                className={cn(itemClass, onSettings && "bg-surface-2 text-text-primary")}
              >
                Settings
              </Menu.LinkItem>
            )}
            <Menu.Item onClick={onSignOut} className={itemClass}>
              Sign out
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

// Ticker Analysis has no landing page of its own -- per the design
// handoff, it's "reached by searching a ticker or navigating from
// Stocks/ETFs/Watchlist," not by clicking this item directly. It renders as
// a plain active-state indicator (highlighted only while already on a
// ticker page), not a link to nowhere.
export function TopNav() {
  const pathname = usePathname();
  const { user, isLoading, isAdmin, logout } = useAuth();
  // On the sign-in page, and for a visitor who is not signed in, there is nothing to navigate to: just the name. (While the
  // session is still being checked the full bar shows, so a signed-in page does not flicker.)
  if (pathname === "/login" || pathname.startsWith("/login/") || (!isLoading && !user)) {
    return (
      <nav className="sticky top-0 z-30 border-b border-border-subtle bg-page/90 backdrop-blur">
        <PageContainer className="flex h-12 items-center">
          <span className="font-heading text-sm font-semibold tracking-tight text-text-primary">Fathom</span>
        </PageContainer>
      </nav>
    );
  }
  const onTickerPage = pathname.startsWith("/tickers/");
  const sameTab = SAME_TAB_PREFIXES.some((p) => isUnder(pathname, p));

  return (
    <nav className="sticky top-0 z-30 border-b border-border-subtle bg-page/90 backdrop-blur">
      <PageContainer className="flex h-12 items-center gap-3">
        <Link href="/screener" {...(sameTab ? {} : NEW_TAB_PROPS)} className="font-heading shrink-0 text-sm font-semibold tracking-tight text-text-primary">
          Fathom
        </Link>
        {/* The page links never wrap and never slide under the search or the account block: every item is one line (`whitespace-nowrap`,
            `shrink-0`), and if the bar is still too narrow (below ~1100px) this group scrolls sideways instead (scrollbar hidden). It
            gives way last (`shrink-[0.1]`): the search field gives way first. */}
        <div className="flex min-w-0 shrink-[0.1] items-center gap-0.5 overflow-x-auto py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <span
            aria-current={onTickerPage ? "page" : undefined}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-md px-2 py-1.5 text-sm font-medium",
              onTickerPage ? "bg-surface-2 text-text-primary" : "text-text-tertiary"
            )}
          >
            Ticker Analysis
          </span>
          {NAV_LINKS.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <Fragment key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  {...(sameTab ? {} : NEW_TAB_PROPS)}
                  className={cn(
                    "shrink-0 whitespace-nowrap rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
                    active ? "bg-surface-2 text-text-primary" : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
                  )}
                >
                  {label}
                </Link>
                {href === MENUS_AFTER && (
                  <>
                    <NavMenu label="Investing" links={INVESTING_LINKS} pathname={pathname} sameTab={sameTab} />
                    <NavMenu label="Markets" links={MARKETS_LINKS} pathname={pathname} sameTab={sameTab} />
                  </>
                )}
              </Fragment>
            );
          })}
        </div>
        <div className="flex-1" />
        {/* The search field is the part that shrinks (176px down to 112px) when the bar is tight. */}
        <div className="w-44 min-w-28 shrink">
          <TickerSearch />
        </div>
        {user && (
          // The login id is the User menu's own label (truncated there); nothing else sits beside it.
          <div className="flex shrink-0 items-center" data-testid="account">
            <UserMenu pathname={pathname} sameTab={sameTab} isAdmin={isAdmin} loginId={user.username} onSignOut={() => void logout()} />
          </div>
        )}
      </PageContainer>
    </nav>
  );
}
