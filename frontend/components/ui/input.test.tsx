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
