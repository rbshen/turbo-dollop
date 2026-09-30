// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Status, Verdict } from "@/components/ui/status";

afterEach(cleanup);

describe("Status", () => {
  it("renders a soft tinted pill for a toned status: tone fill, tone text, no border", () => {
    const { container } = render(<Status tone="positive">Pass</Status>);
    const pill = container.firstElementChild as HTMLElement;
    expect(pill.className).toMatch(/bg-positive\/16/);
    expect(pill.className).toMatch(/text-positive/);
    expect(pill.className).not.toMatch(/border/);
    expect(container.querySelector("[aria-hidden]")).toBeNull();
  });

  it("renders neutral as a surface-2 pill (not plain text)", () => {
    const { container } = render(<Status tone="neutral">Not scored</Status>);
    const pill = container.firstElementChild as HTMLElement;
    expect(pill.className).toMatch(/bg-surface-2/);
    expect(pill.className).toMatch(/text-text-secondary/);
  });

  it.each([
    ["strong", "positive-strong"],
    ["warn", "warn"],
    ["caution", "caution"],
    ["negative", "negative"],
    ["speculative", "chart-purple"],
  ] as const)("uses the %s tone token", (tone, token) => {
    const { container } = render(<Status tone={tone}>x</Status>);
    const pill = container.firstElementChild as HTMLElement;
    expect(pill.className).toContain(`bg-${token}/16`);
    expect(pill.className).toContain(`text-${token}`);
  });

  it("is regular size by default and quieter when compact, with the same tint", () => {
    const { container: regular } = render(<Status tone="warn">x</Status>);
    const { container: compact } = render(
      <Status tone="warn" size="compact">
        x
      </Status>,
    );
    const r = regular.firstElementChild as HTMLElement;
    const c = compact.firstElementChild as HTMLElement;
    expect(r.className).toMatch(/text-xs/);
    expect(c.className).toMatch(/text-\[11px\]/);
    expect(c.className).toMatch(/py-0\.5/);
    expect(c.className).toMatch(/bg-warn\/16/);
  });

  it("renders a direction glyph inside the pill when direction is given", () => {
    const { container } = render(
      <Status tone="negative" direction="down">
        -1.20%
      </Status>,
    );
    expect(container.querySelector("[aria-hidden]")?.textContent).toBe("▼");
    expect(container.firstElementChild?.className).toMatch(/bg-negative\/16/);
  });
});

describe("Verdict", () => {
  it("renders the same pill as Status", () => {
    const { container: a } = render(<Verdict tone="strong">Strong pass</Verdict>);
    const { container: b } = render(<Status tone="strong">Strong pass</Status>);
    expect((a.firstElementChild as HTMLElement).className).toBe((b.firstElementChild as HTMLElement).className);
  });
});
