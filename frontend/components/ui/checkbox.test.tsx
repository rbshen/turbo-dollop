// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Checkbox } from "@/components/ui/checkbox";

afterEach(cleanup);

const boxOf = (input: HTMLElement) => input.nextElementSibling as HTMLElement;
const checkOf = (input: HTMLElement) => boxOf(input).nextElementSibling as HTMLElement;

describe("Checkbox: the default is neutral (there is no brand variant)", () => {
  it("paints the checked state text-primary with a dark check, never brand blue", () => {
    render(<Checkbox id="a" label="Exclude ETFs" />);
    const input = screen.getByLabelText("Exclude ETFs");
    expect(boxOf(input)).toHaveClass("peer-checked:border-text-primary", "peer-checked:bg-text-primary");
    expect(boxOf(input).className).not.toMatch(/peer-checked:\S*brand/); // (the focus ring is brand, by design)
    expect(checkOf(input)).toHaveClass("text-page");
    expect(checkOf(input).getAttribute("class")).not.toMatch(/on-brand/);
  });

  it("keeps the plain inline label and toggles like a native checkbox", () => {
    const onChange = vi.fn();
    render(<Checkbox id="a" label="Exclude ETFs" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Exclude ETFs"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const label = screen.getByText("Exclude ETFs").closest("label");
    expect(label).toHaveClass("inline-flex", "text-sm");
    expect(label).not.toHaveClass("h-8", "border");
  });

  it("is the same box as variant=\"neutral\"", () => {
    render(
      <>
        <Checkbox id="d" label="Default" />
        <Checkbox id="n" variant="neutral" label="Neutral" />
      </>,
    );
    expect(boxOf(screen.getByLabelText("Default")).className).toBe(boxOf(screen.getByLabelText("Neutral")).className);
  });
});

describe("Checkbox: neutral variant", () => {
  it("paints the checked state text-primary with a dark check, no brand blue", () => {
    render(<Checkbox id="n" variant="neutral" label="Keep last breached support" />);
    const input = screen.getByLabelText("Keep last breached support");
    expect(boxOf(input)).toHaveClass("peer-checked:border-text-primary", "peer-checked:bg-text-primary");
    expect(boxOf(input).className).not.toMatch(/peer-checked:\S*brand/);
    expect(checkOf(input)).toHaveClass("text-page");
    expect(checkOf(input)).not.toHaveClass("text-on-brand");
  });

  it("keeps the same focus ring as the default (peer-focus-visible, no outline-none)", () => {
    render(<Checkbox id="n" variant="neutral" label="x" />);
    const cls = boxOf(screen.getByLabelText("x")).className;
    expect(cls).toMatch(/peer-focus-visible:outline-2/);
    expect(cls).not.toMatch(/outline-none/);
  });

  it("checks and unchecks", () => {
    render(<Checkbox id="n" variant="neutral" label="x" />);
    const input = screen.getByLabelText("x") as HTMLInputElement;
    fireEvent.click(input);
    expect(input.checked).toBe(true);
  });
});

describe("Checkbox: chip variant", () => {
  it("is the neutral box inside a 32px radius-md chip that fills surface-2 when checked", () => {
    render(<Checkbox id="c" variant="chip" label="Speculative growth" />);
    const input = screen.getByLabelText("Speculative growth");
    const chip = input.closest("label");
    expect(chip).toHaveClass(
      "h-8",
      "rounded-md",
      "border",
      "border-border-input",
      "px-2",
      "text-xs",
      "font-medium",
      "text-text-secondary",
      "has-[:checked]:bg-surface-2",
      "has-[:checked]:text-text-primary",
    );
    expect(boxOf(input)).toHaveClass("peer-checked:bg-text-primary");
    expect(checkOf(input)).toHaveClass("text-page");
  });

  it("lets a caller override chip styling via className", () => {
    render(<Checkbox variant="chip" label="x" className="text-filter-active" />);
    expect(screen.getByText("x").closest("label")).toHaveClass("text-filter-active");
  });
});

describe("Checkbox: disabled and aria", () => {
  it("passes disabled and aria attributes to the input", () => {
    render(<Checkbox id="d" label="x" disabled aria-describedby="h" />);
    const input = screen.getByLabelText("x");
    expect(input).toBeDisabled();
    expect(input).toHaveAttribute("aria-describedby", "h");
    expect(screen.getByText("x").closest("label")).toHaveClass("has-[:disabled]:opacity-45");
  });
});

describe("Checkbox: no label prop (a Settings row names it)", () => {
  it("renders no wrapping <label>, so the row's label is the only accessible label", () => {
    render(<Checkbox id="bare" variant="neutral" />);
    const input = document.getElementById("bare") as HTMLInputElement;
    expect(input.closest("label")).toBeNull();
    expect(input.labels?.length).toBe(0);
  });

  it("covers the box with the input so a click on the box still toggles it", () => {
    render(<Checkbox id="bare" variant="neutral" />);
    const input = document.getElementById("bare") as HTMLInputElement;
    expect(input).toHaveClass("absolute", "inset-0", "h-full", "w-full", "opacity-0", "peer");
    expect(input).not.toHaveClass("sr-only");
    expect(boxOf(input)).toHaveClass("pointer-events-none", "peer-checked:bg-text-primary");
    expect(checkOf(input)).toHaveClass("pointer-events-none");
    fireEvent.click(input);
    expect(input.checked).toBe(true);
  });

  it("keeps the focus ring, the disabled dimming and the className on the wrapper", () => {
    render(<Checkbox id="bare" variant="neutral" disabled className="ml-2" />);
    const input = document.getElementById("bare") as HTMLInputElement;
    expect(input).toBeDisabled();
    expect(boxOf(input).className).toMatch(/peer-focus-visible:outline-2/);
    expect(input.parentElement).toHaveClass("has-[:disabled]:opacity-45", "ml-2");
  });

  it("keeps the labelled and chip forms unchanged (wrapping label, sr-only input)", () => {
    render(<Checkbox id="l" label="Exclude ETFs" />);
    const input = screen.getByLabelText("Exclude ETFs");
    expect(input.closest("label")).not.toBeNull();
    expect(input).toHaveClass("sr-only");
    cleanup();
    render(<Checkbox id="c" variant="chip" />);
    expect(document.getElementById("c")?.closest("label")).not.toBeNull();
  });
});
