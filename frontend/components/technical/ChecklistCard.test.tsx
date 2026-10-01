// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChecklistCard } from "@/components/technical/ChecklistCard";

afterEach(cleanup);

const items = [{ key: "a", label: "First check", passed: true }] as unknown as React.ComponentProps<typeof ChecklistCard>["items"];

function card(collapsible: boolean) {
  return render(
    <ChecklistCard
      title="Checklist"
      statusLabel="Pass"
      statusTone="positive"
      blurb="Blurb"
      items={items}
      disclaimer="Disclaimer"
      collapsible={collapsible}
    />,
  );
}

describe("ChecklistCard: the details toggle", () => {
  it("is collapsed to start, and expands and collapses with the trigger", () => {
    card(true);
    const trigger = screen.getByRole("button");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("First check")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("First check")).toBeVisible();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("carries a collapsed 'Show details' label and an expanded 'Hide details' label", () => {
    card(true);
    const trigger = screen.getByRole("button");
    expect(trigger).toHaveTextContent(/Show details/);
    expect(trigger).toHaveTextContent(/Hide details/);
  });

  it("has no toggle when it is not collapsible", () => {
    card(false);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("First check")).toBeVisible();
  });

  it("has no plus or minus glyph, and an aria-hidden caret down when collapsed and up when expanded", () => {
    render(<ChecklistCard title="Checklist" statusLabel="Pass" statusTone="positive" blurb="Blurb" items={items} disclaimer="Disclaimer" collapsible />);
    const trigger = screen.getByRole("button");
    expect(trigger.textContent).not.toMatch(/[+\u2212]/);
    expect(trigger).toHaveTextContent("Show details");
    expect(trigger).toHaveTextContent("Hide details");
    const icons = Array.from(trigger.querySelectorAll("svg"));
    expect(icons).toHaveLength(2);
    expect(icons.every((i) => i.getAttribute("aria-hidden") === "true")).toBe(true);
    // CSS decides which one shows: the down caret hides when the panel is open, the up caret shows only then.
    expect(icons[0]).toHaveClass("group-data-[panel-open]:hidden");
    expect(icons[1]).toHaveClass("hidden", "group-data-[panel-open]:block");
  });
});
