// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mutate } from "swr";

import { LiquidityZoneSettingsForm } from "@/components/settings/LiquidityZoneSettingsForm";
import * as client from "@/lib/api/client";
import type { LiquidityZoneConfigOut } from "@/lib/api/types";
import { useLiquidityZoneConfig } from "@/lib/hooks/useLiquidityZoneConfig";

vi.mock("swr", async (importOriginal) => ({ ...(await importOriginal<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: vi.fn(),
}));
vi.mock("@/lib/hooks/useLiquidityZoneConfig", () => ({ useLiquidityZoneConfig: vi.fn() }));

const mockedPut = vi.mocked(client.apiPut);
const mockedMutate = vi.mocked(mutate);
const mockedHook = vi.mocked(useLiquidityZoneConfig);

// Only-recent OFF, and a stored recency (7) that differs from the seeded 5, so
// "the stored value is sent unchanged" is distinguishable from a default.
const STORED: LiquidityZoneConfigOut = {
  key: "default",
  swing_bars_each_side: 2,
  cluster_pct: 0,
  max_lps_per_side: 3,
  over_cap_priority: "nearest_price",
  keep_last_breached_support: true,
  keep_last_breached_resistance: true,
  only_keep_if_breached_recently: false,
  breach_recency_bars: 7,
  updated_at: "2026-09-26T09:14:00",
};

function serve(data: LiquidityZoneConfigOut | undefined, extra: Record<string, unknown> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false, ...extra } as any);
}

const NUMBER_LABELS = ["Swing bars each side", "Cluster", "Max zones per side", "Breach recency"] as const;
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const check = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save" });
const type = (label: string, value: string) => fireEvent.change(field(label), { target: { value } });
const tickOnlyRecent = () => fireEvent.click(check("Only keep if breached recently"));

beforeEach(() => {
  serve(STORED);
  mockedPut.mockResolvedValue(STORED);
  mockedMutate.mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("LiquidityZoneSettingsForm: layout", () => {
  it("renders the sentence-case title, the intro as given, and the three sub-headings", () => {
    render(<LiquidityZoneSettingsForm />);
    expect(screen.getByRole("heading", { name: "Liquidity zones" })).toBeInTheDocument();
    expect(screen.getByText(/^Support and resistance levels found from swings in price/)).toHaveClass("max-w-xl");
    for (const name of ["Detection", "Display", "Last breached liquidity"]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
    expect(screen.getByText(/^Last updated /)).toBeInTheDocument();
  });

  it("renders all 8 controls as rows in the fixed control column", () => {
    render(<LiquidityZoneSettingsForm />);
    const labels = [
      "Swing bars each side",
      "Cluster",
      "Max zones per side",
      "When over the cap, keep",
      "Keep last breached support",
      "Keep last breached resistance",
      "Only keep if breached recently",
      "Breach recency",
    ];
    const rows = screen.getAllByText((_t, el) => el?.tagName === "LABEL" && labels.includes(el.textContent ?? ""));
    expect(rows.map((r) => r.textContent)).toEqual(labels);
    for (const row of rows) expect(row.closest("div.grid")).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
  });

  it("shows the stored values, with units as suffixes and typed short fields; no stepper, no tooltip", () => {
    render(<LiquidityZoneSettingsForm />);
    expect(NUMBER_LABELS.map((l) => field(l).value)).toEqual(["2", "0", "3", "7"]);
    for (const l of NUMBER_LABELS) {
      expect(field(l)).toHaveAttribute("type", "text");
      expect(field(l)).toHaveClass("w-24");
    }
    expect(screen.getByText("%")).toBeInTheDocument();
    expect(screen.getByText("bars")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Increase|Decrease|About/ })).toBeNull();
  });

  it("uses a native medium select with the existing option values", () => {
    render(<LiquidityZoneSettingsForm />);
    const select = screen.getByLabelText("When over the cap, keep") as unknown as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.parentElement).toHaveClass("w-44");
    expect(Array.from(select.options).map((o) => [o.value, o.textContent])).toEqual([
      ["nearest_price", "Nearest to price"],
      ["most_recent", "Most recent"],
    ]);
    expect(select.value).toBe("nearest_price");
  });

  it("links every hint to its control with aria-describedby", () => {
    render(<LiquidityZoneSettingsForm />);
    expect(field("Cluster").getAttribute("aria-describedby")).toContain("lz-cluster-pct-hint");
    expect(check("Keep last breached support").getAttribute("aria-describedby")).toContain("lz-keep-support-hint");
    expect(field("Breach recency").getAttribute("aria-describedby")).toContain("lz-recency-hint");
  });

  it("shows the loading and error states unchanged", () => {
    serve(undefined, { isLoading: true });
    const { unmount } = render(<LiquidityZoneSettingsForm />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    unmount();
    serve(undefined, { error: new Error("boom") });
    render(<LiquidityZoneSettingsForm />);
    expect(screen.getByText(/Couldn.t load Liquidity Zone settings — boom/)).toBeInTheDocument();
  });
});

describe("LiquidityZoneSettingsForm: checkboxes", () => {
  it.each([
    "Keep last breached support",
    "Keep last breached resistance",
    "Only keep if breached recently",
  ])("%s has the row label as its one and only accessible label, and no second label inside", (name) => {
    render(<LiquidityZoneSettingsForm />);
    const box = check(name);
    expect(screen.getByRole("checkbox", { name })).toBe(box); // accessible name is exactly the row label
    expect(box.labels?.length).toBe(1);
    expect(box.labels?.[0]).toHaveTextContent(name);
    expect(box.closest("label")).toBeNull();
    expect(box.parentElement?.textContent).toBe(""); // no visible text inside the control
  });

  it("uses the neutral checked style and sits in the control column with the number boxes", () => {
    render(<LiquidityZoneSettingsForm />);
    const box = check("Keep last breached support");
    expect((box.nextElementSibling as HTMLElement).className).toContain("peer-checked:bg-text-primary");
    const cell = (label: string) => screen.getByText(label, { selector: "label" }).closest("div.grid")?.children[1] as HTMLElement;
    expect(cell("Keep last breached support").className).toBe(cell("Swing bars each side").className);
  });

  it("reflects the stored ticks and toggles them", () => {
    render(<LiquidityZoneSettingsForm />);
    expect(check("Keep last breached support").checked).toBe(true);
    expect(check("Only keep if breached recently").checked).toBe(false);
    fireEvent.click(check("Keep last breached support"));
    expect(check("Keep last breached support").checked).toBe(false);
  });
});

describe("LiquidityZoneSettingsForm: Save until edited", () => {
  it("is disabled until something differs from the stored values, and again when reverted", () => {
    render(<LiquidityZoneSettingsForm />);
    expect(save()).toBeDisabled();
    type("Max zones per side", "4");
    expect(save()).toBeEnabled();
    type("Max zones per side", "3.0");
    expect(save()).toBeDisabled();
  });

  it("counts the select and each checkbox as an edit", () => {
    render(<LiquidityZoneSettingsForm />);
    fireEvent.change(field("When over the cap, keep"), { target: { value: "most_recent" } });
    expect(save()).toBeEnabled();
    fireEvent.change(field("When over the cap, keep"), { target: { value: "nearest_price" } });
    expect(save()).toBeDisabled();
    for (const name of ["Keep last breached support", "Keep last breached resistance", "Only keep if breached recently"]) {
      fireEvent.click(check(name));
      expect(save()).toBeEnabled();
      fireEvent.click(check(name));
      expect(save()).toBeDisabled();
    }
  });

  it("does nothing when an untouched form is submitted", () => {
    render(<LiquidityZoneSettingsForm />);
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });
});

// [label, whole number?, lowest valid, below it, highest valid, above it, message]
const BOUNDS: [string, boolean, string, string, string, string, string][] = [
  ["Swing bars each side", true, "1", "0", "3", "4", "Enter a value between 1 and 3."],
  ["Cluster", false, "0", "-0.1", "3", "3.1", "Enter a value between 0 and 3."],
  ["Max zones per side", true, "1", "0", "10", "11", "Enter a value between 1 and 10."],
];

describe("LiquidityZoneSettingsForm: bounds and integer rules", () => {
  it.each(BOUNDS)("%s: accepts both ends, rejects just outside them, never changes the text", (label, _w, lo, belowLo, hi, aboveHi, message) => {
    render(<LiquidityZoneSettingsForm />);
    for (const ok of [lo, hi]) {
      type(label, ok);
      expect(screen.queryByRole("alert")).toBeNull();
    }
    for (const bad of [belowLo, aboveHi]) {
      type(label, bad);
      expect(screen.getByRole("alert")).toHaveTextContent(message);
      expect(field(label)).toHaveAttribute("aria-invalid", "true");
      expect(field(label).value).toBe(bad);
      expect(save()).toBeDisabled();
    }
  });

  it.each(BOUNDS.filter((b) => b[1]))("%s: a non-integer is an inline error, never snapped or truncated", (label) => {
    render(<LiquidityZoneSettingsForm />);
    type(label, "2.5");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a whole number.");
    fireEvent.blur(field(label));
    expect(field(label).value).toBe("2.5");
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("cluster takes decimals", () => {
    render(<LiquidityZoneSettingsForm />);
    type("Cluster", "1.5");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each(["abc", "", "1e2"])("an unparsable entry (%j) shows an error and does NOT silently revert on blur", (text) => {
    render(<LiquidityZoneSettingsForm />);
    type("Swing bars each side", text);
    fireEvent.blur(field("Swing bars each side"));
    expect(field("Swing bars each side").value).toBe(text);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(save()).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    expect(screen.queryByText(/Save failed/)).toBeNull();
  });

  it("stays blocked while ANY field is invalid, even if another was validly edited", () => {
    render(<LiquidityZoneSettingsForm />);
    type("Max zones per side", "5");
    type("Cluster", "9");
    expect(save()).toBeDisabled();
    type("Cluster", "2");
    expect(save()).toBeEnabled();
  });

  it("keeps arrow-key stepping inside the server bounds", () => {
    render(<LiquidityZoneSettingsForm />);
    type("Swing bars each side", "3");
    fireEvent.keyDown(field("Swing bars each side"), { key: "ArrowUp" });
    expect(field("Swing bars each side").value).toBe("3");
  });
});

describe("LiquidityZoneSettingsForm: Breach recency depends on 'only keep if breached recently'", () => {
  it("is disabled and dimmed while the option is unticked, and enabled once it is ticked", () => {
    render(<LiquidityZoneSettingsForm />);
    const recency = field("Breach recency");
    expect(recency).toBeDisabled();
    const labelBlock = screen.getByText("Breach recency", { selector: "label" }).parentElement;
    expect(labelBlock).toHaveClass("opacity-45");
    expect(recency).toHaveClass("disabled:opacity-45");
    tickOnlyRecent();
    expect(recency).toBeEnabled();
    expect(labelBlock).not.toHaveClass("opacity-45");
    tickOnlyRecent();
    expect(recency).toBeDisabled();
  });

  it("keeps the row in place, with the same alignment, while disabled", () => {
    render(<LiquidityZoneSettingsForm />);
    const cell = (label: string) => screen.getByText(label, { selector: "label" }).closest("div.grid")?.children[1] as HTMLElement;
    expect(cell("Breach recency").className).toBe(cell("Swing bars each side").className);
    expect(screen.getByText("Breach recency", { selector: "label" }).closest("div.grid")).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
  });

  it("is neither validated nor blocking Save while disabled, even holding an invalid value", () => {
    serve({ ...STORED, only_keep_if_breached_recently: true });
    render(<LiquidityZoneSettingsForm />);
    type("Breach recency", "99");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value between 1 and 52.");
    expect(save()).toBeDisabled();
    tickOnlyRecent(); // untick -> the row no longer applies
    expect(screen.queryByRole("alert")).toBeNull();
    expect(field("Breach recency")).not.toHaveAttribute("aria-invalid");
    expect(save()).toBeEnabled(); // the untick is itself an edit, and the invalid recency does not block it
    expect(screen.queryByText("Fix the highlighted fields to save.")).toBeNull();
  });

  it("is validated once the option is ticked, both bounds", () => {
    render(<LiquidityZoneSettingsForm />);
    tickOnlyRecent();
    for (const ok of ["1", "52"]) {
      type("Breach recency", ok);
      expect(screen.queryByRole("alert")).toBeNull();
    }
    for (const bad of ["0", "53", "2.5", "x"]) {
      type("Breach recency", bad);
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(save()).toBeDisabled();
    }
  });

  it("a recency edit does not count once the option is back off: Save is disabled again", () => {
    render(<LiquidityZoneSettingsForm />); // stored: option off
    tickOnlyRecent();
    type("Breach recency", "9");
    expect(save()).toBeEnabled();
    tickOnlyRecent(); // back to the stored state; the disabled field's edit is ignored
    expect(save()).toBeDisabled();
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("sends the STORED recency unchanged when the option is off, whatever the disabled field holds", async () => {
    serve({ ...STORED, only_keep_if_breached_recently: true });
    render(<LiquidityZoneSettingsForm />);
    type("Breach recency", "9"); // edited while it applied...
    tickOnlyRecent(); // ...then the option is turned off
    await act(async () => fireEvent.click(save()));
    const body = mockedPut.mock.calls[0][1] as Record<string, unknown>;
    expect(body.breach_recency_bars).toBe(7);
    expect(body.only_keep_if_breached_recently).toBe(false);
  });

  it("sends the edited recency when the option is on", async () => {
    render(<LiquidityZoneSettingsForm />);
    tickOnlyRecent();
    type("Breach recency", "9");
    await act(async () => fireEvent.click(save()));
    const body = mockedPut.mock.calls[0][1] as Record<string, unknown>;
    expect(body.breach_recency_bars).toBe(9);
    expect(body.only_keep_if_breached_recently).toBe(true);
  });
});

describe("LiquidityZoneSettingsForm: saving", () => {
  it("sends the same endpoint, all 8 fields, with the types the API expects today", async () => {
    render(<LiquidityZoneSettingsForm />);
    type("Swing bars each side", "3");
    type("Cluster", "1.5");
    type("Max zones per side", "5");
    fireEvent.change(field("When over the cap, keep"), { target: { value: "most_recent" } });
    fireEvent.click(check("Keep last breached support"));
    fireEvent.click(check("Keep last breached resistance"));
    tickOnlyRecent();
    type("Breach recency", "12");
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    const [path, body] = mockedPut.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/config/liquidity-zones");
    expect(body).toEqual({
      swing_bars_each_side: 3,
      cluster_pct: 1.5,
      max_lps_per_side: 5,
      breach_recency_bars: 12,
      over_cap_priority: "most_recent",
      keep_last_breached_support: false,
      keep_last_breached_resistance: false,
      only_keep_if_breached_recently: true,
    });
    for (const k of ["swing_bars_each_side", "cluster_pct", "max_lps_per_side", "breach_recency_bars"]) {
      expect(typeof body[k]).toBe("number");
    }
    for (const k of ["swing_bars_each_side", "max_lps_per_side", "breach_recency_bars"]) {
      expect(Number.isInteger(body[k])).toBe(true);
    }
    for (const k of ["keep_last_breached_support", "keep_last_breached_resistance", "only_keep_if_breached_recently"]) {
      expect(typeof body[k]).toBe("boolean");
    }
    expect(["nearest_price", "most_recent"]).toContain(body.over_cap_priority);
  });

  it("sends untouched fields at their stored values", async () => {
    render(<LiquidityZoneSettingsForm />);
    type("Cluster", "2");
    await act(async () => fireEvent.click(save()));
    expect(mockedPut.mock.calls[0][1]).toEqual({
      swing_bars_each_side: 2,
      cluster_pct: 2,
      max_lps_per_side: 3,
      breach_recency_bars: 7,
      over_cap_priority: "nearest_price",
      keep_last_breached_support: true,
      keep_last_breached_resistance: true,
      only_keep_if_breached_recently: false,
    });
  });

  it("revalidates its own key and nothing else", async () => {
    render(<LiquidityZoneSettingsForm />);
    type("Cluster", "2");
    await act(async () => fireEvent.click(save()));
    expect(mockedMutate.mock.calls).toEqual([["/config/liquidity-zones"]]);
  });

  it("shows Saving… while in flight and disables Save", async () => {
    let release: () => void = () => {};
    mockedPut.mockReturnValue(new Promise((resolve) => { release = () => resolve(STORED); }));
    render(<LiquidityZoneSettingsForm />);
    type("Cluster", "2");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Saving…")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    await act(async () => release());
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
  });

  it("still shows 'Saved ✓' after the form remounts on the fresh updated_at, then resets after 3 seconds", async () => {
    vi.useFakeTimers();
    const { rerender } = render(<LiquidityZoneSettingsForm />);
    mockedMutate.mockImplementationOnce(async () => {
      serve({ ...STORED, cluster_pct: 2, updated_at: "2026-09-30T10:00:00" });
      act(() => rerender(<LiquidityZoneSettingsForm />));
      return undefined;
    });
    type("Cluster", "2");
    await act(async () => fireEvent.click(save()));
    expect(field("Cluster").value).toBe("2");
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("Saved ✓")).toBeNull();
  });

  it("shows the server's reason for a rejected save, keeps the typed values, and keeps it until the next edit", async () => {
    vi.useFakeTimers();
    mockedPut.mockRejectedValue(
      new Error("PUT /config/liquidity-zones failed: 422 - swing_bars_each_side: Input should be less than or equal to 3"),
    );
    render(<LiquidityZoneSettingsForm />);
    type("Cluster", "2");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed: swing_bars_each_side: Input should be less than or equal to 3")).toBeInTheDocument();
    expect(field("Cluster").value).toBe("2");
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByText(/^Save failed: swing_bars_each_side/)).toBeInTheDocument(); // no timeout on a failure
    fireEvent.click(check("Keep last breached support")); // any edit, any control
    expect(screen.queryByText(/Save failed/)).toBeNull();
  });
});
