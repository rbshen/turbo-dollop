// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SortHeader } from "@/components/ui/sort-header";

afterEach(cleanup);

describe("SortHeader", () => {
  it("shows no arrow and a tertiary label when inactive", () => {
    render(<SortHeader label="Ticker" active={false} onClick={() => {}} />);
    const button = screen.getByRole("button", { name: "Ticker" });
    expect(button).toHaveClass("text-text-tertiary");
    expect(button).not.toHaveClass("text-text-primary");
    expect(button.querySelector("svg")).not.toBeInTheDocument();
  });

  it("shows a primary label and an arrow when active", () => {
    render(<SortHeader label="Ticker" active direction="asc" onClick={() => {}} />);
    const button = screen.getByRole("button", { name: "Ticker" });
    expect(button).toHaveClass("text-text-primary");
    expect(button.querySelector("svg")).toBeInTheDocument();
  });

  it("shows the priority numeral only when given", () => {
    const { rerender } = render(<SortHeader label="Ticker" active direction="asc" onClick={() => {}} />);
    expect(screen.queryByText("2")).not.toBeInTheDocument();

    rerender(<SortHeader label="Ticker" active direction="asc" priority={2} onClick={() => {}} />);
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("calls onClick when clicked", () => {
    const onClick = vi.fn();
    render(<SortHeader label="Ticker" active={false} onClick={onClick} />);
    screen.getByRole("button", { name: "Ticker" }).click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
