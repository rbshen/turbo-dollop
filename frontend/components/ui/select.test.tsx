// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Select } from "@/components/ui/Select";

afterEach(cleanup);

function renderSelect(props: Partial<React.ComponentProps<typeof Select>> = {}) {
  return render(
    <Select aria-label="MA type" {...props}>
      <option value="EMA">EMA</option>
      <option value="SMA">SMA</option>
    </Select>,
  );
}

describe("Select: legacy rendering is unchanged", () => {
  it("keeps the old shell when no size is given", () => {
    const { container } = renderSelect();
    const select = screen.getByLabelText("MA type");
    expect(select).toHaveClass("w-full", "appearance-none", "rounded", "py-1.5", "pl-2", "pr-7", "focus:border-brand", "focus:outline-none");
    expect(select).not.toHaveClass("h-9");
    expect(container.firstElementChild).toHaveClass("relative", "block");
    expect(container.firstElementChild).not.toHaveClass("w-24");
    expect(select).not.toHaveAttribute("aria-invalid");
  });
});

describe("Select: opt-in restyle", () => {
  it.each([
    ["short", "w-24"],
    ["medium", "w-44"],
    ["wide", "w-80"],
    ["full", "w-full"],
  ] as const)("size %s sizes the shell with %s and makes the select 36px high", (size, cls) => {
    const { container } = renderSelect({ size });
    const shell = container.firstElementChild;
    expect(shell).toHaveClass(cls);
    if (size !== "full") expect(shell).toHaveClass("max-w-full");
    expect(screen.getByLabelText("MA type")).toHaveClass("h-9", "w-full", "rounded-md", "appearance-none", "border-border-control", "bg-page");
  });

  it("is still a native select and never sets focus:outline-none", () => {
    renderSelect({ size: "short" });
    const select = screen.getByLabelText("MA type");
    expect(select.tagName).toBe("SELECT");
    expect(select.className).not.toMatch(/outline-none/);
    expect(select.className).not.toMatch(/focus:border-brand/);
  });

  it("invalid adds aria-invalid and the invalid border", () => {
    renderSelect({ size: "medium", invalid: true });
    const select = screen.getByLabelText("MA type");
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveClass("border-negative");
  });

  it("passes disabled and aria-describedby through", () => {
    renderSelect({ size: "medium", disabled: true, "aria-describedby": "hint" });
    const select = screen.getByLabelText("MA type");
    expect(select).toBeDisabled();
    expect(select).toHaveAttribute("aria-describedby", "hint");
  });
});
