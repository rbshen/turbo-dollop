// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScreenerSidebarMock } from "./ScreenerSidebarMock";

afterEach(cleanup);

// Smoke tests: the boxed sidebar reference renders from mock data alone and the
// real primitives inside it behave as specified. (The underline sidebar and the
// "live sidebar still uses the old parser" caption were deleted when the live
// sidebar moved onto the same components.)
const sidebar = () => screen.getByTestId("sidebar-boxed");
const presets = () => screen.getByTestId("presets-boxed");
const group = (root: HTMLElement, name: string) => within(root).getByRole("group", { name });
const minIn = (root: HTMLElement, name: string) => within(group(root, name)).getByRole("textbox", { name: "Minimum" }) as HTMLInputElement;
const maxIn = (root: HTMLElement, name: string) => within(group(root, name)).getByRole("textbox", { name: "Maximum" }) as HTMLInputElement;
const readoutOf = (root: HTMLElement, name: string) => group(root, name).parentElement?.querySelector("[data-testid='readout']")?.textContent;
const type = (box: HTMLInputElement, text: string) => {
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value: text } });
};

describe("ScreenerSidebarMock", () => {
  it("renders one 256px boxed sidebar, and no underline sidebar", () => {
    const { container } = render(<ScreenerSidebarMock />);
    expect(sidebar()).toHaveClass("w-64");
    for (const box of within(sidebar()).getAllByRole("textbox", { name: /Minimum|Maximum/ })) expect(box).toHaveClass("h-9", "rounded-md");
    expect(screen.queryByTestId("sidebar-underline")).toBeNull();
    expect(container.querySelector("input[class~='border-b'], input[class~='border-0']")).toBeNull();
    expect(screen.queryByText(/Underline/)).toBeNull();
  });

  it("has every real filter pair as a labelled group, with its unit in the label row", () => {
    render(<ScreenerSidebarMock />);
    const units: Record<string, string | null> = {
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
      const g = group(sidebar(), label);
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
    const root = sidebar();
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

  it("takes M, B and T in Mkt cap, shows the same hint as the live sidebar, and flags a reversed range", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar();
    type(minIn(root, "Mkt cap"), "5T");
    expect(readoutOf(root, "Mkt cap")).toBe("min: 5000000000000, max: null");
    type(maxIn(root, "Mkt cap"), "2 b");
    expect(within(group(root, "Mkt cap")).getByRole("alert")).toHaveTextContent("Min is higher than max, so no ticker can match.");
    expect(within(group(root, "Mkt cap")).getByText("Type 500M or 2B.")).toBeInTheDocument();
  });

  it("counts applied filters in a neutral section badge, and Reset and Load re-sync the boxes", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar();
    const fundamental = within(root).getByText("Fundamental").closest("div") as HTMLElement;
    expect(within(fundamental).queryByTitle(/applied/)).toBeNull();
    fireEvent.click(within(root).getByRole("button", { name: "Load sample view (mock)" }));
    // The Overall filter is a verdict multi-select: three verdicts are selected by the sample view, and it reads orange (active).
    const overall = within(root).getByRole("button", { name: "Overall (3): 3 selected" });
    expect(overall).toHaveClass("text-filter-active");
    expect(minIn(root, "Mkt cap").value).toBe("1B");
    expect(maxIn(root, "Mkt cap").value).toBe("5T");
    expect(within(fundamental).getByTitle("5 applied")).toBeInTheDocument();
    type(minIn(root, "Growth"), "1x");
    fireEvent.click(within(root).getByRole("button", { name: "Reset" }));
    expect(within(root).getByRole("button", { name: "Overall: none selected" })).not.toHaveClass("text-filter-active");
    expect(minIn(root, "Growth").value).toBe("");
    expect(within(root).queryByRole("alert")).toBeNull();
  });

  it("shows the Watchlist scope label orange only while the filter is in effect, and counts it", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar();
    const label = () => within(root).getByText("Limit results to", { selector: "label" });
    const select = within(root).getByLabelText("Limit results to") as HTMLSelectElement;
    expect(label()).not.toHaveClass("text-filter-active");
    fireEvent.change(select, { target: { value: "W1" } });
    expect(label()).toHaveClass("text-filter-active");
    expect(within(root).getByText("Watchlist").closest("div")?.querySelector("[title='1 applied']")).not.toBeNull();
    fireEvent.click(within(root).getByLabelText("Mock: universe is All"));
    expect(select).toBeDisabled();
    expect(select.value).toBe("W1");
    expect(label()).not.toHaveClass("text-filter-active");
    expect(label()).toHaveClass("opacity-45");
  });

  it("has full-width chips and the real saved-views bar with its labelled naming step", () => {
    render(<ScreenerSidebarMock />);
    const root = sidebar();
    // the Sort row lives in the results header, not the sidebar (see the results controls mock)
    expect(within(root).queryByLabelText("Sort")).toBeNull();
    expect(within(root).queryByLabelText("Sort by")).toBeNull();
    expect(within(root).getByRole("button", { name: "Saved views (4)" })).toBeInTheDocument();
    const chip = within(root).getByLabelText("Speculative growth") as HTMLInputElement;
    expect(chip.closest("label")).toHaveClass("w-full", "h-8");
    fireEvent.click(chip);
    expect(chip).toBeChecked();
    fireEvent.click(within(root).getByRole("button", { name: "Save current view" }));
    const name = within(root).getByLabelText("View name");
    expect(name).toHaveClass("w-full", "rounded-md");
    expect(within(root).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(name, { target: { value: "My view" } });
    expect(within(root).getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(within(root).getByRole("button", { name: "Cancel" }));
    expect(within(root).queryByLabelText("View name")).toBeNull();
  });

  it("pre-sets every state for real: filled, invalid, held prefix, prefix after blur, reversed, 1B, 5T", async () => {
    render(<ScreenerSidebarMock />);
    await waitFor(() => expect(readoutOf(presets(), "P/E")).toBe("min: null, max: null"));
    const root = presets();
    expect(within(root).getByText("Financials")).toHaveClass("text-filter-active");
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
    const marks = within(root).getAllByRole("group", { name: "Mkt cap" });
    expect((within(marks[0]).getByRole("textbox", { name: "Minimum" }) as HTMLInputElement).value).toBe("1B");
    expect((within(marks[1]).getByRole("textbox", { name: "Maximum" }) as HTMLInputElement).value).toBe("5T");
  });

  it("shows the default-versus-compact label comparison, the computed heights and the outline button", () => {
    render(<ScreenerSidebarMock />);
    expect(screen.getByText(/Default FormField/)).toBeInTheDocument();
    expect(screen.getByText(/Compact: text-xs/)).toBeInTheDocument();
    const note = screen.getByTestId("height-note");
    expect(note).toHaveTextContent("524px");
    expect(note).toHaveTextContent("543px");
    expect(note).toHaveTextContent("864px");
    expect(note).toHaveTextContent("883px");
    expect(note).toHaveTextContent("not measured in a browser");
    expect(screen.getByRole("button", { name: "Outline" })).toHaveClass("border-border-input", "hover:border-brand");
    expect(screen.queryByText(/old market-cap parser/)).toBeNull();
  });
});
