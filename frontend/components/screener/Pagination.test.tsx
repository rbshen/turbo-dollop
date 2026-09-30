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

  it("calls onPage with the clicked page number", () => {
    const onPage = vi.fn();
    render(<Pagination page={1} nPages={3} onPage={onPage} />);
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    expect(onPage).toHaveBeenCalledWith(3);
  });
});
