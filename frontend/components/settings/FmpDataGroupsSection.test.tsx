// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FmpDataGroupsSection } from "@/components/settings/FmpDataGroupsSection";
import { retestGroupVariants, useDataGroups } from "@/lib/hooks/useDataGroups";
import type { DataGroupOut, DataGroupsOut } from "@/lib/api/types";

vi.mock("@/lib/hooks/useDataGroups", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hooks/useDataGroups")>();
  return { ...actual, useDataGroups: vi.fn(), retestGroupVariants: vi.fn() };
});
const mockedHook = vi.mocked(useDataGroups);

afterEach(cleanup);

function group(overrides: Partial<DataGroupOut>): DataGroupOut {
  return {
    key: "fundamentals",
    label: "Fundamentals",
    wired: true,
    enabled: true,
    state: "live",
    reason: "live",
    required_tier: "Starter",
    restricted_since: null,
    last_success_at: "2026-09-28T03:10:00Z",
    last_error: null,
    feeds: ["Financials", "Ratios"],
    can_toggle: true,
    ...overrides,
  };
}

function mockData(groups: DataGroupOut[]) {
  const data: DataGroupsOut = {
    master_on: true,
    fmp_plan: "Ultimate",
    tiers: ["Starter", "Premium", "Ultimate"],
    key_problem_at: null,
    key_problem_detail: null,
    groups,
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined } as any);
}

describe("FmpDataGroupsSection", () => {
  it("renders a cached_only group with the neutral Badge tone, not a raw zinc class", () => {
    mockData([group({ key: "news", label: "News", state: "cached_only", reason: "user_off" })]);
    render(<FmpDataGroupsSection />);

    const pill = screen.getByText("Cached only");
    expect(pill.className).not.toMatch(/zinc/);
    // Badge's neutral tone (components/ui/badge.tsx) -- the same treatment
    // used elsewhere in the app for a value with no Pass/Fail read.
    expect(pill.className).toMatch(/bg-surface-2/);
    expect(pill.className).toMatch(/text-text-secondary/);
  });

  it("has a sentence-case heading that matches the Settings nav label", () => {
    mockData([group({})]);
    render(<FmpDataGroupsSection />);
    expect(screen.getByRole("heading", { name: "FMP data groups" })).toBeInTheDocument();
  });

  it("still renders a live group with the positive tone", () => {
    mockData([group({})]);
    render(<FmpDataGroupsSection />);

    const pill = screen.getByText("Live");
    expect(pill.className).toMatch(/text-positive/);
  });

  it("keeps a group live and notes the request variants the plan refuses, with a Re-test button", async () => {
    const quarter = (name: string) => ({
      key: `/${name}?limit=12&period=quarter`,
      label: `Quarterly ${name} (limit 12)`,
      restricted_since: "2026-10-02T03:00:00Z",
      last_error: null,
      last_probe_at: null,
    });
    mockData([group({ unavailable_variants: [quarter("income statement"), quarter("balance sheet")] })]);
    vi.mocked(retestGroupVariants).mockResolvedValue({} as never);
    render(<FmpDataGroupsSection />);

    expect(screen.getByText("Live")).toBeInTheDocument(); // the group itself is not restricted
    expect(screen.getByText("Quarterly data not on plan: income statement, balance sheet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Re-test" }));
    await waitFor(() => expect(retestGroupVariants).toHaveBeenCalledWith("fundamentals"));
  });

  it("shows no note and no Re-test button when nothing is refused", () => {
    mockData([group({})]);
    render(<FmpDataGroupsSection />);
    expect(screen.queryByText(/not on plan/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-test" })).toBeNull();
  });
});
