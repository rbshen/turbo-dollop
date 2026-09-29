// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";
import { useCronHealth } from "@/lib/hooks/useCronHealth";
import type { CronHealthOut, CronJobHealthOut } from "@/lib/api/types";

vi.mock("@/lib/hooks/useCronHealth");
const mockedHook = vi.mocked(useCronHealth);

afterEach(cleanup);

function job(overrides: Partial<CronJobHealthOut>): CronJobHealthOut {
  return {
    job_name: "nightly_fundamentals_fetch",
    health_status: "ok",
    message: null,
    last_run: null,
    last_success_at: "2026-09-28T02:00:00Z",
    skipped_since: null,
    description: "Nightly fundamentals fetch",
    cadence_group: "daily",
    time_label: "2:00 AM",
    sort_minutes: 120,
    ...overrides,
  };
}

function mockData(jobs: CronJobHealthOut[]) {
  const data: CronHealthOut = { enabled: true, jobs };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined } as any);
}

describe("ScheduledJobsSection", () => {
  it("renders a skipped job as a neutral pill, not the retired sky-blue", () => {
    mockData([job({ job_name: "nightly_liquidity_zone_calculation", health_status: "skipped", message: "skipped (group daily_prices off)" })]);
    render(<ScheduledJobsSection />);

    const pill = screen.getByText("Skipped");
    expect(pill.className).toMatch(/bg-surface-2/);
    expect(pill.className).toMatch(/text-text-secondary/);
    expect(document.body.innerHTML).not.toMatch(/sky-/);
    expect(screen.getByText("skipped (group daily_prices off)").className).toMatch(/text-text-tertiary/);
  });

  it("renders an unknown job as the same neutral pill as skipped, told apart by its word", () => {
    mockData([job({ job_name: "nightly_market_breadth", health_status: "unknown", message: null })]);
    render(<ScheduledJobsSection />);

    const pill = screen.getByText("Unknown");
    expect(pill.className).toMatch(/bg-surface-2/);
    expect(document.querySelector(".rounded-full")).toBeNull();
  });

  it("still renders a failed job with the negative tone", () => {
    mockData([job({ health_status: "failed", message: "boom" })]);
    render(<ScheduledJobsSection />);

    expect(screen.getByText("Failed").className).toMatch(/text-negative/);
    expect(screen.getByText("boom").className).toMatch(/text-negative/);
  });
});
