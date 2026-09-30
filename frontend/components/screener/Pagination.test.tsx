// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Pagination } from "@/components/screener/Pagination";

afterEach(cleanup);

// Regression test for the session-5c move onto the shared Button --
// confirms the active page keeps the dark-on-brand contrast fix
// (bg-brand text-on-brand) rather than regressing to white text, and that
// Prev/Next disable at the ends and page clicks still report the right
// page number, unchanged from the pre-migration implementation.
describe("Pagination", () => {
  it("renders nothing for a single page", () => {
    const { container } = render(<Pagination page={1} nPages={1} onPage={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("gives the active page button the dark-on-brand classes, not white text", () => {
    render(<Pagination page={2} nPages={5} onPage={() => {}} />);
    const active = screen.getByRole("button", { name: "2" });
    expect(active.className).toContain("bg-brand");
    expect(active.className).toContain("text-on-brand");
    expect(active.className).not.toContain("text-white");
  });

  it("disables Prev on the first page and Next on the last page", () => {
    render(<Pagination page={1} nPages={3} onPage={() => {}} />);
    expect(screen.getByRole("button", { name: "« Prev" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next »" })).not.toBeDisabled();
  });

  it("disables Next on the last page and Prev is live there", () => {
    render(<Pagination page={3} nPages={3} onPage={() => {}} />);
    expect(screen.getByRole("button", { name: "Next »" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "« Prev" })).not.toBeDisabled();
  });

  it("Prev and Next report the neighbouring pages", () => {
    const onPage = vi.fn();
    render(<Pagination page={4} nPages={9} onPage={onPage} />);
    fireEvent.click(screen.getByRole("button", { name: "« Prev" }));
    fireEvent.click(screen.getByRole("button", { name: "Next »" }));
    expect(onPage.mock.calls).toEqual([[3], [5]]);
  });

  it("a disabled Prev or Next does not report a page", () => {
    const onPage = vi.fn();
    render(<Pagination page={1} nPages={2} onPage={onPage} />);
    fireEvent.click(screen.getByRole("button", { name: "« Prev" }));
    expect(onPage).not.toHaveBeenCalled();
  });

  it("calls onPage with the clicked page number", () => {
    const onPage = vi.fn();
    render(<Pagination page={1} nPages={3} onPage={onPage} />);
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    expect(onPage).toHaveBeenCalledWith(3);
  });
});

// The page window: the first and last page always, the current page plus or
// minus two, and a single "…" wherever pages are skipped.
describe("Pagination: the page window", () => {
  function windowOf(page: number, nPages: number): string[] {
    const { container, unmount } = render(<Pagination page={page} nPages={nPages} onPage={() => {}} />);
    const tokens = Array.from(container.firstElementChild!.children)
      .map((el) => el.textContent?.trim() ?? "")
      .filter((t) => /^(\d+|…)$/.test(t));
    unmount();
    return tokens;
  }

  it.each([
    [1, 10, ["1", "2", "3", "…", "10"]],
    [3, 10, ["1", "2", "3", "4", "5", "…", "10"]],
    [4, 10, ["1", "2", "3", "4", "5", "6", "…", "10"]],
    [5, 10, ["1", "…", "3", "4", "5", "6", "7", "…", "10"]],
    [8, 10, ["1", "…", "6", "7", "8", "9", "10"]],
    [10, 10, ["1", "…", "8", "9", "10"]],
    [2, 5, ["1", "2", "3", "4", "5"]],
    [3, 7, ["1", "2", "3", "4", "5", "…", "7"]],
  ])("page %i of %i shows %j", (page, nPages, expected) => {
    expect(windowOf(page, nPages)).toEqual(expected);
  });

  it("never shows an ellipsis when every page fits", () => {
    expect(windowOf(3, 5)).not.toContain("…");
  });

  it("renders no pagination at all for 0 or 1 pages", () => {
    const { container } = render(<Pagination page={1} nPages={0} onPage={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
