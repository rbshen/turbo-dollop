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

// Session 16: this card has no side column (a single stack), so the expanded details already start at the same left
// edge as the title and paragraph. Pinned so a future column cannot silently reintroduce the offset.
describe("ChecklistCard: the expanded details line up with the paragraph", () => {
  it("has the details and the header text as children of one stack, with no left offset on either path", () => {
    const { container } = card(true);
    fireEvent.click(screen.getByRole("button"));
    const root = container.firstElementChild as HTMLElement;
    const textBlock = screen.getByText("Blurb").parentElement as HTMLElement;
    const details = screen.getByText("First check").closest("ul")!.closest("[data-slot=collapsible-content]") as HTMLElement;
    // Path from the root to each: the header row holds the text block, the collapsible holds the details.
    expect(textBlock.parentElement!.parentElement).toBe(root);
    expect(details.parentElement!.parentElement).toBe(root);
    for (const el of [textBlock, textBlock.parentElement!, details, details.parentElement!, screen.getByText("First check").closest("ul")!]) {
      expect(el.className).not.toMatch(/(^|\s)(-?ml|-?pl|-?px|-?mx)-/);
    }
  });

  it("is the same in the always-expanded variant", () => {
    const { container } = card(false);
    const root = container.firstElementChild as HTMLElement;
    expect(screen.getByText("First check").closest("ul")!.parentElement).toBe(root);
  });
});
