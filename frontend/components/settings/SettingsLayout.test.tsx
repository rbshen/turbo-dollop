// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SETTINGS_CONTROL_COLUMN_CLASS,
  SettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSection,
} from "@/components/settings/SettingsLayout";
import { Checkbox } from "@/components/ui/checkbox";
import { NumberField } from "@/components/ui/number-field";
import { Select } from "@/components/ui/Select";

afterEach(cleanup);

describe("SettingsSection", () => {
  it("renders the title as a heading, the intro capped at max-w-xl, and a max-w-2xl body", () => {
    const { container } = render(
      <SettingsSection title="Weinstein stage" intro="How the weekly stage is worked out.">
        <p>body</p>
      </SettingsSection>,
    );
    expect(screen.getByRole("heading", { name: "Weinstein stage" })).toBeInTheDocument();
    expect(screen.getByText("How the weekly stage is worked out.")).toHaveClass("max-w-xl");
    expect(screen.getByText("body").parentElement).toHaveClass("max-w-2xl");
    expect(container.firstElementChild).toHaveClass("border-t");
  });

  it("omits the intro when there is none", () => {
    render(
      <SettingsSection title="REIT">
        <p>body</p>
      </SettingsSection>,
    );
    expect(document.querySelector("p.max-w-xl")).toBeNull();
  });
});

describe("SettingsGroup", () => {
  it("has a sub-heading only when given a title, and names the group by it", () => {
    render(
      <SettingsGroup title="Stage">
        <div>row</div>
      </SettingsGroup>,
    );
    const group = screen.getByRole("group", { name: "Stage" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Stage" })).toBeInTheDocument();
  });

  it("is a plain, untitled group otherwise", () => {
    render(
      <SettingsGroup>
        <div>row</div>
      </SettingsGroup>,
    );
    expect(screen.queryByRole("group")).toBeNull();
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("puts a hairline between rows", () => {
    render(
      <SettingsGroup>
        <div>row</div>
      </SettingsGroup>,
    );
    expect(screen.getByText("row").parentElement).toHaveClass("divide-y", "divide-border-subtle");
  });
});

describe("SettingsRow", () => {
  it("is a two-column grid with py-3, label and hint on the left, control in the control column", () => {
    const { container } = render(
      <SettingsRow label="MA length" hint="Weeks in the average." htmlFor="ma">
        <NumberField value="30" onChange={() => {}} unit="weeks" />
      </SettingsRow>,
    );
    expect(container.firstElementChild).toHaveClass("grid", "py-3", SETTINGS_CONTROL_COLUMN_CLASS);
    expect(container.firstElementChild).not.toHaveClass("grid-cols-[1fr_auto]");
    const label = screen.getByText("MA length");
    expect(label.tagName).toBe("LABEL");
    expect(label).toHaveAttribute("for", "ma");
    expect(label.nextElementSibling).toBe(screen.getByText("Weeks in the average."));
    const input = screen.getByLabelText("MA length");
    expect(input).toHaveAttribute("id", "ma");
    expect(label.parentElement?.nextElementSibling).toContainElement(input);
  });

  it("links the hint to the control with aria-describedby", () => {
    render(
      <SettingsRow label="MA length" hint="Weeks in the average." htmlFor="ma">
        <NumberField value="30" onChange={() => {}} />
      </SettingsRow>,
    );
    const input = screen.getByLabelText("MA length");
    expect(screen.getByText("Weeks in the average.")).toHaveAttribute("id", "ma-hint");
    expect(input.getAttribute("aria-describedby")).toContain("ma-hint");
  });

  it("shows an error on its own line under the control, announced, and marks the control invalid", () => {
    render(
      <SettingsRow label="MA length" hint="A hint." htmlFor="ma" error="Enter a value between 2 and 200.">
        <NumberField value="1" onChange={() => {}} />
      </SettingsRow>,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Enter a value between 2 and 200.");
    const input = screen.getByLabelText("MA length");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input.getAttribute("aria-describedby")).toContain(alert.id);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("disables the control and dims the label and hint when disabled", () => {
    render(
      <SettingsRow label="Breach recency" hint="A hint." htmlFor="br" disabled>
        <NumberField value="5" onChange={() => {}} unit="bars" />
      </SettingsRow>,
    );
    expect(screen.getByLabelText("Breach recency")).toBeDisabled();
    expect(screen.getByText("Breach recency").parentElement).toHaveClass("opacity-45");
  });

  it("names a Select and a Checkbox from the row label", () => {
    render(
      <>
        <SettingsRow label="MA type" htmlFor="mt">
          <Select size="short">
            <option>EMA</option>
          </Select>
        </SettingsRow>
        <SettingsRow label="Keep last breached support" htmlFor="ks">
          <Checkbox variant="neutral" />
        </SettingsRow>
      </>,
    );
    expect(screen.getByLabelText("MA type").tagName).toBe("SELECT");
    expect(screen.getByRole("checkbox", { name: "Keep last breached support" })).toBeInTheDocument();
  });
});

// The fixed control column: the same width for every row, whatever its unit,
// with every control (box, checkbox, switch) left-aligned in it.
describe("SettingsRow: fixed, left-aligned control column", () => {
  const rowOf = (label: string) => screen.getByText(label).closest("div.grid") as HTMLElement;
  const controlCellOf = (label: string) => rowOf(label).children[1] as HTMLElement;

  function renderRows() {
    render(
      <>
        <SettingsRow label="No unit" htmlFor="r-none">
          <NumberField value="2" onChange={() => {}} />
        </SettingsRow>
        <SettingsRow label="Percent" htmlFor="r-pct">
          <NumberField value="5" onChange={() => {}} unit="%" />
        </SettingsRow>
        <SettingsRow label="Weeks" htmlFor="r-wk">
          <NumberField value="30" onChange={() => {}} unit="weeks" />
        </SettingsRow>
        <SettingsRow label="Times average" htmlFor="r-x">
          <NumberField value="2" onChange={() => {}} unit="× average" />
        </SettingsRow>
        <SettingsRow label="Choice" htmlFor="r-sel">
          <Select size="medium">
            <option>Nearest to price</option>
          </Select>
        </SettingsRow>
        <SettingsRow label="Tick" htmlFor="r-cb">
          <Checkbox variant="neutral" />
        </SettingsRow>
        <SettingsRow label="Recency" htmlFor="r-dis" disabled>
          <NumberField value="5" onChange={() => {}} unit="bars" />
        </SettingsRow>
      </>,
    );
  }
  const LABELS = ["No unit", "Percent", "Weeks", "Times average", "Choice", "Tick", "Recency"];

  it("puts the control column width on every row, identical whatever the unit", () => {
    renderRows();
    expect(SETTINGS_CONTROL_COLUMN_CLASS).toBe("sm:grid-cols-[minmax(0,1fr)_16rem]");
    for (const label of LABELS) {
      expect(rowOf(label)).toHaveClass(SETTINGS_CONTROL_COLUMN_CLASS);
    }
    const widths = LABELS.map((l) => rowOf(l).className.split(/\s+/).filter((c) => c.includes("grid-cols")).join(" "));
    expect(new Set(widths).size).toBe(1);
  });

  it("never sizes the column from content: no auto column, and the width is not on the control", () => {
    renderRows();
    for (const label of LABELS) {
      expect(rowOf(label).className).not.toMatch(/\bauto\b|_auto\]/);
    }
  });

  it("gives every control cell the same left-alignment class: number boxes, select, checkbox, disabled", () => {
    renderRows();
    const classes = LABELS.map((l) => controlCellOf(l).className);
    expect(new Set(classes).size).toBe(1);
    expect(classes[0]).toContain("justify-start");
    expect(classes[0]).not.toMatch(/justify-end|self-end|justify-self-end|sm:justify/);
  });

  it("keeps the same alignment on a disabled row", () => {
    renderRows();
    expect(controlCellOf("Recency").className).toBe(controlCellOf("Weeks").className);
    expect(rowOf("Recency")).toHaveClass(SETTINGS_CONTROL_COLUMN_CLASS);
    expect(screen.getByLabelText("Recency")).toBeDisabled();
  });

  it("left-aligns the error under the control column", () => {
    render(
      <SettingsRow label="Weeks" htmlFor="e1" error="Enter a number.">
        <NumberField value="abc" onChange={() => {}} unit="weeks" />
      </SettingsRow>,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveClass("text-left", "sm:col-start-2");
    expect(alert.className).not.toMatch(/text-right|justify-self-end|sm:text-right/);
  });

  it("stacks below the sm breakpoint and lays out two columns only from sm up", () => {
    renderRows();
    for (const label of LABELS) {
      const cls = rowOf(label).className;
      expect(cls).toContain("grid-cols-1");
      // the two-column template is behind the sm: variant, so it is one column below it
      expect(cls).toContain("sm:grid-cols-[");
      expect(cls).not.toMatch(/(^|\s)grid-cols-\[/);
    }
  });

  it("stacks the error under the control (full width, then column 2 from sm)", () => {
    render(
      <SettingsRow label="Weeks" htmlFor="e2" error="Enter a number.">
        <NumberField value="abc" onChange={() => {}} />
      </SettingsRow>,
    );
    expect(screen.getByRole("alert").className).toContain("sm:col-start-2");
    expect(screen.getByRole("alert").className).not.toMatch(/(^|\s)col-start-2/);
  });

  it("caps the control cell at the column so nothing overflows", () => {
    renderRows();
    expect(controlCellOf("Weeks")).toHaveClass("min-w-0", "max-w-full");
  });
});

describe("SettingsFooter", () => {
  it("renders Save, an aria-live status region and the Last updated line", () => {
    render(<SettingsFooter onSave={() => {}} status="idle" updatedAt="2026-09-30T12:00:00" />);
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(screen.getByText(/^Last updated /)).toBeInTheDocument();
    const live = document.querySelector("[aria-live='polite']");
    expect(live).not.toBeNull();
    expect(live).toHaveTextContent("");
  });

  it("keeps the order: Save, then status, then Last updated", () => {
    render(<SettingsFooter onSave={() => {}} status="saved" updatedAt="2026-09-30T12:00:00" />);
    const [button, status, updated] = Array.from(screen.getByRole("button").parentElement!.children);
    expect(button).toBe(screen.getByRole("button"));
    expect(status).toHaveTextContent("Saved ✓");
    expect(updated).toHaveTextContent(/^Last updated/);
  });

  it("calls onSave when Save is pressed", () => {
    const onSave = vi.fn();
    render(<SettingsFooter onSave={onSave} status="idle" updatedAt="2026-09-30T12:00:00" />);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("disables Save while saving and reports it", () => {
    render(<SettingsFooter onSave={() => {}} status="saving" updatedAt="2026-09-30T12:00:00" />);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText("Saving…")).toBeInTheDocument();
  });

  it("reports a failed save in the negative tone", () => {
    render(<SettingsFooter onSave={() => {}} status="error" updatedAt="2026-09-30T12:00:00" />);
    expect(screen.getByText("Save failed")).toHaveClass("text-negative");
  });

  it("disables Save and says why while a field is invalid", () => {
    render(<SettingsFooter onSave={() => {}} status="idle" invalid updatedAt="2026-09-30T12:00:00" />);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
  });
});
