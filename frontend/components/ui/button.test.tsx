// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";

afterEach(cleanup);

describe("Button", () => {
  it("defaults to type=\"button\" so it never submits a form by accident", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("type", "button");
  });

  it("respects an explicit type override", () => {
    render(<Button type="submit">Submit</Button>);
    expect(screen.getByRole("button", { name: "Submit" })).toHaveAttribute("type", "submit");
  });

  it("applies the primary variant's brand background class", () => {
    render(<Button variant="primary">Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveClass("bg-brand");
  });

  it("applies the danger variant's negative text class", () => {
    render(<Button variant="danger">Delete</Button>);
    expect(screen.getByRole("button", { name: "Delete" })).toHaveClass("text-negative");
  });

  it("defaults to the ghost variant when none is given", () => {
    render(<Button>Cancel</Button>);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("text-text-secondary");
  });

  it("applies the outline variant: a hairline border that turns brand on hover", () => {
    render(<Button variant="outline">Save view</Button>);
    const button = screen.getByRole("button", { name: "Save view" });
    expect(button).toHaveClass("border", "border-border-input", "hover:border-brand", "h-9");
  });

  it("makes a small outline button 32px high, like the sidebar's chips and triggers", () => {
    render(
      <Button variant="outline" size="sm">
        Sort
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Sort" });
    expect(button).toHaveClass("h-8");
    expect(button).not.toHaveClass("h-7");
  });

  it("leaves the existing variants untouched (a small ghost is still 28px, no border)", () => {
    render(
      <Button size="sm">Plain</Button>,
    );
    const button = screen.getByRole("button", { name: "Plain" });
    expect(button).toHaveClass("h-7");
    expect(button).not.toHaveClass("border");
  });
});
