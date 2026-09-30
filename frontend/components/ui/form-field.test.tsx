// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/Select";

afterEach(cleanup);

describe("FormField", () => {
  it("renders a real label wired to the control by htmlFor", () => {
    render(
      <FormField label="RS benchmark" htmlFor="bm">
        <Input />
      </FormField>,
    );
    const input = screen.getByLabelText("RS benchmark");
    expect(input).toBe(screen.getByRole("textbox"));
    expect(screen.getByText("RS benchmark").tagName).toBe("LABEL");
  });

  it("puts the hint directly under the label and links it with aria-describedby", () => {
    render(
      <FormField label="RS benchmark" htmlFor="bm" hint="The index each stock is compared against.">
        <Input />
      </FormField>,
    );
    const label = screen.getByText("RS benchmark");
    const hint = screen.getByText("The index each stock is compared against.");
    expect(label.nextElementSibling).toBe(hint);
    expect(hint).toHaveAttribute("id", "bm-hint");
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-describedby", "bm-hint");
  });

  it("renders the unit as a suffix after the control and describes the control with it", () => {
    render(
      <FormField label="MA length" htmlFor="ma" unit="weeks">
        <Input />
      </FormField>,
    );
    const input = screen.getByRole("textbox");
    const unit = screen.getByText("weeks");
    expect(input.compareDocumentPosition(unit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(input.getAttribute("aria-describedby")).toBe("ma-unit");
  });

  it("shows an error with role=alert under the field, marks the control invalid and links it", () => {
    render(
      <FormField label="MA length" htmlFor="ma" hint="A hint." error="Enter a number.">
        <Input />
      </FormField>,
    );
    const input = screen.getByRole("textbox");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Enter a number.");
    expect(alert).toHaveAttribute("id", "ma-error");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveClass("border-negative");
    expect(input.getAttribute("aria-describedby")).toBe("ma-hint ma-error");
    expect(input.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("has no aria-describedby, alert or invalid state when there is nothing to describe", () => {
    render(
      <FormField label="Ticker" htmlFor="t">
        <Input />
      </FormField>,
    );
    const input = screen.getByRole("textbox");
    expect(input).not.toHaveAttribute("aria-describedby");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("disables the control and dims the label and hint", () => {
    render(
      <FormField label="Breach recency" htmlFor="br" hint="A hint." disabled>
        <Input />
      </FormField>,
    );
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByText("Breach recency")).toHaveClass("opacity-45");
    expect(screen.getByText("A hint.")).toHaveClass("opacity-45");
  });

  it("wires a Select the same way", () => {
    render(
      <FormField label="MA type" htmlFor="mt" hint="EMA reacts faster." error="Pick one.">
        <Select size="medium">
          <option>EMA</option>
        </Select>
      </FormField>,
    );
    const select = screen.getByLabelText("MA type");
    expect(select.getAttribute("aria-describedby")).toBe("mt-hint mt-error");
    expect(select).toHaveAttribute("aria-invalid", "true");
  });

  it("lets a prop on the control win over the field's wiring", () => {
    render(
      <FormField label="MA length" htmlFor="ma" hint="A hint.">
        <Input aria-describedby="mine" />
      </FormField>,
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-describedby", "mine");
  });
});

describe("FormField: compact density", () => {
  it("is text-xs text-secondary with a 2px gap to the control", () => {
    const { container } = render(
      <FormField label="Quote" htmlFor="q" density="compact">
        <Input />
      </FormField>,
    );
    const label = screen.getByText("Quote");
    expect(label.tagName).toBe("LABEL");
    expect(label).toHaveClass("text-xs", "text-text-secondary");
    expect(label).not.toHaveClass("text-sm");
    expect(container.firstElementChild).toHaveClass("gap-0.5");
    expect(screen.getByLabelText("Quote")).toBe(screen.getByRole("textbox"));
  });

  it("puts the unit in the label row, right-aligned in text-tertiary, not after the control", () => {
    render(
      <FormField label="Mkt cap" htmlFor="m" density="compact" unit="USD">
        <Input />
      </FormField>,
    );
    const label = screen.getByText("Mkt cap");
    const unit = screen.getByText("USD");
    expect(unit.parentElement).toBe(label.parentElement);
    expect(label.parentElement).toHaveClass("justify-between");
    expect(unit).toHaveClass("text-xs", "text-text-tertiary");
    expect(unit.parentElement?.nextElementSibling?.contains(screen.getByRole("textbox"))).toBe(true);
    expect(screen.getByRole("textbox").getAttribute("aria-describedby")).toBe("m-unit");
  });

  it("turns the label orange when applied, and leaves the unit tertiary", () => {
    render(
      <FormField label="P/E" htmlFor="pe" density="compact" unit="x" applied>
        <Input />
      </FormField>,
    );
    expect(screen.getByText("P/E")).toHaveClass("text-filter-active");
    expect(screen.getByText("P/E")).not.toHaveClass("text-text-secondary");
    expect(screen.getByText("x")).toHaveClass("text-text-tertiary");
  });

  it("shows an optional hint under the control (it wraps, never clips), linked by aria-describedby", () => {
    render(
      <FormField label="Mkt cap" htmlFor="m" density="compact" hint="e.g. 500M, 2B, 1T">
        <Input />
      </FormField>,
    );
    const hint = screen.getByText("e.g. 500M, 2B, 1T");
    expect(hint).toHaveClass("text-xs", "text-text-tertiary");
    expect(hint).not.toHaveClass("truncate");
    expect(screen.getByRole("textbox").compareDocumentPosition(hint) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("textbox").getAttribute("aria-describedby")).toBe("m-hint");
  });

  it("shows the error under the control with role alert", () => {
    render(
      <FormField label="Quote" htmlFor="q" density="compact" error="Enter a number.">
        <Input />
      </FormField>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
  });

  it("dims the label when disabled", () => {
    render(
      <FormField label="Watchlist" htmlFor="w" density="compact" disabled>
        <Input />
      </FormField>,
    );
    expect(screen.getByText("Watchlist")).toHaveClass("opacity-45");
  });
});

describe("FormField: default density is unchanged", () => {
  it("keeps the text-sm primary label, the unit after the control and the hint under the label", () => {
    render(
      <FormField label="MA length" htmlFor="ma" hint="Weeks in the average." unit="weeks">
        <Input />
      </FormField>,
    );
    const label = screen.getByText("MA length");
    expect(label).toHaveClass("text-sm", "text-text-primary");
    const unit = screen.getByText("weeks");
    expect(unit).toHaveClass("text-sm", "text-text-secondary");
    expect(unit.previousElementSibling).toBe(screen.getByRole("textbox"));
    expect(label.nextElementSibling).toBe(screen.getByText("Weeks in the average."));
  });

  it("only changes the label colour when applied is passed", () => {
    render(
      <FormField label="MA length" htmlFor="ma" applied>
        <Input />
      </FormField>,
    );
    expect(screen.getByText("MA length")).toHaveClass("text-filter-active");
  });
});

