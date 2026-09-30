// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FormControlsReference } from "./FormControlsReference";
import { DiscountRateMock, LiquidityMock, WeinsteinMock } from "./SettingsMocks";

afterEach(cleanup);

// Smoke tests: the styleguide's form-control reference and Settings mocks
// render from mock data alone (no API/hooks) and behave as the spec says.
describe("FormControlsReference", () => {
  it("renders every control family from mock data", () => {
    const { container } = render(<FormControlsReference />);
    for (const name of ["NumberField", "Input, boxed", "Select (native)", "Neutral (new)", "Chip"]) {
      expect(screen.getAllByText(name, { exact: false }).length).toBeGreaterThan(0);
    }
    expect(screen.getAllByRole("switch").length).toBeGreaterThanOrEqual(5);
    // stepper demos: at least one -/+ pair
    expect(screen.getAllByRole("button", { name: "Increase" }).length).toBeGreaterThan(0);
    // native selects, not custom listboxes
    expect(container.querySelectorAll("select").length).toBeGreaterThan(0);
    expect(container.querySelector("[role='listbox']")).toBeNull();
  });

  it("shows boxed and underline fields side by side", () => {
    render(<FormControlsReference />);
    expect(document.getElementById("sg-boxed-ticker")).toHaveClass("rounded-md");
    expect(document.getElementById("sg-underline-ticker")).toHaveClass("rounded-none", "border-b");
  });

  it("shows every size token on NumberField", () => {
    render(<FormControlsReference />);
    expect(screen.getByLabelText("NumberField short")).toHaveClass("w-24");
    expect(screen.getByLabelText("NumberField medium")).toHaveClass("w-44");
    expect(screen.getByLabelText("NumberField wide")).toHaveClass("w-80");
    expect(screen.getByLabelText("NumberField full")).toHaveClass("w-full");
  });
});

describe("WeinsteinMock", () => {
  it("has the two sub-headings and all 8 fields, with units as suffixes and unit-free labels", () => {
    render(<WeinsteinMock />);
    expect(screen.getByRole("heading", { name: "Stage" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Breakout and relative strength" })).toBeInTheDocument();
    for (const label of [
      "MA length",
      "MA type",
      "Within range",
      "Slope lookback",
      "Breakout volume",
      "Volume average length",
      "RS benchmark",
      "RS smoothing length",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText("weeks").length).toBe(4);
    expect(screen.getByText("× average")).toBeInTheDocument();
  });

  it("starts with exactly one invalid field, announced, and Save disabled until it is fixed", () => {
    render(<WeinsteinMock />);
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent("Enter a value between 2 and 200.");
    expect(screen.getByLabelText("Volume average length")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Volume average length"), { target: { value: "50" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("keeps every hint linked to its field", () => {
    render(<WeinsteinMock />);
    const field = screen.getByLabelText("MA length");
    expect(field.getAttribute("aria-describedby")).toContain("sg-ws-ma-length-hint");
  });
});

describe("LiquidityMock", () => {
  it("keeps the breach-recency row in place but disabled until 'only keep if breached recently' is ticked", () => {
    render(<LiquidityMock />);
    const recency = screen.getByLabelText("Breach recency");
    expect(recency).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Only keep if breached recently" }));
    expect(recency).toBeEnabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Only keep if breached recently" }));
    expect(recency).toBeDisabled();
  });

  it("does not validate the disabled recency row", () => {
    render(<LiquidityMock />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Only keep if breached recently" }));
    fireEvent.change(screen.getByLabelText("Breach recency"), { target: { value: "99" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value between 1 and 52.");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Only keep if breached recently" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("uses the neutral checked style on its checkboxes", () => {
    render(<LiquidityMock />);
    const input = screen.getByRole("checkbox", { name: "Keep last breached support" });
    expect((input.nextElementSibling as HTMLElement).className).toContain("peer-checked:bg-text-primary");
  });
});

describe("DiscountRateMock", () => {
  it("has one region group with two fields and its own footer, and sets no bounds", () => {
    render(<DiscountRateMock />);
    const group = screen.getByRole("group", { name: "United States (US)" });
    expect(within(group).getByLabelText("Risk-free rate")).toBeInTheDocument();
    expect(within(group).getByLabelText("Market risk premium")).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.change(within(group).getByLabelText("Risk-free rate"), { target: { value: "-250.5" } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.change(within(group).getByLabelText("Risk-free rate"), { target: { value: "abc" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
  });

  it("never cites a doc in its intro", () => {
    render(<DiscountRateMock />);
    expect(document.body.textContent).not.toMatch(/CLAUDE\.md|valuation\.md|§/);
  });
});
