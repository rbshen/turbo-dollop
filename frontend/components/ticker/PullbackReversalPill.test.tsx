// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PullbackPill } from "@/components/ticker/PullbackPill";
import { ReversalPill } from "@/components/ticker/ReversalPill";
import { Status } from "@/components/ui/status";

afterEach(cleanup);

describe("PullbackPill", () => {
  it.each([
    ["pending", "Pullback pending", "warn"],
    ["recovered", "Pullback recovered", "positive"],
    ["invalidated", "Trend invalidated", "negative"],
  ] as const)("%s renders the shared pill in the %s tone", (status, label, tone) => {
    render(<PullbackPill status={status} />);
    const pill = screen.getByText(label);
    expect(pill.className).toContain(`bg-${tone}/16`);
    expect(pill.className).toContain(`text-${tone}`);
    expect(pill.className).not.toMatch(/border/);
  });

  it("is the same pill as Status", () => {
    const { container: a } = render(<PullbackPill status="pending" />);
    const { container: b } = render(<Status tone="warn" title="x">Pullback pending</Status>);
    expect((a.firstElementChild as HTMLElement).className).toBe((b.firstElementChild as HTMLElement).className);
  });

  it("renders nothing for no pullback / null", () => {
    expect(render(<PullbackPill status="no_pullback" />).container).toBeEmptyDOMElement();
    expect(render(<PullbackPill status={null} />).container).toBeEmptyDOMElement();
  });
});

describe("ReversalPill", () => {
  it("renders a live confirmed reversal as positive and a stale one as neutral", () => {
    render(
      <>
        <ReversalPill status="confirmed" />
        <ReversalPill status="confirmed_stale" />
      </>,
    );
    expect(screen.getByText("Reversal").className).toContain("bg-positive/16");
    expect(screen.getByText("Reversal (stale)").className).toContain("bg-surface-2");
  });

  it("renders nothing when not present", () => {
    expect(render(<ReversalPill status="not_present" />).container).toBeEmptyDOMElement();
  });
});
