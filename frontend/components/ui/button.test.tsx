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

  it("makes a small primary button 32px too, so it matches an outline button beside it", () => {
    render(
      <Button variant="primary" size="sm">
        Save
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveClass("bg-brand", "h-8", "text-xs");
    expect(button).not.toHaveClass("h-7");
  });

  it("leaves the default primary at 36px and the small ghost and danger at 28px", () => {
    render(
      <>
        <Button variant="primary">Default</Button>
        <Button variant="ghost" size="sm">Ghost</Button>
        <Button variant="danger" size="sm">Danger</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Default" })).toHaveClass("h-9");
    expect(screen.getByRole("button", { name: "Ghost" })).toHaveClass("h-7");
    expect(screen.getByRole("button", { name: "Danger" })).toHaveClass("h-7");
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

describe("Button icon sizes", () => {
  it("makes icon a 36px square with no horizontal padding", () => {
    render(
      <Button variant="outline" size="icon" aria-label="Open">
        <span aria-hidden="true">x</span>
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Open" });
    expect(button).toHaveClass("size-9", "px-0");
    expect(button).not.toHaveClass("px-3");
  });

  it("makes icon-sm a 28px square, and 32px as an outline like sm", () => {
    render(
      <>
        <Button size="icon-sm" aria-label="Ghost">
          <span aria-hidden="true">x</span>
        </Button>
        <Button variant="outline" size="icon-sm" aria-label="Outline">
          <span aria-hidden="true">x</span>
        </Button>
      </>,
    );
    const ghost = screen.getByRole("button", { name: "Ghost" });
    expect(ghost).toHaveClass("size-7", "px-0");
    const outline = screen.getByRole("button", { name: "Outline" });
    expect(outline).toHaveClass("size-8", "px-0");
    expect(outline).not.toHaveClass("size-7");
  });
});
