// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Field, Input } from "@/components/ui/input";

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

describe("Field", () => {
  it("wires the label to the input via htmlFor/id", () => {
    render(
      <Field label="Ticker" htmlFor="field-ticker">
        <Input id="field-ticker" />
      </Field>,
    );
    expect(screen.getByLabelText("Ticker")).toBe(screen.getByRole("textbox"));
  });
});

describe("Input: existing behaviour is unchanged unless a new prop is passed", () => {
  it("keeps the underline defaults with no size and no invalid style", () => {
    render(<Input aria-label="Ticker" />);
    const el = screen.getByLabelText("Ticker");
    expect(el).toHaveClass("h-8", "rounded-none", "border-b", "border-border-control");
    expect(el).not.toHaveClass("w-24", "border-negative");
    expect(el).not.toHaveAttribute("aria-invalid");
    expect(el).not.toHaveAttribute("aria-describedby");
  });

  it("keeps the boxed defaults (h-9, radius-md, page fill)", () => {
    render(<Input variant="boxed" aria-label="Search" />);
    expect(screen.getByLabelText("Search")).toHaveClass("h-9", "rounded-md", "bg-page", "px-3");
    expect(screen.getByLabelText("Search")).not.toHaveClass("w-full");
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

describe("Input: opt-in size tokens and invalid style", () => {
  it.each([
    ["short", "w-24"],
    ["medium", "w-44"],
    ["wide", "w-80"],
    ["full", "w-full"],
  ] as const)("size %s adds %s and a 36px height on either variant", (size, cls) => {
    render(
      <>
        <Input variant="boxed" size={size} aria-label="Boxed" />
        <Input variant="underline" size={size} aria-label="Underline" />
      </>,
    );
    for (const name of ["Boxed", "Underline"]) {
      expect(screen.getByLabelText(name)).toHaveClass(cls, "h-9");
      expect(screen.getByLabelText(name)).not.toHaveClass("h-8");
    }
    if (size !== "full") expect(screen.getByLabelText("Boxed")).toHaveClass("max-w-full");
  });

  it("invalid sets aria-invalid and swaps the border colour", () => {
    render(<Input variant="boxed" invalid aria-label="Bad" />);
    const el = screen.getByLabelText("Bad");
    expect(el).toHaveAttribute("aria-invalid", "true");
    expect(el).toHaveClass("border-negative");
    expect(el).not.toHaveClass("border-border-control");
  });

  it("never sets focus:outline-none", () => {
    render(<Input variant="boxed" size="short" invalid aria-label="Any" />);
    expect(screen.getByLabelText("Any").className).not.toMatch(/outline-none/);
  });
});
