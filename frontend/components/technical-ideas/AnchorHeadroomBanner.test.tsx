// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnchorHeadroomBanner } from "@/components/technical-ideas/AnchorHeadroomBanner";
import type { AnchorHeadroomOut, WarrenWatchOut } from "@/lib/api/types";
import { TestAuth } from "@/lib/auth/testAuth";

afterEach(cleanup);

const WARNING: AnchorHeadroomOut = {
  days: 298, level: "warning", anchor: "2025-10-15T15:30:00", slice_start: "2025-12-20",
  warning_date: "2026-12-19", urgent_date: "2027-01-18", deadline_date: "2027-04-17",
};
const URGENT: AnchorHeadroomOut = { ...WARNING, days: 250, level: "urgent", warning_date: "2026-12-19", urgent_date: "2027-01-18" };

function draw(role: "admin" | "viewer", headroom: AnchorHeadroomOut | null | undefined, loaded = true) {
  const data: WarrenWatchOut | undefined = loaded ? { as_of: null, rows: [], anchor_headroom: headroom } : undefined;
  return render(
    <TestAuth role={role}>
      <AnchorHeadroomBanner useData={() => ({ data })} />
    </TestAuth>,
  );
}

describe("AnchorHeadroomBanner", () => {
  it("shows the warning for an admin: what is happening, the days, the urgent date, the deadline and the runbook pointer", () => {
    draw("admin", WARNING);
    const banner = screen.getByRole("status", { name: "Warren replay start: warning" });
    expect(banner).toHaveTextContent("The Warren replay start date is running out of warm-up history.");
    expect(banner).toHaveTextContent("Oct 15, 2025 15:30 ET");
    expect(banner).toHaveTextContent("298 days of cached history");
    expect(banner).toHaveTextContent("becomes urgent on Jan 18, 2027");
    expect(banner).toHaveTextContent("hard deadline is Apr 17, 2027");
    expect(banner).toHaveTextContent("Re-anchor: see the runbook in docs/specs/warren-signals-page.md");
  });

  it("draws urgent in the stronger style, as an alert, in the past tense", () => {
    draw("admin", URGENT);
    const banner = screen.getByRole("alert", { name: "Warren replay start: urgent" });
    expect(banner).toHaveTextContent("Urgent: the Warren replay start date is running out of warm-up history.");
    expect(banner).toHaveTextContent("250 days of cached history");
    expect(banner).toHaveTextContent("became urgent on Jan 18, 2027");
    expect(banner.className).toContain("border-negative/40");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("uses the warn style for the warning", () => {
    draw("admin", WARNING);
    expect(screen.getByRole("status").className).toContain("border-warn/40");
  });

  it("has no dismiss control", () => {
    draw("admin", URGENT);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is hidden when the level is none (no data), while loading, and for a viewer", () => {
    draw("admin", null);
    expect(screen.queryByRole("status")).toBeNull();
    cleanup();
    draw("admin", undefined, false);
    expect(screen.queryByRole("status")).toBeNull();
    cleanup();
    draw("viewer", WARNING);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    cleanup();
    draw("viewer", URGENT);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
