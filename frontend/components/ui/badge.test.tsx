// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Badge } from "@/components/ui/badge";
import { Status } from "@/components/ui/status";

afterEach(cleanup);

describe("Badge", () => {
  it("renders the em dash and ignores children when missing", () => {
    render(<Badge missing>Pass</Badge>);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("Pass")).not.toBeInTheDocument();
  });

  it("renders its label for a normal tone", () => {
    render(<Badge tone="positive">Pass</Badge>);
    expect(screen.getByText("Pass")).toBeInTheDocument();
  });

  it("is the same pill as Status for the same tone and size", () => {
    const { container: badge } = render(<Badge tone="caution" size="compact">92</Badge>);
    const { container: status } = render(<Status tone="caution" size="compact">92</Status>);
    expect((badge.firstElementChild as HTMLElement).className).toBe((status.firstElementChild as HTMLElement).className);
  });

  it("renders the missing state as a neutral pill in the requested size", () => {
    const { container } = render(<Badge missing size="compact" />);
    const pill = container.firstElementChild as HTMLElement;
    expect(pill.className).toMatch(/bg-surface-2/);
    expect(pill.className).toMatch(/text-\[11px\]/);
    expect(pill.className).toMatch(/text-text-tertiary/);
  });
});
