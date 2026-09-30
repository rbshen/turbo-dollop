// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FmpSettingsMock } from "./FmpSettingsMock";
import { FormControlsReference } from "./FormControlsReference";
import { AlignmentCheckMock, DiscountRateMock, LiquidityMock, WeinsteinMock } from "./SettingsMocks";

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
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
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

describe("AlignmentCheckMock", () => {
  it("covers every kind of control, all in the same fixed control column", () => {
    render(<AlignmentCheckMock />);
    for (const label of [
      "No unit",
      "Percent",
      "Weeks",
      "Times average",
      "Bars",
      "Medium select",
      "RS benchmark",
      "Checkbox",
      "Switch",
      "Disabled row",
      "Invalid row",
    ]) {
      const row = screen.getByText(label, { selector: "label" }).closest("div.grid") as HTMLElement;
      expect(row.className).toContain("sm:grid-cols-[minmax(0,1fr)_16rem]");
      expect((row.children[1] as HTMLElement).className).toContain("justify-start");
    }
    for (const unit of ["%", "weeks", "× average", "bars"]) {
      expect(screen.getAllByText(unit).length).toBeGreaterThan(0);
    }
  });

  it("has a disabled row and one invalid row with a left-aligned error", () => {
    render(<AlignmentCheckMock />);
    expect(screen.getByLabelText("Disabled row")).toBeDisabled();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveClass("text-left");
    expect(screen.getByLabelText("Invalid row")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("FmpSettingsMock", () => {
  it("shows the table with a Switch and a tier Select per row, and the card below it, in three panels", () => {
    render(<FmpSettingsMock />);
    expect(screen.getAllByRole("table")).toHaveLength(3);
    expect(screen.getAllByRole("heading", { name: "FMP status" })).toHaveLength(3);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    // 3 panels x (4 group switches + master)
    expect(screen.getAllByRole("switch")).toHaveLength(15);
    // 3 panels x (4 tier selects + plan)
    expect(screen.getAllByRole("combobox")).toHaveLength(15);
    for (const el of [...screen.getAllByRole("switch"), ...screen.getAllByRole("combobox")]) {
      expect(el).toHaveAccessibleName();
    }
  });

  it("covers on, off, not-toggleable and not-wired rows", () => {
    render(<FmpSettingsMock />);
    const [first] = screen.getAllByRole("table");
    expect(within(first).getByRole("switch", { name: "Enable Fundamentals" })).toBeChecked();
    expect(within(first).getByRole("switch", { name: "Enable News" })).not.toBeChecked();
    expect(within(first).getByRole("switch", { name: "Enable Analyst ratings" })).toBeDisabled();
    expect(within(first).getByText(/not wired yet/)).toBeInTheDocument();
  });

  it("the interactive panel applies a change at once, with no Save and no API call", () => {
    render(<FmpSettingsMock />);
    const [first] = screen.getAllByRole("table");
    fireEvent.click(within(first).getByRole("switch", { name: "Enable News" }));
    expect(within(first).getByRole("switch", { name: "Enable News" })).toBeChecked();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("the busy panel disables every control", () => {
    render(<FmpSettingsMock />);
    const busyTable = screen.getAllByRole("table")[1];
    for (const el of [...within(busyTable).getAllByRole("switch"), ...within(busyTable).getAllByRole("combobox")]) {
      expect(el).toBeDisabled();
    }
    expect(document.getElementById("sg-fmp-busy-master")).toBeDisabled();
    expect(document.getElementById("sg-fmp-busy-plan")).toBeDisabled();
    expect(document.getElementById("sg-fmp-live-master")).toBeEnabled();
  });

  it("the error panel shows the row message, the card message and the key problem", () => {
    render(<FmpSettingsMock />);
    const alerts = screen.getAllByRole("alert").map((a) => a.textContent);
    expect(alerts).toContain("enabled: Input should be a valid boolean");
    expect(alerts.some((t) => t?.startsWith("fmp_plan:"))).toBe(true);
    expect(screen.getByText(/FMP rejected the API key \(HTTP 401\)/)).toBeInTheDocument();
  });
});
