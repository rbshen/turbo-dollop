// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnalysisSectionCard } from "@/components/shared/AnalysisSectionCard";

afterEach(cleanup);

function card(bullets = [{ key: "b1", text: "Revenue (35%, 88/100): Grows every year", tierClassName: "text-positive" }]) {
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
