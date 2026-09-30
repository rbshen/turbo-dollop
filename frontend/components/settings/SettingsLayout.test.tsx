// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsFooter, SettingsGroup, SettingsRow, SettingsSection } from "@/components/settings/SettingsLayout";
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
  it("is a two-column [1fr_auto] grid with py-3, label and hint on the left, control on the right", () => {
    const { container } = render(
      <SettingsRow label="MA length" hint="Weeks in the average." htmlFor="ma">
        <NumberField value="30" onChange={() => {}} unit="weeks" />
      </SettingsRow>,
    );
    expect(container.firstElementChild).toHaveClass("grid", "grid-cols-[1fr_auto]", "py-3");
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
    expect(alert).toHaveClass("col-span-full");
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
