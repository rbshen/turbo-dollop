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
  it("renders a skipped job's status dot with the neutral text-tertiary tone, not the retired sky-blue", () => {
    mockData([job({ job_name: "nightly_liquidity_zone_calculation", health_status: "skipped", message: "skipped (group daily_prices off)" })]);
    render(<ScheduledJobsSection />);

    const dot = document.querySelector(".rounded-full.bg-text-tertiary");
    expect(dot).not.toBeNull();
    expect(document.body.innerHTML).not.toMatch(/sky-/);
    expect(screen.getByText("skipped (group daily_prices off)").className).toMatch(/text-text-tertiary/);
  });

  it("renders an unknown job's status dot with the same neutral tone as skipped", () => {
    mockData([job({ job_name: "nightly_market_breadth", health_status: "unknown", message: null })]);
    render(<ScheduledJobsSection />);

    const dot = document.querySelector(".rounded-full.bg-text-tertiary");
    expect(dot).not.toBeNull();
  });

  it("still renders a failed job with the negative tone", () => {
    mockData([job({ health_status: "failed", message: "boom" })]);
    render(<ScheduledJobsSection />);

    expect(document.querySelector(".rounded-full.bg-negative")).not.toBeNull();
    expect(screen.getByText("boom").className).toMatch(/text-negative/);
  });
});
