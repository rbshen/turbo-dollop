// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScreenerSidebarMock } from "./ScreenerSidebarMock";

afterEach(cleanup);

// Smoke tests: the sidebar mock renders from mock data alone and the real
// primitives inside it behave as specified.
const sidebar = (variant: "boxed" | "underline") => screen.getByTestId(`sidebar-${variant}`);
const presets = (variant: "boxed" | "underline") => screen.getByTestId(`presets-${variant}`);
const group = (root: HTMLElement, name: string) => within(root).getByRole("group", { name });
const minIn = (root: HTMLElement, name: string) => within(group(root, name)).getByRole("textbox", { name: "Minimum" }) as HTMLInputElement;
const maxIn = (root: HTMLElement, name: string) => within(group(root, name)).getByRole("textbox", { name: "Maximum" }) as HTMLInputElement;
const readoutOf = (root: HTMLElement, name: string) => group(root, name).parentElement?.querySelector("[data-testid='readout']")?.textContent;
const type = (box: HTMLInputElement, text: string) => {
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value: text } });
};

describe("ScreenerSidebarMock", () => {
  it("renders two 256px sidebars, boxed and underline", () => {
    render(<ScreenerSidebarMock />);
    expect(sidebar("boxed")).toHaveClass("w-64");
    expect(sidebar("underline")).toHaveClass("w-64");
    for (const box of within(sidebar("boxed")).getAllByRole("textbox", { name: /Minimum|Maximum/ })) expect(box).toHaveClass("h-9", "rounded-md");
    for (const box of within(sidebar("underline")).getAllByRole("textbox", { name: /Minimum|Maximum/ })) {
      expect(box).toHaveClass("h-8", "rounded-none", "border-b");
    }
  });

  it("has every real filter pair as a labelled group, with its unit in the label row", () => {
    render(<ScreenerSidebarMock />);
    const units: Record<string, string | null> = {
      Overall: null,
      Financials: null,
      "Growth rate": null,
      Profitability: null,
      Debt: null,
      Quote: "USD",
      "Mkt cap": "USD",
      "P/E": "x",
      Growth: "%",
      Beta: null,
    };
    for (const [label, unit] of Object.entries(units)) {
      const g = group(sidebar("boxed"), label);
      const labelEl = within(g).getByText(label);
      if (unit) {
        const unitEl = within(g).getByText(unit);
        expect(unitEl.parentElement).toBe(labelEl.parentElement);
        expect(unitEl).toHaveClass("text-text-tertiary");
      }
    }
  });

  it("shows the live numeric value under each pair and follows the commit rule", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar("boxed");
    expect(readoutOf(root, "Growth")).toBe("min: null, max: null");
    type(minIn(root, "Growth"), "12.");
    expect(readoutOf(root, "Growth")).toBe("min: 12, max: null");
    type(minIn(root, "Growth"), "-");
    expect(readoutOf(root, "Growth")).toBe("min: 12, max: null"); // held
    expect(within(group(root, "Growth")).queryByRole("alert")).toBeNull();
    fireEvent.blur(minIn(root, "Growth"));
    expect(readoutOf(root, "Growth")).toBe("min: null, max: null");
    expect(within(group(root, "Growth")).getByRole("alert")).toHaveTextContent("Enter a number.");
    type(minIn(root, "Growth"), "1x");
    expect(readoutOf(root, "Growth")).toBe("min: null, max: null");
  });

  it("takes M, B and T in Mkt cap and shows the market-cap hint", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar("underline");
    type(minIn(root, "Mkt cap"), "5T");
    expect(readoutOf(root, "Mkt cap")).toBe("min: 5000000000000, max: null");
    type(maxIn(root, "Mkt cap"), "2 b");
    expect(within(group(root, "Mkt cap")).getByRole("alert")).toHaveTextContent("Min is higher than max, so no ticker can match.");
    expect(within(group(root, "Mkt cap")).getByText("e.g. 500M, 2B, 1T")).toBeInTheDocument();
  });

  it("counts applied filters in a neutral section badge, and Reset and Load re-sync the boxes", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar("boxed");
    const fundamental = within(root).getByText("Fundamental").closest("div") as HTMLElement;
    expect(within(fundamental).queryByTitle(/applied/)).toBeNull();
    fireEvent.click(within(root).getByRole("button", { name: "Load sample view (mock)" }));
    expect(minIn(root, "Overall").value).toBe("70");
    expect(minIn(root, "Mkt cap").value).toBe("1B");
    expect(maxIn(root, "Mkt cap").value).toBe("5T");
    expect(within(fundamental).getByTitle("5 applied")).toBeInTheDocument();
    expect(within(group(root, "Overall")).getByText("Overall")).toHaveClass("text-filter-active");
    type(minIn(root, "Growth"), "1x");
    fireEvent.click(within(root).getByRole("button", { name: "Reset" }));
    expect(minIn(root, "Overall").value).toBe("");
    expect(minIn(root, "Growth").value).toBe("");
    expect(within(root).queryByRole("alert")).toBeNull();
  });

  it("shows the Watchlist label orange only while the filter is in effect", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar("boxed");
    const label = () => within(root).getByText("Watchlist", { selector: "label" });
    const select = within(root).getByLabelText("Watchlist") as HTMLSelectElement;
    expect(label()).not.toHaveClass("text-filter-active");
    fireEvent.change(select, { target: { value: "W1" } });
    expect(label()).toHaveClass("text-filter-active");
    fireEvent.click(within(root).getByLabelText("Mock: universe is All"));
    expect(select).toBeDisabled();
    expect(select.value).toBe("W1");
    expect(label()).not.toHaveClass("text-filter-active");
  });

  it("has the Sort select with a real label, full-width chips and the naming row", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar("boxed");
    expect(within(root).getByLabelText("Sort")).toBeInstanceOf(HTMLSelectElement);
    const chip = within(root).getByLabelText("Speculative growth") as HTMLInputElement;
    expect(chip.closest("label")).toHaveClass("w-full", "h-8");
    fireEvent.click(chip);
    expect(chip).toBeChecked();
    fireEvent.click(within(root).getByRole("button", { name: "Save current view" }));
    const name = within(root).getByRole("textbox", { name: "View name" });
    expect(name).toHaveClass("w-full", "rounded-md");
    expect(within(root).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(name, { target: { value: "My view" } });
    expect(within(root).getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(within(root).getByRole("button", { name: "Cancel" }));
    expect(within(root).queryByRole("textbox", { name: "View name" })).toBeNull();
  });

  it("pre-sets every state for real: filled, invalid, held prefix, prefix after blur, reversed, 1B, 5T", async () => {
    render(<ScreenerSidebarMock />);
    await waitFor(() => expect(readoutOf(presets("boxed"), "P/E")).toBe("min: null, max: null"));
    await waitFor(() => expect(readoutOf(presets("underline"), "P/E")).toBe("min: null, max: null"));
    for (const variant of ["boxed", "underline"] as const) {
      const root = presets(variant);
      expect(within(root).getByText("Overall")).toHaveClass("text-filter-active");
      expect(within(group(root, "Growth")).getByRole("alert")).toHaveTextContent("Enter a number.");
      expect(minIn(root, "Growth").value).toBe("1x");
      expect(minIn(root, "Quote").value).toBe("-");
      expect(within(group(root, "Quote")).queryByRole("alert")).toBeNull();
      expect(readoutOf(root, "Quote")).toBe("min: 50, max: null");
      expect(within(group(root, "P/E")).getByRole("alert")).toHaveTextContent("Enter a number.");
      expect(readoutOf(root, "P/E")).toBe("min: null, max: null");
      expect(within(group(root, "Debt")).getByRole("alert")).toHaveTextContent("Min is higher than max");
      expect(maxIn(root, "Debt")).toHaveAttribute("aria-invalid", "true");
      expect(minIn(root, "Debt")).not.toHaveAttribute("aria-invalid");
    }
    const marks = within(presets("boxed")).getAllByRole("group", { name: "Mkt cap" });
    expect((within(marks[0]).getByRole("textbox", { name: "Minimum" }) as HTMLInputElement).value).toBe("1B");
    expect((within(marks[1]).getByRole("textbox", { name: "Maximum" }) as HTMLInputElement).value).toBe("5T");
  });

  it("shows the default-versus-compact label comparison, the height note and the outline button", () => {
    render(<ScreenerSidebarMock />);
    expect(screen.getByText(/Default FormField/)).toBeInTheDocument();
    expect(screen.getByText(/Compact: text-xs/)).toBeInTheDocument();
    const note = screen.getByTestId("height-note");
    expect(note).toHaveTextContent("555px");
    expect(note).toHaveTextContent("591px");
    expect(note).toHaveTextContent("847px");
    expect(note).toHaveTextContent("883px");
    expect(screen.getByRole("button", { name: "Outline" })).toHaveClass("border-border-input", "hover:border-brand");
    expect(screen.getByText(/old market-cap parser/)).toBeInTheDocument();
  });
});
