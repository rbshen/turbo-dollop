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

// Markets is a menu: its links exist in the DOM only while it is open. Base UI treats a click with no pointer detail as a keyboard
// activation, which opens the menu.
function openMarkets() {
  fireEvent.click(screen.getByRole("button", { name: "Markets" }));
  return screen.findAllByRole("menuitem");
}

describe("TopNav", () => {
  it("links to every page, and opens each in a new tab", async () => {
    render(<TopNav />);
    const expected: [string, string][] = [
      ["Fathom", "/screener"],
      ["Stocks", "/screener"],
      ["ETFs", "/etfs"],
      ["Watchlist", "/watchlist"],
      ["Opportunities", "/opportunities"],
      ["Momentum", "/momentum"],
      ["Settings", "/settings"],
    ];
    for (const [name, href] of expected) {
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("href", href);
      expect(link).toHaveAttribute("target", "_blank");
    }
    const items = await openMarkets();
    for (const [name, href] of [["Sectors", "/sectors"], ["Breadth", "/breadth"]]) {
      const item = items.find((el) => el.textContent === name)!;
      expect(item).toHaveAttribute("href", href);
      expect(item).toHaveAttribute("target", "_blank");
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
    async (path) => {
      h.pathname = path;
      render(<TopNav />);
      for (const link of [...screen.getAllByRole("link"), ...(await openMarkets())]) {
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
    for (const name of ["Stocks", "ETFs", "Watchlist", "Settings"]) {
      expect(isCurrent(screen.getByRole("link", { name }))).toBe(false);
    }
    expect(isCurrent(screen.getByRole("button", { name: "Markets" }))).toBe(false);
    expect(isCurrent(screen.getByText("Ticker Analysis"))).toBe(false);
  });

  it("lists the pages in order: Stocks, ETFs, Watchlist, then the rest", () => {
    render(<TopNav />);
    const labels = screen.getAllByRole("link").map((a) => a.textContent);
    expect(labels).toEqual(["Fathom", "Stocks", "ETFs", "Watchlist", "Opportunities", "Momentum", "Settings"]);
    expect(screen.queryByRole("link", { name: "Screener" })).not.toBeInTheDocument();
  });

  it("marks ETFs (and only ETFs) on /etfs", () => {
    h.pathname = "/etfs";
    render(<TopNav />);
    expect(isCurrent(screen.getByRole("link", { name: "ETFs" }))).toBe(true);
    for (const name of ["Stocks", "Watchlist", "Momentum", "Settings"]) {
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
    for (const name of ["Stocks", "ETFs", "Watchlist", "Momentum", "Settings"]) {
      expect(isCurrent(screen.getByRole("link", { name }))).toBe(false);
    }
    expect(isCurrent(screen.getByRole("button", { name: "Markets" }))).toBe(false);
  });
});

describe("TopNav: the Markets dropdown", () => {
  it("is a menu button, not a link, sitting between Momentum and Settings", () => {
    render(<TopNav />);
    const trigger = screen.getByRole("button", { name: "Markets" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("href");
    expect(screen.queryByRole("link", { name: "Sectors" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Breadth" })).toBeNull();
    const order = [...document.querySelectorAll("nav a, nav button")].map((el) => el.textContent);
    expect(order.indexOf("Momentum")).toBeLessThan(order.indexOf("Markets"));
    expect(order.indexOf("Markets")).toBeLessThan(order.indexOf("Settings"));
  });

  it("lists Sectors then Breadth once opened", async () => {
    render(<TopNav />);
    const items = await openMarkets();
    expect(items.map((i) => i.textContent)).toEqual(["Sectors", "Breadth"]);
    expect(screen.getByRole("button", { name: "Markets" })).toHaveAttribute("aria-expanded", "true");
  });

  it.each([
    ["/sectors", "Sectors"],
    ["/breadth", "Breadth"],
    ["/breadth/XLK", "Breadth"],
  ])("on %s, marks Markets and the %s item", async (path, item) => {
    h.pathname = path;
    render(<TopNav />);
    const trigger = screen.getByRole("button", { name: "Markets" });
    expect(isCurrent(trigger)).toBe(true);
    expect(trigger).toHaveClass("bg-surface-2", "text-text-primary");
    const items = await openMarkets();
    for (const el of items) expect(isCurrent(el)).toBe(el.textContent === item);
  });

  it("does not mark Markets on another page, and leaves its items unmarked", async () => {
    h.pathname = "/momentum";
    render(<TopNav />);
    expect(isCurrent(screen.getByRole("button", { name: "Markets" }))).toBe(false);
    for (const el of await openMarkets()) expect(isCurrent(el)).toBe(false);
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    render(<TopNav />);
    const trigger = screen.getByRole("button", { name: "Markets" });
    const [first] = await openMarkets();
    await waitFor(() => expect(first).toHaveFocus());
    fireEvent.keyDown(first, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menuitem")).toBeNull());
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("moves between items with the arrow keys", async () => {
    render(<TopNav />);
    const [sectors, breadth] = await openMarkets();
    await waitFor(() => expect(sectors).toHaveFocus());
    fireEvent.keyDown(sectors, { key: "ArrowDown" });
    await waitFor(() => expect(breadth).toHaveFocus());
    fireEvent.keyDown(breadth, { key: "ArrowUp" });
    await waitFor(() => expect(sectors).toHaveFocus());
  });

  it("closes when an item is selected", async () => {
    render(<TopNav />);
    const [sectors] = await openMarkets();
    const spy = (e: Event) => e.preventDefault(); // jsdom has no navigation
    document.addEventListener("click", spy);
    fireEvent.click(sectors);
    document.removeEventListener("click", spy);
    await waitFor(() => expect(screen.queryByRole("menuitem")).toBeNull());
  });

  it("closes on an outside click", async () => {
    render(<TopNav />);
    await openMarkets();
    fireEvent.pointerDown(document.body);
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);
    await waitFor(() => expect(screen.queryByRole("menuitem")).toBeNull());
  });
});

// Session 16: the current page is neutral (a surface-2 fill with text-primary) and says so with aria-current, never brand blue.
describe("TopNav: the current item is neutral", () => {
  it("draws the current link with surface-2 and text-primary, and no brand blue anywhere in the nav", () => {
    h.pathname = "/momentum";
    const { container } = render(<TopNav />);
    const current = screen.getByRole("link", { name: "Momentum" });
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
    expect(labels).toEqual(["Fathom", "Stocks", "ETFs", "Watchlist", "Opportunities", "Momentum", "Settings"]);
    expect(screen.getByRole("button", { name: "Markets" })).toBeInTheDocument();
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
    for (const el of [...screen.getAllByRole("link").slice(1), screen.getByRole("button", { name: "Markets" }), screen.getByText("Ticker Analysis")]) {
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
