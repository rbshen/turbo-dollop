// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsFooter, SettingsRow, SettingsSection } from "@/components/settings/SettingsLayout";
import { NumberField } from "@/components/ui/number-field";
import { TestAuth } from "@/lib/auth/testAuth";

afterEach(cleanup);

function form(role: "admin" | "viewer") {
  return render(
    <TestAuth role={role}>
      <SettingsSection title="Example" intro="What it does.">
        <SettingsRow label="Threshold" htmlFor="threshold">
          <NumberField id="threshold" value="3" onChange={() => {}} size="short" />
        </SettingsRow>
        <SettingsFooter
          onSave={vi.fn()}
          status="idle"
          updatedAt="2026-10-01T00:00:00"
          secondary={<button type="button">Reset to defaults</button>}
        />
      </SettingsSection>
    </TestAuth>,
  );
}

describe("a Settings section for a viewer", () => {
  it("shows the stored value, disabled, with a view-only note", () => {
    form("viewer");
    expect(screen.getByLabelText("Threshold")).toHaveValue("3");
    expect(screen.getByLabelText("Threshold")).toBeDisabled();
    expect(screen.getByTestId("view-only-note")).toHaveTextContent("View only");
  });

  it("has no Save and no secondary action (Reset), but keeps the Last updated line", () => {
    form("viewer");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset to defaults" })).toBeNull();
    expect(screen.getByText(/Last updated/)).toBeInTheDocument();
  });
});

describe("a Settings section for an admin", () => {
  it("is editable, with Save and the secondary action, and no view-only note", () => {
    form("admin");
    expect(screen.getByLabelText("Threshold")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset to defaults" })).toBeInTheDocument();
    expect(screen.queryByTestId("view-only-note")).toBeNull();
  });
});
