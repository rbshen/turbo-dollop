// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig, mutate } from "swr";
import type { ReactNode } from "react";

import { FmpDataGroupsSection } from "@/components/settings/FmpDataGroupsSection";
import * as client from "@/lib/api/client";
import type { DataGroupOut, DataGroupsOut } from "@/lib/api/types";
import { disableWarning } from "@/lib/dataGroups";

// The REAL useDataGroups hook (real SWR) over a mocked network layer.
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
  apiPut: vi.fn(),
}));

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

const FUNDAMENTALS = group({});
const NEWS = group({ key: "news", label: "News", enabled: false, state: "cached_only", reason: "user_off", feeds: ["News tab"] });
const ANALYST = group({
  key: "analyst_ratings",
  label: "Analyst ratings",
  required_tier: "Premium",
  state: "not_on_plan",
  reason: "above_plan",
  can_toggle: false,
  feeds: ["Analyst Ratings"],
});

function payload(overrides: Partial<DataGroupsOut> = {}): DataGroupsOut {
  return {
    master_on: true,
    fmp_plan: "Starter",
    tiers: ["Starter", "Premium", "Ultimate"],
    key_problem_at: null,
    key_problem_detail: null,
    groups: [FUNDAMENTALS, NEWS, ANALYST],
    ...overrides,
  };
}

function Fresh({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ dedupingInterval: 0 }}>{children}</SWRConfig>;
}

async function renderSection() {
  render(<FmpDataGroupsSection />, { wrapper: Fresh });
  await screen.findByLabelText("My FMP plan");
}

const tableEl = () => screen.getByRole("table");
const master = () => screen.getByRole("switch", { name: "FMP master switch" }) as HTMLInputElement;
const plan = () => screen.getByLabelText("My FMP plan") as unknown as HTMLSelectElement;
const enable = (label: string) => screen.getByRole("switch", { name: `Enable ${label}` }) as HTMLInputElement;
const tier = (label: string) => screen.getByLabelText(`Required tier for ${label}`) as unknown as HTMLSelectElement;
const rowOf = (label: string) => screen.getByText(label, { selector: "div" }).closest("tr") as HTMLElement;

beforeEach(async () => {
  await mutate(() => true, undefined, { revalidate: false });
  mockedFetch.mockResolvedValue(payload());
  mockedPut.mockResolvedValue(payload());
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("FMP settings controls: kit primitives and accessible names", () => {
  it("uses Switch for every on/off and native Select for every choice: no checkboxes or bare selects are left", async () => {
    await renderSection();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.getAllByRole("switch")).toHaveLength(1 + 3); // master + one per group
    expect(screen.getAllByRole("combobox")).toHaveLength(1 + 3); // plan + one tier per group
    for (const el of screen.getAllByRole("switch")) expect(el).toHaveAttribute("type", "checkbox");
    for (const el of screen.getAllByRole("combobox")) expect(el.tagName).toBe("SELECT");
  });

  it("gives every Switch and Select an accessible name from its visible label or row", async () => {
    await renderSection();
    expect(master()).toHaveAccessibleName("FMP master switch");
    expect(plan()).toHaveAccessibleName("My FMP plan");
    for (const label of ["Fundamentals", "News", "Analyst ratings"]) {
      expect(enable(label)).toHaveAccessibleName(`Enable ${label}`);
      expect(tier(label)).toHaveAccessibleName(`Required tier for ${label}`);
    }
    for (const el of [...screen.getAllByRole("switch"), ...screen.getAllByRole("combobox")]) {
      expect(el).toHaveAccessibleName();
    }
  });

  it("uses the medium size token for the plan and tier selects (Ultimate does not fit the 96px short field)", async () => {
    await renderSection();
    for (const select of [plan(), tier("Fundamentals"), tier("News"), tier("Analyst ratings")]) {
      expect(select.parentElement).toHaveClass("w-44");
      expect(select).toHaveClass("h-9");
      expect(select.className).not.toMatch(/outline-none/);
    }
  });

  it("never suppresses the focus ring on a Switch or Select", async () => {
    await renderSection();
    for (const el of [master(), enable("News")]) {
      expect((el.nextElementSibling as HTMLElement).className).toMatch(/peer-focus-visible:outline-2/);
      expect(el.className).not.toMatch(/outline-none/);
    }
  });

  it("keeps the table a table: headers, one row per group, controls in the cells", async () => {
    await renderSection();
    expect(within(tableEl()).getAllByRole("row")).toHaveLength(1 + 3);
    expect(within(rowOf("News")).getByRole("switch")).toBe(enable("News"));
    expect(within(rowOf("News")).getByRole("combobox")).toBe(tier("News"));
    expect(document.body.querySelector("[class*='grid-cols-[minmax']")).toBeNull(); // no Settings rows
  });
});

describe("FMP settings controls: state comes from the data", () => {
  it("shows master, plan, every group's enabled state and tier from the fetched data", async () => {
    await renderSection();
    expect(master()).toBeChecked();
    expect(plan().value).toBe("Starter");
    expect(Array.from(plan().options).map((o) => o.value)).toEqual(["Starter", "Premium", "Ultimate"]);
    expect([enable("Fundamentals").checked, enable("News").checked, enable("Analyst ratings").checked]).toEqual([true, false, true]);
    expect(tier("Analyst ratings").value).toBe("Premium");
  });

  it("shows the master as off from the data", async () => {
    mockedFetch.mockResolvedValue(payload({ master_on: false }));
    await renderSection();
    expect(master()).not.toBeChecked();
    expect(screen.getByText("Off — cache only")).toBeInTheDocument();
  });

  it("disables a group's Switch when it cannot be toggled, with the reason as its title", async () => {
    await renderSection();
    expect(enable("Analyst ratings")).toBeDisabled();
    expect(enable("Analyst ratings")).toHaveAttribute("title", "Needs the Premium plan or higher.");
    expect(enable("Fundamentals")).toBeEnabled();
    expect(enable("Fundamentals")).not.toHaveAttribute("title");
  });
});

describe("FMP settings controls: master switch", () => {
  it("asks for confirmation before turning off, then calls the same endpoint and payload as before", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await renderSection();
    await act(async () => fireEvent.click(master()));
    expect(confirm).toHaveBeenCalledWith("Disable ALL FMP calls? Every group goes cache-only (nothing is wiped).");
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/master", { master_on: false });
  });

  it("cancelling the confirmation sends nothing and the Switch is still on", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderSection();
    await act(async () => fireEvent.click(master()));
    expect(mockedPut).not.toHaveBeenCalled();
    expect(master()).toBeChecked();
    expect(screen.getByText("On", { selector: "span" })).toBeInTheDocument();
  });

  it("turning it on needs no confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm");
    mockedFetch.mockResolvedValue(payload({ master_on: false }));
    await renderSection();
    await act(async () => fireEvent.click(master()));
    expect(confirm).not.toHaveBeenCalled();
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/master", { master_on: true });
  });

  it("is disabled while its request is in flight, then enabled again", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let release: (v: DataGroupsOut) => void = () => {};
    mockedPut.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await renderSection();
    await act(async () => fireEvent.click(master()));
    expect(master()).toBeDisabled();
    expect(plan()).toBeDisabled();
    await act(async () => release(payload({ master_on: false })));
    await waitFor(() => expect(master()).toBeEnabled());
    expect(master()).not.toBeChecked();
  });

  it("a failed request shows the server's message near the control and keeps the true state", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockedPut.mockRejectedValue(new Error("PUT /config/data-groups/master failed: 422 - master_on: Input should be a valid boolean"));
    await renderSection();
    await act(async () => fireEvent.click(master()));
    expect(screen.getByRole("alert")).toHaveTextContent("master_on: Input should be a valid boolean");
    expect(master()).toBeChecked(); // the data never changed, so the Switch shows the real state
    expect(master()).toBeEnabled();
  });

  it("falls back to 'Update failed' when the error has no detail", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockedPut.mockRejectedValue(new Error("PUT /config/data-groups/master failed: 500"));
    await renderSection();
    await act(async () => fireEvent.click(master()));
    expect(screen.getByRole("alert")).toHaveTextContent("Update failed");
  });
});

describe("FMP settings controls: plan select", () => {
  it("calls the same endpoint and payload as before", async () => {
    await renderSection();
    await act(async () => fireEvent.change(plan(), { target: { value: "Ultimate" } }));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/plan", { fmp_plan: "Ultimate" });
  });

  it("is disabled while in flight and shows the new plan from the response", async () => {
    let release: (v: DataGroupsOut) => void = () => {};
    mockedPut.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await renderSection();
    await act(async () => fireEvent.change(plan(), { target: { value: "Ultimate" } }));
    expect(plan()).toBeDisabled();
    await act(async () => release(payload({ fmp_plan: "Ultimate" })));
    await waitFor(() => expect(plan()).toBeEnabled());
    expect(plan().value).toBe("Ultimate");
  });

  it("a failed request shows the message and leaves the select on the real plan", async () => {
    mockedPut.mockRejectedValue(new Error("PUT /config/data-groups/plan failed: 422 - fmp_plan: bad tier"));
    await renderSection();
    await act(async () => fireEvent.change(plan(), { target: { value: "Ultimate" } }));
    expect(screen.getByRole("alert")).toHaveTextContent("fmp_plan: bad tier");
    expect(plan().value).toBe("Starter");
  });
});

describe("FMP settings controls: per-group Switch", () => {
  it("turning a group off warns with the same text, then calls the same endpoint and payload as before", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await renderSection();
    await act(async () => fireEvent.click(enable("Fundamentals")));
    expect(confirm).toHaveBeenCalledWith(disableWarning(FUNDAMENTALS));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/fundamentals", { enabled: false });
  });

  it("cancelling the confirmation sends nothing and the Switch ends up back on", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderSection();
    await act(async () => fireEvent.click(enable("Fundamentals")));
    expect(mockedPut).not.toHaveBeenCalled();
    expect(enable("Fundamentals")).toBeChecked();
  });

  it("turning a group on needs no confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm");
    await renderSection();
    await act(async () => fireEvent.click(enable("News")));
    expect(confirm).not.toHaveBeenCalled();
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/news", { enabled: true });
  });

  it("disables EVERY control in the table while any request is in flight", async () => {
    let release: (v: DataGroupsOut) => void = () => {};
    mockedPut.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await renderSection();
    await act(async () => fireEvent.click(enable("News")));
    for (const el of [enable("News"), enable("Fundamentals"), tier("News"), tier("Fundamentals"), tier("Analyst ratings")]) {
      expect(el).toBeDisabled();
    }
    await act(async () => release(payload()));
    await waitFor(() => expect(enable("Fundamentals")).toBeEnabled());
  });

  it("a failed request shows the server's message in that group's row and keeps the true state", async () => {
    mockedPut.mockRejectedValue(new Error("PUT /config/data-groups/news failed: 422 - enabled: Input should be a valid boolean"));
    await renderSection();
    await act(async () => fireEvent.click(enable("News")));
    const alert = within(rowOf("News")).getByRole("alert");
    expect(alert).toHaveTextContent("enabled: Input should be a valid boolean");
    expect(enable("News")).not.toBeChecked(); // still the real (off) state
    expect(enable("News")).toBeEnabled();
    expect(within(rowOf("Fundamentals")).queryByRole("alert")).toBeNull();
    // the next action clears it
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockedPut.mockResolvedValue(payload());
    await act(async () => fireEvent.click(enable("Fundamentals")));
    expect(screen.queryByText(/enabled: Input should be/)).toBeNull();
  });
});

describe("FMP settings controls: per-group tier select", () => {
  it("calls the same endpoint and payload as before", async () => {
    await renderSection();
    await act(async () => fireEvent.change(tier("Fundamentals"), { target: { value: "Ultimate" } }));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/data-groups/fundamentals", { required_tier: "Ultimate" });
  });

  it("offers the tiers from the data and shows each group's tier", async () => {
    await renderSection();
    expect(Array.from(tier("News").options).map((o) => o.value)).toEqual(["Starter", "Premium", "Ultimate"]);
    expect(tier("Fundamentals").value).toBe("Starter");
  });

  it("a failed request shows the message in that row and leaves the select on the real tier", async () => {
    mockedPut.mockRejectedValue(new Error("PUT /config/data-groups/fundamentals failed: 422 - required_tier: bad"));
    await renderSection();
    await act(async () => fireEvent.change(tier("Fundamentals"), { target: { value: "Ultimate" } }));
    expect(within(rowOf("Fundamentals")).getByRole("alert")).toHaveTextContent("required_tier: bad");
    expect(tier("Fundamentals").value).toBe("Starter");
  });
});
