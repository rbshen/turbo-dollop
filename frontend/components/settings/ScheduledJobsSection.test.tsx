// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  it("has a sentence-case heading that matches the Settings nav label", () => {
    mockData([job({})]);
    render(<ScheduledJobsSection />);
    expect(screen.getByRole("heading", { name: "Scheduled jobs" })).toBeInTheDocument();
  });

  it("lets the Time cell wrap so a long label cannot spill into the Status column", () => {
    mockData([job({ time_label: "1st–5th, 2:50 AM" })]);
    render(<ScheduledJobsSection />);

    const cell = screen.getByText("1st–5th, 2:50 AM");
    expect(cell.className).toMatch(/whitespace-normal/);
  });

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

// Characterization of the cadence strip (Daily, Weekly, Monthly). How an entry is found and how it shows as
// selected are the markup-dependent parts, so they live in these helpers.
const groupEntry = (name: RegExp) => screen.getByRole("tab", { name });
const groupSelected = (el: HTMLElement) => el.getAttribute("aria-selected") === "true";

describe("ScheduledJobsSection: the cadence strip", () => {
  const jobs = [
    job({ job_name: "daily_a", description: "Daily A", cadence_group: "daily", sort_minutes: 200 }),
    job({ job_name: "daily_b", description: "Daily B", cadence_group: "daily", sort_minutes: 100 }),
    job({ job_name: "weekly_a", description: "Weekly A", cadence_group: "weekly" }),
  ];

  it("starts on Daily, shows each group's job count and lists only that group, earliest first", () => {
    mockData(jobs);
    render(<ScheduledJobsSection />);
    expect(groupEntry(/^Daily/)).toHaveTextContent("2");
    expect(groupEntry(/^Weekly/)).toHaveTextContent("1");
    expect(groupEntry(/^Monthly/)).toHaveTextContent("0");
    expect(groupSelected(groupEntry(/^Daily/))).toBe(true);
    expect(groupSelected(groupEntry(/^Weekly/))).toBe(false);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Daily B");
    expect(rows[1]).toHaveTextContent("Daily A");
  });

  it("switches to the chosen group, and says so when it has no jobs", () => {
    mockData(jobs);
    render(<ScheduledJobsSection />);
    fireEvent.click(groupEntry(/^Weekly/));
    expect(screen.getByText("Weekly A")).toBeInTheDocument();
    expect(screen.queryByText("Daily A")).not.toBeInTheDocument();
    expect(groupSelected(groupEntry(/^Weekly/))).toBe(true);
    expect(groupSelected(groupEntry(/^Daily/))).toBe(false);
    fireEvent.click(groupEntry(/^Monthly/));
    expect(screen.getByText("No monthly jobs.")).toBeInTheDocument();
  });
});

// Session 16: the strip is the shared Tabs primitive (with its count figure), neutral selected state, a named list.
describe("ScheduledJobsSection: the cadence strip is a neutral tab list", () => {
  it("is a named tablist with Daily, Weekly and Monthly tabs", () => {
    mockData([job({})]);
    render(<ScheduledJobsSection />);
    const list = screen.getByRole("tablist", { name: "Job cadence" });
    expect(within(list).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Daily1", "Weekly0", "Monthly0"]);
  });

  it("draws the selected tab with the neutral underline and text-primary, and no brand blue", () => {
    mockData([job({})]);
    render(<ScheduledJobsSection />);
    expect(groupEntry(/^Daily/)).toHaveClass("data-[active]:border-text-primary", "data-[active]:text-text-primary");
    for (const name of [/^Daily/, /^Weekly/, /^Monthly/]) expect(groupEntry(name).className).not.toMatch(/brand/);
  });

  it("moves between tabs with the arrow keys", async () => {
    mockData([job({})]);
    render(<ScheduledJobsSection />);
    const daily = groupEntry(/^Daily/);
    daily.focus();
    fireEvent.keyDown(daily, { key: "ArrowRight" });
    await waitFor(() => expect(groupEntry(/^Weekly/)).toHaveFocus());
  });
});

describe("ScheduledJobsSection: last failure", () => {
  const failure = {
    job_name: "pipeline.backup_db",
    started_at: "2026-10-18T03:30:02.931411",
    finished_at: "2026-10-18T03:30:02.987923",
    status: "failure",
    error_summary: "InsufficientDiskSpaceError: Refusing to start backup: 1.58 GB free on the volume holding /home/shen/fathom/backend/backups",
  };
  const latest = { ...failure, started_at: "2026-10-19T03:30:03.056298", status: "success", error_summary: "158.1 MB, 1 old backup(s) pruned" };

  it("shows the time and a short message for a failure that a later success did not erase", () => {
    mockData([job({ health_status: "ok", message: "158.1 MB, 1 old backup(s) pruned", last_run: latest, last_failure: failure })]);
    render(<ScheduledJobsSection />);

    expect(screen.getByText("Success")).toBeInTheDocument(); // the latest status is untouched
    const line = screen.getByTestId("last-failure");
    expect(line).toHaveTextContent("Last failure 2026-10-18 03:30 UTC: InsufficientDiskSpaceError: Refusing to start backup");
    expect(line.getAttribute("title")).toContain("1.58 GB free on the volume holding /home/shen/fathom/backend/backups"); // full text on hover
  });

  it("truncates a long message and keeps the whole text in the hover title", () => {
    const long = "RuntimeError: " + "x".repeat(300);
    mockData([job({ last_run: latest, last_failure: { ...failure, error_summary: long } })]);
    render(<ScheduledJobsSection />);

    const line = screen.getByTestId("last-failure");
    expect(line.textContent!.endsWith("…")).toBe(true);
    expect(line.textContent!.length).toBeLessThan(200);
    expect(line.getAttribute("title")).toContain("x".repeat(300));
  });

  it("is quiet text: tertiary tone, no accent colour, no control", () => {
    mockData([job({ last_run: latest, last_failure: failure })]);
    render(<ScheduledJobsSection />);

    const line = screen.getByTestId("last-failure");
    expect(line.className).toMatch(/text-text-tertiary/);
    expect(line.className).not.toMatch(/negative|warn|brand|positive|sky-|red-|amber-/);
    expect(line.querySelector("button, a, input")).toBeNull();
  });

  it("shows nothing extra for a job with no failure in the window", () => {
    mockData([job({ last_run: latest, last_failure: null }), job({ job_name: "other", description: "Other job", last_run: latest })]);
    render(<ScheduledJobsSection />);

    expect(screen.queryByTestId("last-failure")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Last failure/);
  });

  it("does not repeat the failure on a row whose latest run is that failure", () => {
    mockData([job({ health_status: "failed", message: failure.error_summary, last_run: failure, last_failure: failure })]);
    render(<ScheduledJobsSection />);

    expect(screen.getByText("Failed").className).toMatch(/text-negative/);
    expect(screen.queryByTestId("last-failure")).toBeNull();
  });

  it("shows the earlier failure under a red row when the latest failure is a different run", () => {
    mockData([job({ health_status: "failed", message: "boom", last_run: { ...failure, started_at: "2026-10-20T03:30:00" }, last_failure: { ...failure, started_at: "2026-10-18T03:30:02" } })]);
    render(<ScheduledJobsSection />);
    // The latest failure IS last_failure in the API, so a differing started_at cannot occur; the guard compares runs, not statuses.
    expect(screen.getByTestId("last-failure")).toBeInTheDocument();
  });

  it("formats the stored UTC time without parsing it into the browser's zone", async () => {
    const { formatFailureTime } = await import("@/components/settings/ScheduledJobsSection");
    expect(formatFailureTime("2026-10-18T03:30:02.931411")).toBe("2026-10-18 03:30 UTC");
  });
});
