// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig, mutate } from "swr";
import type { ReactNode } from "react";

import { FmpDataGroupsSection } from "@/components/settings/FmpDataGroupsSection";
import { StatusSection } from "@/components/settings/StatusSection";
import * as client from "@/lib/api/client";
import type { DataGroupOut, DataGroupsOut } from "@/lib/api/types";
import { useCronHealth } from "@/lib/hooks/useCronHealth";

// The REAL useDataGroups hook (real SWR, one shared key) over a mocked network
// layer, so the card and the table are proven to share data as in the app.
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
  apiPut: vi.fn(),
}));
vi.mock("@/lib/hooks/useCronHealth");

const mockedFetch = vi.mocked(client.apiFetch);
const mockedPut = vi.mocked(client.apiPut);

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

function payload(overrides: Partial<DataGroupsOut> = {}): DataGroupsOut {
  return {
    master_on: true,
    fmp_plan: "Ultimate",
    tiers: ["Starter", "Premium", "Ultimate"],
    key_problem_at: null,
    key_problem_detail: null,
    groups: [group({}), group({ key: "analyst_ratings", label: "Analyst ratings", required_tier: "Premium", feeds: ["Analyst Ratings"] })],
    ...overrides,
  };
}

// No request deduping, so a test never inherits the previous test's in-flight fetch.
function Fresh({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ dedupingInterval: 0 }}>{children}</SWRConfig>;
}

beforeEach(async () => {
  await mutate(() => true, undefined, { revalidate: false }); // empty the shared SWR cache
  mockedFetch.mockResolvedValue(payload());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useCronHealth).mockReturnValue({ data: { enabled: true, jobs: [] }, error: undefined } as any);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FMP status card location", () => {
  it("sits inside FMP data groups, BELOW the per-group table", async () => {
    render(<FmpDataGroupsSection />, { wrapper: Fresh });
    const table = await screen.findByRole("table");
    const heading = await screen.findByRole("heading", { name: "FMP status" });
    expect(table.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // ...and inside the same section as the table
    const section = screen.getByRole("heading", { name: "FMP data groups" }).parentElement as HTMLElement;
    expect(within(section).getByRole("table")).toBe(table);
    expect(within(section).getByRole("heading", { name: "FMP status" })).toBe(heading);
  });

  it("carries the whole card: the plan select, the master control with its badge, and the description", async () => {
    render(<FmpDataGroupsSection />, { wrapper: Fresh });
    expect(await screen.findByLabelText("My FMP plan")).toHaveValue("Ultimate");
    expect(screen.getByLabelText("FMP master switch")).toBeChecked();
    expect(screen.getByText("On", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText(/serves cached data\s+only/)).toBeInTheDocument();
    expect(screen.getByText(/Per-group toggles are in the table above/)).toBeInTheDocument();
  });

  it("shows the API-key problem line in the card when there is one", async () => {
    mockedFetch.mockResolvedValue(payload({ key_problem_at: "2026-09-29T10:00:00Z", key_problem_detail: "HTTP 401" }));
    render(<FmpDataGroupsSection />, { wrapper: Fresh });
    expect(await screen.findByText(/FMP rejected the API key \(HTTP 401\)/)).toBeInTheDocument();
  });

  it("is no longer rendered by Scheduled jobs, which keeps only its jobs table", async () => {
    render(<StatusSection />, { wrapper: Fresh });
    expect(await screen.findByRole("heading", { name: "Scheduled jobs" })).toBeInTheDocument();
    expect(screen.queryByText("FMP status")).toBeNull();
    expect(screen.queryByLabelText("My FMP plan")).toBeNull();
    expect(screen.queryByLabelText("FMP master switch")).toBeNull();
    expect(mockedFetch).not.toHaveBeenCalled(); // and Scheduled jobs no longer fetches the data groups
  });

  it("makes one shared fetch of the data groups for the table and the card together", async () => {
    render(<FmpDataGroupsSection />, { wrapper: Fresh });
    await screen.findByLabelText("My FMP plan");
    expect(mockedFetch.mock.calls.filter(([path]) => path === "/config/data-groups")).toHaveLength(1);
  });
});

describe("the table follows the card's controls (shared data, card below the table)", () => {
  it("re-renders the table's states when the plan is changed in the card", async () => {
    // Plan Starter: the Premium-tier group is above the plan; the response to the
    // plan change (what the API returns) flips it live.
    mockedFetch.mockResolvedValue(
      payload({
        fmp_plan: "Starter",
        groups: [
          group({}),
          group({ key: "analyst_ratings", label: "Analyst ratings", required_tier: "Premium", state: "not_on_plan", reason: "above_plan", can_toggle: false }),
        ],
      }),
    );
    render(<FmpDataGroupsSection />, { wrapper: Fresh });
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Not on plan")).toBeInTheDocument();
    expect(screen.getByLabelText("Enable Analyst ratings")).toBeDisabled();

    mockedPut.mockResolvedValue(payload({ fmp_plan: "Premium" }));
    fireEvent.change(screen.getByLabelText("My FMP plan"), { target: { value: "Premium" } });
    await waitFor(() => expect(within(table).queryByText("Not on plan")).toBeNull());
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/plan", { fmp_plan: "Premium" });
    expect(screen.getByLabelText("My FMP plan")).toHaveValue("Premium");
    expect(screen.getByLabelText("Enable Analyst ratings")).toBeEnabled();
  });

  it("re-renders the table's states when the master switch is turned off in the card", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<FmpDataGroupsSection />, { wrapper: Fresh });
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("Live")).toHaveLength(2);
    mockedPut.mockResolvedValue(
      payload({
        master_on: false,
        groups: [
          group({ state: "cached_only", reason: "master_off", can_toggle: false }),
          group({ key: "analyst_ratings", label: "Analyst ratings", state: "cached_only", reason: "master_off", can_toggle: false }),
        ],
      }),
    );
    await act(async () => fireEvent.click(screen.getByLabelText("FMP master switch")));
    await waitFor(() => expect(within(table).getAllByText("Cached only")).toHaveLength(2));
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/master", { master_on: false });
    expect(screen.getByText("Off — cache only")).toBeInTheDocument();
    confirm.mockRestore();
  });
});
