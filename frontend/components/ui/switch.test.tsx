// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FormField } from "@/components/ui/form-field";
import { Switch } from "@/components/ui/switch";

afterEach(cleanup);

describe("Switch", () => {
  it("is a native checkbox input with role=switch, named by its label", () => {
    render(<Switch id="s" label="Enable job" />);
    const el = screen.getByRole("switch", { name: "Enable job" });
    expect(el.tagName).toBe("INPUT");
    expect(el).toHaveAttribute("type", "checkbox");
    expect(el).not.toBeChecked();
  });

  it("toggles on click and reports the change", () => {
    const onChange = vi.fn();
    render(<Switch id="s" label="Enable job" onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("works controlled", () => {
    render(<Switch id="s" label="x" checked readOnly />);
    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("draws a 32x18 track and a 12px thumb, neutral when on, with the Checkbox focus ring", () => {
    render(<Switch id="s" label="x" />);
    const input = screen.getByRole("switch");
    const track = input.nextElementSibling as HTMLElement;
    const thumb = track.nextElementSibling as HTMLElement;
    expect(input.parentElement).toHaveClass("h-[18px]", "w-8");
    expect(thumb).toHaveClass("h-3", "w-3", "peer-checked:translate-x-3.5");
    expect(track).toHaveClass("rounded-full", "peer-checked:bg-text-primary", "peer-checked:border-text-primary");
    expect(track.className).not.toMatch(/peer-checked:\S*brand/);
    expect(track.className).toMatch(/peer-focus-visible:outline-2/);
    expect(track.className).not.toMatch(/outline-none/);
    expect(thumb).toHaveClass("peer-checked:bg-page");
  });

  it("is disabled and dims its label when disabled", () => {
    render(<Switch id="s" label="x" disabled />);
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByText("x").closest("label")).toHaveClass("has-[:disabled]:opacity-45");
  });

  it("passes aria-describedby through", () => {
    render(<Switch id="s" label="x" aria-describedby="h" />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-describedby", "h");
  });

  it("takes its id and description from an enclosing FormField", () => {
    render(
      <FormField label="Refresh automatically" htmlFor="auto" hint="Applies at once.">
        <Switch />
      </FormField>,
    );
    const el = screen.getByRole("switch", { name: "Refresh automatically" });
    expect(el).toHaveAttribute("id", "auto");
    expect(el).toHaveAttribute("aria-describedby", "auto-hint");
  });
});
