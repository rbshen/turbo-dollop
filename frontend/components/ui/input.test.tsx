// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Input } from "@/components/ui/input";

afterEach(cleanup);

describe("Input", () => {
  it("applies mono/tabular-nums styling for type=\"number\"", () => {
    render(<Input type="number" aria-label="Shares" defaultValue={100} />);
    expect(screen.getByLabelText("Shares")).toHaveClass("font-mono", "tabular-nums");
  });

  it("does not apply the number styling for a plain text input", () => {
    render(<Input aria-label="Ticker" />);
    expect(screen.getByLabelText("Ticker")).not.toHaveClass("font-mono");
  });
});

describe("Input: the boxed field, the only style", () => {
  it("is 36px, radius-md, 1px border-control, page fill, with no width token by default", () => {
    render(<Input aria-label="Search" />);
    const el = screen.getByLabelText("Search");
    expect(el).toHaveClass("h-9", "rounded-md", "border", "border-border-control", "bg-page", "px-3");
    expect(el).not.toHaveClass("w-full", "w-24", "border-negative", "rounded-none", "border-b");
    expect(el).not.toHaveAttribute("aria-invalid");
    expect(el).not.toHaveAttribute("aria-describedby");
  });

  it("still passes id, disabled and aria-* straight through", () => {
    render(<Input id="x" aria-label="Ticker" disabled aria-describedby="d" aria-invalid />);
    const el = screen.getByLabelText("Ticker");
    expect(el).toHaveAttribute("id", "x");
    expect(el).toBeDisabled();
    expect(el).toHaveAttribute("aria-describedby", "d");
    expect(el).toHaveAttribute("aria-invalid", "true");
  });
});

describe("Input: size tokens and invalid style", () => {
  it.each([
    ["short", "w-24"],
    ["medium", "w-44"],
    ["wide", "w-80"],
    ["full", "w-full"],
  ] as const)("size %s adds %s and keeps the 36px height", (size, cls) => {
    render(<Input size={size} aria-label="Boxed" />);
    expect(screen.getByLabelText("Boxed")).toHaveClass(cls, "h-9");
    if (size !== "full") expect(screen.getByLabelText("Boxed")).toHaveClass("max-w-full");
  });

  it("invalid sets aria-invalid and swaps the border colour", () => {
    render(<Input invalid aria-label="Bad" />);
    const el = screen.getByLabelText("Bad");
    expect(el).toHaveAttribute("aria-invalid", "true");
    expect(el).toHaveClass("border-negative");
    expect(el).not.toHaveClass("border-border-control");
  });

  it("never sets focus:outline-none", () => {
    render(<Input size="short" invalid aria-label="Any" />);
    expect(screen.getByLabelText("Any").className).not.toMatch(/outline-none/);
  });
});
