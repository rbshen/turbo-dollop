// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopNav as BareTopNav } from "@/components/nav/TopNav";
import { TestAuth } from "@/lib/auth/testAuth";

// Characterization of the top nav: which item reads as the current page, and where each link goes. The search box is
// its own component with its own tests, so it is a stub here.
const h = vi.hoisted(() => ({ pathname: "/screener" }));
vi.mock("next/navigation", () => ({ usePathname: () => h.pathname }));
vi.mock("@/components/nav/TickerSearch", () => ({ TickerSearch: () => <div data-testid="search" /> }));

afterEach(cleanup);
beforeEach(() => {
  h.pathname = "/screener";
});

// Every test below draws the bar for a signed-in admin; the account block has its own describe at the end.
function TopNav() {
  return (
    <TestAuth role="admin">
      <BareTopNav />
    </TestAuth>
  );
}

// How the current item is marked is the one markup-dependent part of this file.
function isCurrent(el: HTMLElement): boolean {
  return el.getAttribute("aria-current") === "page";
}

describe("TopNav", () => {
  it("links to every page, and opens each in a new tab", () => {
    render(<TopNav />);
    const expected: [string, string][] = [
      ["Fathom", "/screener"],
      ["Stocks", "/screener"],
      ["ETFs", "/etfs"],
      ["Watchlist", "/watchlist"],
      ["Opportunities", "/opportunities"],
      ["Momentum", "/momentum"],
      ["Sectors", "/sectors"],
      ["Breadth", "/breadth"],
      ["Settings", "/settings"],
    ];
    for (const [name, href] of expected) {
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("href", href);
      expect(link).toHaveAttribute("target", "_blank");
    }
  });

  it("replays a plain click on a new-tab link as a modifier-click, so the tab opens in the background", () => {
    render(<TopNav />);
    const seen: MouseEvent[] = [];
    const spy = (e: Event) => {
      seen.push(e as MouseEvent);
      e.preventDefault(); // jsdom has no navigation
    };
    document.addEventListener("click", spy);
    const notPrevented = fireEvent.click(screen.getByRole("link", { name: "Momentum" }));
    document.removeEventListener("click", spy);
    expect(notPrevented).toBe(false); // the original click is cancelled...
    const replay = seen.find((e) => e.ctrlKey || e.metaKey);
    expect(replay).toBeDefined(); // ...and replayed with a modifier
    expect((replay!.target as HTMLAnchorElement).target).toBe("_blank");
  });

  it("leaves already-modified clicks alone", () => {
    render(<TopNav />);
    expect(fireEvent.click(screen.getByRole("link", { name: "Momentum" }), { ctrlKey: true })).toBe(true);
  });

  it.each(["/screener", "/etfs", "/watchlist", "/tickers/AAPL"])("on %s, every nav link and the logo open in a new tab", (path) => {
    h.pathname = path;
    render(<TopNav />);
    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveAttribute("target", "_blank");
    }
  });

  it.each(["/opportunities", "/momentum", "/sectors", "/breadth", "/breadth/XLK", "/settings"])(
    "on %s, every nav link and the logo navigate in the same tab",
    (path) => {
      h.pathname = path;
      render(<TopNav />);
      for (const link of screen.getAllByRole("link")) {
        expect(link).not.toHaveAttribute("target");
      }
      const seen: MouseEvent[] = [];
      const spy = (e: Event) => {
        seen.push(e as MouseEvent);
        e.preventDefault(); // jsdom has no navigation
      };
      document.addEventListener("click", spy);
      fireEvent.click(screen.getByRole("link", { name: "Stocks" }));
      document.removeEventListener("click", spy);
      expect(seen).toHaveLength(1); // no replayed background-tab click
    }
  );

  it("marks the link for the current page and no other", () => {
    h.pathname = "/momentum";
    render(<TopNav />);
    expect(isCurrent(screen.getByRole("link", { name: "Momentum" }))).toBe(true);
    for (const name of ["Stocks", "ETFs", "Watchlist", "Sectors", "Breadth", "Settings"]) {
      expect(isCurrent(screen.getByRole("link", { name }))).toBe(false);
    }
    expect(isCurrent(screen.getByText("Ticker Analysis"))).toBe(false);
  });

  it("lists the pages in order: Stocks, ETFs, Watchlist, then the rest", () => {
    render(<TopNav />);
    const labels = screen.getAllByRole("link").map((a) => a.textContent);
    expect(labels).toEqual(["Fathom", "Stocks", "ETFs", "Watchlist", "Opportunities", "Momentum", "Sectors", "Breadth", "Settings"]);
    expect(screen.queryByRole("link", { name: "Screener" })).not.toBeInTheDocument();
  });

  it("marks ETFs (and only ETFs) on /etfs", () => {
    h.pathname = "/etfs";
    render(<TopNav />);
    expect(isCurrent(screen.getByRole("link", { name: "ETFs" }))).toBe(true);
    for (const name of ["Stocks", "Watchlist", "Momentum", "Sectors", "Breadth", "Settings"]) {
      expect(isCurrent(screen.getByRole("link", { name }))).toBe(false);
    }
  });

  it("marks Stocks on /screener, and the logo keeps linking to the home page's route", () => {
    render(<TopNav />);
    expect(isCurrent(screen.getByRole("link", { name: "Stocks" }))).toBe(true);
    expect(isCurrent(screen.getByRole("link", { name: "ETFs" }))).toBe(false);
    expect(screen.getByRole("link", { name: "Fathom" })).toHaveAttribute("href", "/screener");
  });

  it("marks Ticker Analysis (not a link) on a ticker page, and no link", () => {
    h.pathname = "/tickers/AAPL";
    render(<TopNav />);
    expect(isCurrent(screen.getByText("Ticker Analysis"))).toBe(true);
    expect(screen.queryByRole("link", { name: "Ticker Analysis" })).not.toBeInTheDocument();
    for (const name of ["Stocks", "ETFs", "Watchlist", "Momentum", "Sectors", "Breadth", "Settings"]) {
      expect(isCurrent(screen.getByRole("link", { name }))).toBe(false);
    }
  });

  it("matches the path exactly, so /breadth/XLK does not mark Breadth", () => {
    h.pathname = "/breadth/XLK";
    render(<TopNav />);
    expect(isCurrent(screen.getByRole("link", { name: "Breadth" }))).toBe(false);
  });
});

// Session 16: the current page is neutral (a surface-2 fill with text-primary) and says so with aria-current, never brand blue.
describe("TopNav: the current item is neutral", () => {
  it("draws the current link with surface-2 and text-primary, and no brand blue anywhere in the nav", () => {
    h.pathname = "/sectors";
    const { container } = render(<TopNav />);
    const current = screen.getByRole("link", { name: "Sectors" });
    expect(current).toHaveClass("bg-surface-2", "text-text-primary");
    expect(screen.getByRole("link", { name: "Stocks" })).not.toHaveClass("bg-surface-2");
    expect(container.innerHTML).not.toMatch(/(bg|text|border)-brand/);
  });

  it("draws Ticker Analysis the same way on a ticker page, and aria-current is on one element only", () => {
    h.pathname = "/tickers/AAPL";
    const { container } = render(<TopNav />);
    expect(screen.getByText("Ticker Analysis")).toHaveClass("bg-surface-2", "text-text-primary");
    expect(container.querySelectorAll("[aria-current]")).toHaveLength(1);
  });
});

describe("TopNav: the account block", () => {
  const draw = (role: "admin" | "viewer" | null, extra: { loading?: boolean; logout?: () => Promise<void> } = {}) =>
    render(
      <TestAuth role={role} username="ann" loading={extra.loading} overrides={extra.logout ? { logout: extra.logout } : undefined}>
        <BareTopNav />
      </TestAuth>,
    );

  it("shows the username, the role and a Sign out button", () => {
    draw("viewer");
    expect(screen.getByTestId("account")).toHaveTextContent("ann");
    expect(screen.getByTestId("account")).toHaveTextContent("viewer");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("shows every nav link to a viewer too (hides nothing)", () => {
    draw("viewer");
    const labels = screen.getAllByRole("link").map((a) => a.textContent);
    expect(labels).toEqual(["Fathom", "Stocks", "ETFs", "Watchlist", "Opportunities", "Momentum", "Sectors", "Breadth", "Settings"]);
  });

  it("signs out through the provider", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    draw("admin", { logout });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
  });

  it("keeps the full bar, without an account block, while the session is being checked", () => {
    draw(null, { loading: true });
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByTestId("account")).toBeNull();
  });

  it("shows only the name for a signed-out visitor", () => {
    draw(null);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByTestId("search")).toBeNull();
    expect(screen.getByText("Fathom")).toBeInTheDocument();
  });

  it("shows only the name on the login page, even while loading", () => {
    h.pathname = "/login";
    draw(null, { loading: true });
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByTestId("search")).toBeNull();
  });
});

// Layout guard: jsdom does no layout, so these pin the classes that keep the bar from wrapping, overlapping or pushing Settings out
// of view. They are not a substitute for looking at the bar at 1280 and 1366px (see the 2026-10-13 decision).
describe("TopNav: the bar does not wrap or overlap", () => {
  const draw = (role: "admin" | "viewer") =>
    render(
      <TestAuth role={role} username="ann">
        <BareTopNav />
      </TestAuth>,
    );

  it("keeps every label, Ticker Analysis included, on one line and unshrinkable", () => {
    draw("admin");
    for (const el of [...screen.getAllByRole("link").slice(1), screen.getByText("Ticker Analysis")]) {
      expect(el).toHaveClass("whitespace-nowrap", "shrink-0");
    }
  });

  it("lets the link group scroll sideways rather than run under the search or account block", () => {
    draw("admin");
    const group = screen.getByRole("link", { name: "Settings" }).parentElement!;
    expect(group).toHaveClass("min-w-0", "overflow-x-auto");
    expect(group).not.toHaveClass("shrink-0");
  });

  it("makes the search field the part that shrinks, and keeps the account block fixed", () => {
    draw("admin");
    const search = screen.getByTestId("search").parentElement!;
    expect(search).toHaveClass("shrink", "min-w-28");
    expect(screen.getByTestId("account")).toHaveClass("shrink-0");
  });

  it.each(["admin", "viewer"] as const)("collapses the account block for a %s: role word on 2xl only, username to its initial below lg", (role) => {
    draw(role);
    const account = screen.getByTestId("account");
    const roleWord = screen.getByText(role);
    expect(roleWord).toHaveClass("sr-only", "2xl:not-sr-only"); // still in the accessibility tree, drawn from 2xl
    expect(screen.getByText("ann")).toHaveClass("sr-only", "lg:not-sr-only");
    const initial = account.querySelector('[aria-hidden="true"]')!;
    expect(initial).toHaveTextContent("a");
    expect(initial).toHaveClass("lg:hidden");
    expect(account.querySelector("[title]")).toHaveAttribute("title", `ann (${role})`);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  it("keeps Settings, the search field and Sign out in the bar together", () => {
    draw("viewer");
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByTestId("search")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
