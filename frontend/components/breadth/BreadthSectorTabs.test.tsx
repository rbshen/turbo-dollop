// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BreadthSectorTabs } from "@/components/breadth/BreadthSectorTabs";

// Characterization of the 12-entry link strip: the tab semantics, the hrefs and which entry is selected.
afterEach(cleanup);

describe("BreadthSectorTabs", () => {
  it("is a named tablist of 12 links: S&P 500 first, then the 11 sector ETFs", () => {
    render(<BreadthSectorTabs active="sp500" />);
    expect(screen.getByRole("tablist", { name: "Market breadth universe" })).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(12);
    expect(tabs[0]).toHaveTextContent("S&P 500");
    expect(tabs[0]).toHaveAttribute("href", "/breadth");
    expect(tabs[1]).toHaveAttribute("href", `/breadth/${tabs[1].textContent}`);
  });

  it("selects the entry that is active, and only it", () => {
    render(<BreadthSectorTabs active="XLK" />);
    const selected = screen.getAllByRole("tab").filter((t) => t.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent("XLK");
  });

  it("selects S&P 500 for 'sp500', and nothing for an unrecognised value", () => {
    const { unmount } = render(<BreadthSectorTabs active="sp500" />);
    expect(screen.getByRole("tab", { name: "S&P 500" })).toHaveAttribute("aria-selected", "true");
    unmount();
    render(<BreadthSectorTabs active="nope" />);
    expect(screen.getAllByRole("tab").every((t) => t.getAttribute("aria-selected") === "false")).toBe(true);
  });

  it("gives each sector tab its full name as a title", () => {
    render(<BreadthSectorTabs active="sp500" />);
    expect(screen.getByRole("tab", { name: "XLK" })).toHaveAttribute("title", expect.stringMatching(/technology/i));
  });
});

// Session 16: the selected link tab is neutral (surface-2 and text-primary), says so with aria-current as well as
// aria-selected, and a hover never looks selected.
describe("BreadthSectorTabs: the selected tab is neutral", () => {
  it("draws the selected tab with surface-2 and text-primary and marks it aria-current, with no brand blue", () => {
    const { container } = render(<BreadthSectorTabs active="XLK" />);
    const selected = screen.getByRole("tab", { name: "XLK" });
    expect(selected).toHaveClass("bg-surface-2", "text-text-primary");
    expect(selected).toHaveAttribute("aria-current", "page");
    expect(container.querySelectorAll("[aria-current]")).toHaveLength(1);
    expect(container.innerHTML).not.toMatch(/(bg|text|border)-brand/);
  });

  it("gives an unselected tab a text-only hover, so it never takes the selected fill", () => {
    render(<BreadthSectorTabs active="XLK" />);
    const other = screen.getByRole("tab", { name: "XLF" });
    expect(other).toHaveClass("text-text-tertiary", "hover:text-text-primary");
    expect(other.className).not.toMatch(/bg-surface-2/);
  });
});
