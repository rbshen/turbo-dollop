// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnalysisSectionCard, type ReasoningBullet } from "@/components/shared/AnalysisSectionCard";

afterEach(cleanup);

function card(bullets: ReasoningBullet[] = [{ key: "b1", text: "Revenue (35%, 88/100): Grows every year", tierClassName: "text-positive" }]) {
  return render(
    <AnalysisSectionCard
      title="Financials"
      score={82}
      verdict="Pass"
      blurb="Blurb"
      methodology="Method"
      bullets={bullets}
    />,
  );
}

describe("AnalysisSectionCard: the reasoning toggle", () => {
  it("is collapsed to start, and expands and collapses with the trigger", () => {
    card();
    const trigger = screen.getByRole("button");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Grows every year/)).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Grows every year/)).toBeVisible();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("carries a collapsed 'Show reasoning' label and an expanded 'Hide reasoning' label", () => {
    card();
    const trigger = screen.getByRole("button");
    expect(trigger).toHaveTextContent(/Show reasoning/);
    expect(trigger).toHaveTextContent(/Hide reasoning/);
  });

  it("still toggles with no bullets (nothing to reveal)", () => {
    card([]);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");
  });

  it("has no plus or minus glyph, and an aria-hidden caret down when collapsed and up when expanded", () => {
    render(<AnalysisSectionCard title="Financials" score={82} verdict="Pass" blurb="Blurb" methodology="Method" bullets={[]} />);
    const trigger = screen.getByRole("button");
    expect(trigger.textContent).not.toMatch(/[+\u2212]/);
    expect(trigger).toHaveTextContent("Show reasoning");
    expect(trigger).toHaveTextContent("Hide reasoning");
    const icons = Array.from(trigger.querySelectorAll("svg"));
    expect(icons).toHaveLength(2);
    expect(icons.every((i) => i.getAttribute("aria-hidden") === "true")).toBe(true);
    // CSS decides which one shows: the down caret hides when the panel is open, the up caret shows only then.
    expect(icons[0]).toHaveClass("group-data-[panel-open]:hidden");
    expect(icons[1]).toHaveClass("hidden", "group-data-[panel-open]:block");
  });
});

// Bug fix (session 16): the expanded list used to sit outside the row, indented by a fixed 10.4rem, so it started
// 3.6rem left of the paragraph. It now lives in the same text column as the title and paragraph.
describe("AnalysisSectionCard: the expanded list lines up with the paragraph", () => {
  const column = () => screen.getByText("Blurb").closest('[data-slot="analysis-text-column"]') as HTMLElement;

  it("keeps the title, paragraph, methodology and the list in one text column that is the score column's sibling", () => {
    card();
    fireEvent.click(screen.getByRole("button"));
    const col = column();
    expect(col).not.toBeNull();
    expect(col).toContainElement(screen.getByText("Financials"));
    expect(col).toContainElement(screen.getByText("Method"));
    const list = screen.getByRole("list");
    expect(col).toContainElement(list);
    // The score and the pill are the column's sibling, never its ancestor.
    const score = screen.getByText("82");
    expect(col).not.toContainElement(score);
    expect(score.closest("div")!.parentElement).toBe(col.parentElement);
  });

  it("puts the list flush with the column: no margin or padding on the list's own container, one hanging step inside it", () => {
    card();
    fireEvent.click(screen.getByRole("button"));
    const list = screen.getByRole("list");
    expect(list).toHaveClass("list-disc", "pl-5");
    expect(list.className).not.toMatch(/(^|\s)(ml|mx|pl)-\[/);
    expect(list.className).not.toMatch(/10\.4rem/);
    // Nothing between the column and the list adds a left offset.
    for (let el: HTMLElement | null = list.parentElement; el && el !== column(); el = el.parentElement) {
      expect(el.className).not.toMatch(/(^|\s)(-?ml|-?pl|-?px|-?mx)-/);
    }
  });

  it("is the same column in both states, so toggling never moves it", () => {
    card();
    const before = column();
    fireEvent.click(screen.getByRole("button"));
    expect(column()).toBe(before);
    expect(column()).toContainElement(screen.getByRole("list"));
    fireEvent.click(screen.getByRole("button"));
    expect(column()).toBe(before);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("keeps the toggle in the column's header row at the right, and the whole card clickable through the toggle's overlay", () => {
    card();
    const trigger = screen.getByRole("button");
    expect(trigger.parentElement).toHaveClass("flex", "justify-between");
    expect(column()).toContainElement(trigger);
    expect(trigger).toHaveClass("shrink-0", "after:absolute", "after:inset-0");
    expect(trigger.closest("[data-slot=collapsible]")).toHaveClass("relative");
  });

  it("paints the list above the overlay, so it neither toggles nor loses text selection", () => {
    card();
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("list").closest("[data-slot=collapsible-content]")).toHaveClass("relative");
  });

  it("puts the list in the text column when there is no score column too", () => {
    render(<AnalysisSectionCard title="Financials" score={null} verdict="" blurb="Blurb" methodology="Method" bullets={[{ key: "b", text: "A bullet", tierClassName: "" }]} />);
    fireEvent.click(screen.getByRole("button"));
    expect(column()).toContainElement(screen.getByRole("list"));
  });
});

describe("AnalysisSectionCard: bullet tooltips", () => {
  it("wraps only a bullet that has a tooltip in a focusable trigger", () => {
    card([
      { key: "a", text: "Plain bullet", tierClassName: "text-text-primary" },
      { key: "b", text: "Noted bullet", tierClassName: "text-text-tertiary", tooltip: "Why" },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Show reasoning/ }));
    expect(screen.getByText("Plain bullet").closest("button")).toBeNull();
    expect(screen.getByRole("button", { name: "Noted bullet" })).toBeInTheDocument();
  });
});
