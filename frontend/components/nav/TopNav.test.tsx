// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopNav } from "@/components/nav/TopNav";

// Characterization of the top nav: which item reads as the current page, and where each link goes. The search box is
// its own component with its own tests, so it is a stub here.
const h = vi.hoisted(() => ({ pathname: "/screener" }));
vi.mock("next/navigation", () => ({ usePathname: () => h.pathname }));
vi.mock("@/components/nav/TickerSearch", () => ({ TickerSearch: () => <div data-testid="search" /> }));

afterEach(cleanup);
beforeEach(() => {
  h.pathname = "/screener";
});

// How the current item is marked is the one markup-dependent part of this file.
function isCurrent(el: HTMLElement): boolean {
  return el.getAttribute("aria-current") === "page";
}

describe("TopNav", () => {
  it("links to every page, and opens all but the Screener in a new tab", () => {
    render(<TopNav />);
    const expected: [string, string, boolean][] = [
      ["Screener", "/screener", false],
      ["Watchlist", "/watchlist", true],
      ["Momentum", "/momentum", true],
      ["Sectors", "/sectors", true],
      ["Breadth", "/breadth", true],
      ["Settings", "/settings", true],
    ];
    for (const [name, href, newTab] of expected) {
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("href", href);
      if (newTab) expect(link).toHaveAttribute("target", "_blank");
      else expect(link).not.toHaveAttribute("target");
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

  it("leaves Screener and already-modified clicks alone", () => {
    render(<TopNav />);
    expect(fireEvent.click(screen.getByRole("link", { name: "Screener" }), { defaultPrevented: false })).toBeDefined();
    expect(fireEvent.click(screen.getByRole("link", { name: "Momentum" }), { ctrlKey: true })).toBe(true);
  });

  it.each(["/momentum", "/sectors", "/breadth", "/breadth/XLK", "/settings"])(
    "on %s, Screener and the logo open in a new tab too",
    (path) => {
      h.pathname = path;
      render(<TopNav />);
      for (const name of ["Fathom", "Screener"]) {
        expect(screen.getByRole("link", { name })).toHaveAttribute("target", "_blank");
      }
    }
  );

  it("marks the link for the current page and no other", () => {
    h.pathname = "/momentum";
    render(<TopNav />);
    expect(isCurrent(screen.getByRole("link", { name: "Momentum" }))).toBe(true);
    for (const name of ["Screener", "Watchlist", "Sectors", "Breadth", "Settings"]) {
      expect(isCurrent(screen.getByRole("link", { name }))).toBe(false);
    }
    expect(isCurrent(screen.getByText("Ticker Analysis"))).toBe(false);
  });

  it("marks Ticker Analysis (not a link) on a ticker page, and no link", () => {
    h.pathname = "/tickers/AAPL";
    render(<TopNav />);
    expect(isCurrent(screen.getByText("Ticker Analysis"))).toBe(true);
    expect(screen.queryByRole("link", { name: "Ticker Analysis" })).not.toBeInTheDocument();
    for (const name of ["Screener", "Watchlist", "Momentum", "Sectors", "Breadth", "Settings"]) {
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
    expect(screen.getByRole("link", { name: "Screener" })).not.toHaveClass("bg-surface-2");
    expect(container.innerHTML).not.toMatch(/(bg|text|border)-brand/);
  });

  it("draws Ticker Analysis the same way on a ticker page, and aria-current is on one element only", () => {
    h.pathname = "/tickers/AAPL";
    const { container } = render(<TopNav />);
    expect(screen.getByText("Ticker Analysis")).toHaveClass("bg-surface-2", "text-text-primary");
    expect(container.querySelectorAll("[aria-current]")).toHaveLength(1);
  });
});
