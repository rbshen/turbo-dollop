// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mutate } from "swr";

import { WeinsteinSettingsForm } from "@/components/settings/WeinsteinSettingsForm";
import * as client from "@/lib/api/client";
import type { WeinsteinConfigOut } from "@/lib/api/types";
import { useWeinsteinConfig } from "@/lib/hooks/useWeinsteinConfig";

vi.mock("swr", async (importOriginal) => ({ ...(await importOriginal<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: vi.fn(),
}));
vi.mock("@/lib/hooks/useWeinsteinConfig", () => ({ useWeinsteinConfig: vi.fn() }));

const actualClient = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
const mockedPut = vi.mocked(client.apiPut);
const mockedMutate = vi.mocked(mutate);
const mockedHook = vi.mocked(useWeinsteinConfig);

const STORED = {
  key: "default",
  ma_length: 30,
  ma_type: "EMA",
  within_range_pct: 5,
  slope_lookback: 5,
  breakout_volume_mult: 2,
  volume_avg_length: 50,
  rs_benchmark: "SPY",
  rs_smoothing_length: 52,
  updated_at: "2026-09-26T09:14:00",
} as WeinsteinConfigOut;

function serve(data: WeinsteinConfigOut | undefined, extra: Record<string, unknown> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false, ...extra } as any);
}

const LABELS = [
  "MA length",
  "MA type",
  "Within range",
  "Slope lookback",
  "Breakout volume",
  "Volume average length",
  "RS benchmark",
  "RS smoothing length",
] as const;
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save" });
const type = (label: string, value: string) => fireEvent.change(field(label), { target: { value } });

beforeEach(() => {
  serve(STORED);
  mockedPut.mockResolvedValue(STORED);
  mockedMutate.mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("WeinsteinSettingsForm: layout", () => {
  it("renders the sentence-case title, the intro as given, and both sub-headings", () => {
    render(<WeinsteinSettingsForm />);
    expect(screen.getByRole("heading", { name: "Weinstein stage" })).toBeInTheDocument();
    expect(screen.getByText(/^Sets how the weekly stage is worked out: Base, Advance, Top or Decline\./)).toHaveClass("max-w-xl");
    expect(screen.getByRole("heading", { level: 3, name: "Stage" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Breakout and relative strength" })).toBeInTheDocument();
    expect(screen.getByText(/^Last updated /)).toBeInTheDocument();
  });

  it("renders all 8 rows in the fixed control column, in order, with the stored values", () => {
    render(<WeinsteinSettingsForm />);
    const rows = screen.getAllByText((_t, el) => el?.tagName === "LABEL" && LABELS.includes(el.textContent as never));
    expect(rows.map((r) => r.textContent)).toEqual([...LABELS]);
    for (const row of rows) expect(row.closest("div.grid")).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
    expect(LABELS.map((l) => field(l).value)).toEqual(["30", "EMA", "5", "5", "2", "50", "SPY", "52"]);
  });

  it("uses units as suffixes (not in labels), typed short fields, a native short select and a medium text field", () => {
    render(<WeinsteinSettingsForm />);
    expect(screen.getAllByText("weeks")).toHaveLength(4);
    expect(screen.getByText("%")).toBeInTheDocument();
    expect(screen.getByText("× average")).toBeInTheDocument();
    for (const label of LABELS) expect(label).not.toMatch(/\(|weeks|%/);
    for (const l of ["MA length", "Within range", "Slope lookback", "Breakout volume", "Volume average length", "RS smoothing length"]) {
      expect(field(l)).toHaveAttribute("type", "text");
      expect(field(l)).toHaveClass("w-24");
    }
    const select = field("MA type");
    expect(select.tagName).toBe("SELECT");
    expect(select.parentElement).toHaveClass("w-24");
    expect(field("RS benchmark")).toHaveClass("w-44");
    expect(screen.queryByRole("button", { name: /About/ })).toBeNull();
  });

  it("links every hint to its field with aria-describedby", () => {
    render(<WeinsteinSettingsForm />);
    for (const [label, id] of [
      ["MA length", "ws-ma-length"],
      ["MA type", "ws-ma-type"],
      ["Within range", "ws-range-pct"],
      ["Slope lookback", "ws-slope-lookback"],
      ["Breakout volume", "ws-vol-mult"],
      ["Volume average length", "ws-vol-avg"],
      ["RS benchmark", "ws-benchmark"],
      ["RS smoothing length", "ws-rs-smoothing"],
    ]) {
      expect(field(label).getAttribute("aria-describedby")).toContain(`${id}-hint`);
    }
  });

  it("never cites a doc file or section number", () => {
    render(<WeinsteinSettingsForm />);
    expect(document.body.textContent).not.toMatch(/CLAUDE\.md|\.md\b|§/);
  });

  it("shows the loading and error states unchanged", () => {
    serve(undefined, { isLoading: true });
    const { unmount } = render(<WeinsteinSettingsForm />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    unmount();
    serve(undefined, { error: new Error("boom") });
    render(<WeinsteinSettingsForm />);
    expect(screen.getByText(/Couldn.t load Weinstein settings — boom/)).toBeInTheDocument();
  });
});

describe("WeinsteinSettingsForm: Save until edited", () => {
  it("is disabled until a field differs from the stored value, and again when reverted", () => {
    render(<WeinsteinSettingsForm />);
    expect(save()).toBeDisabled();
    type("MA length", "40");
    expect(save()).toBeEnabled();
    type("MA length", "30.0");
    expect(save()).toBeDisabled();
  });

  it("counts the select and the text field as edits too", () => {
    render(<WeinsteinSettingsForm />);
    fireEvent.change(field("MA type"), { target: { value: "SMA" } });
    expect(save()).toBeEnabled();
    fireEvent.change(field("MA type"), { target: { value: "EMA" } });
    expect(save()).toBeDisabled();
    type("RS benchmark", "QQQ");
    expect(save()).toBeEnabled();
    type("RS benchmark", "  SPY  ");
    expect(save()).toBeDisabled();
  });

  it("does nothing when an untouched form is submitted", () => {
    render(<WeinsteinSettingsForm />);
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });
});

// [label, whole number?, lowest valid, below it, highest valid, above it, message]
const BOUNDS: [string, boolean, string, string, string, string, string][] = [
  ["MA length", true, "2", "1", "200", "201", "Enter a value between 2 and 200."],
  ["Within range", false, "0", "-0.5", "50", "50.5", "Enter a value between 0 and 50."],
  ["Slope lookback", true, "1", "0", "52", "53", "Enter a value between 1 and 52."],
  ["Breakout volume", false, "0.1", "0.05", "20", "20.1", "Enter a value between 0.1 and 20."],
  ["Volume average length", true, "2", "1", "200", "201", "Enter a value between 2 and 200."],
  ["RS smoothing length", true, "2", "1", "200", "201", "Enter a value between 2 and 200."],
];

describe("WeinsteinSettingsForm: bounds and integer rules", () => {
  it.each(BOUNDS)("%s: accepts both ends, rejects just outside them", (label, _whole, lo, belowLo, hi, aboveHi, message) => {
    render(<WeinsteinSettingsForm />);
    for (const ok of [lo, hi]) {
      type(label, ok);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(field(label)).not.toHaveAttribute("aria-invalid");
    }
    for (const bad of [belowLo, aboveHi]) {
      type(label, bad);
      expect(screen.getAllByRole("alert")).toHaveLength(1);
      expect(screen.getByRole("alert")).toHaveTextContent(message);
      expect(field(label)).toHaveAttribute("aria-invalid", "true");
      expect(field(label).value).toBe(bad); // never clamped or corrected
      expect(save()).toBeDisabled();
    }
  });

  it.each(BOUNDS.filter((b) => b[1]))("%s: a non-integer shows an inline error and is never truncated", (label) => {
    render(<WeinsteinSettingsForm />);
    type(label, "30.7");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a whole number.");
    expect(field(label).value).toBe("30.7");
    expect(save()).toBeDisabled();
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it.each(BOUNDS.filter((b) => !b[1]))("%s: a decimal is fine", (label) => {
    render(<WeinsteinSettingsForm />);
    type(label, "7.5");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("breakout volume's error names the 0.1 floor, which is stricter than the server's 'above 0'", () => {
    render(<WeinsteinSettingsForm />);
    type("Breakout volume", "0");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value between 0.1 and 20.");
  });

  it.each(["abc", "", "1e2", "3,5"])("flags %j in a number field as not a number", (text) => {
    render(<WeinsteinSettingsForm />);
    type("Slope lookback", text);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(save()).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    expect(screen.queryByText(/Save failed/)).toBeNull();
  });
});

describe("WeinsteinSettingsForm: RS benchmark", () => {
  it("accepts 1 and 20 characters after trimming, and does not enforce case", () => {
    render(<WeinsteinSettingsForm />);
    type("RS benchmark", "q");
    expect(screen.queryByRole("alert")).toBeNull();
    type("RS benchmark", "a".repeat(20));
    expect(screen.queryByRole("alert")).toBeNull();
    type("RS benchmark", `  ${"a".repeat(20)}  `);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each(["", "   "])("flags %j (empty after trimming) inline and blocks Save", (text) => {
    render(<WeinsteinSettingsForm />);
    type("RS benchmark", text);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a ticker symbol.");
    expect(field("RS benchmark")).toHaveAttribute("aria-invalid", "true");
    expect(save()).toBeDisabled();
  });

  it("flags more than 20 characters inline and blocks Save", () => {
    render(<WeinsteinSettingsForm />);
    type("RS benchmark", "a".repeat(21));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter 20 characters or fewer.");
    expect(save()).toBeDisabled();
  });

  it("never rewrites what was typed (no upper-casing)", () => {
    render(<WeinsteinSettingsForm />);
    type("RS benchmark", "qqq");
    fireEvent.blur(field("RS benchmark"));
    expect(field("RS benchmark").value).toBe("qqq");
  });

  it("stays blocked while ANY field is invalid, even if another was validly edited", () => {
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    type("RS benchmark", "");
    expect(save()).toBeDisabled();
    type("RS benchmark", "SPY");
    expect(save()).toBeEnabled();
  });
});

describe("WeinsteinSettingsForm: saving", () => {
  it("sends the same endpoint and payload shape as before, with the right types", async () => {
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    fireEvent.change(field("MA type"), { target: { value: "SMA" } });
    type("Within range", "7.5");
    type("Breakout volume", "2.5");
    type("RS benchmark", "  QQQ ");
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    const [path, body] = mockedPut.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/config/weinstein");
    expect(body).toEqual({
      ma_length: 40,
      ma_type: "SMA",
      within_range_pct: 7.5,
      slope_lookback: 5,
      breakout_volume_mult: 2.5,
      volume_avg_length: 50,
      rs_benchmark: "QQQ",
      rs_smoothing_length: 52,
    });
    expect(Object.keys(body).sort()).toEqual(
      [
        "breakout_volume_mult",
        "ma_length",
        "ma_type",
        "rs_benchmark",
        "rs_smoothing_length",
        "slope_lookback",
        "volume_avg_length",
        "within_range_pct",
      ].sort(),
    );
    for (const k of ["ma_length", "slope_lookback", "volume_avg_length", "rs_smoothing_length"]) {
      expect(Number.isInteger(body[k])).toBe(true);
    }
    for (const k of ["within_range_pct", "breakout_volume_mult"]) expect(typeof body[k]).toBe("number");
    expect(typeof body.ma_type).toBe("string");
    expect(typeof body.rs_benchmark).toBe("string");
  });

  it("revalidates its own key and nothing else", async () => {
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    await act(async () => fireEvent.click(save()));
    expect(mockedMutate.mock.calls).toEqual([["/config/weinstein"]]);
  });

  it("shows Saving… while in flight and disables Save", async () => {
    let release: () => void = () => {};
    mockedPut.mockReturnValue(new Promise((resolve) => { release = () => resolve(STORED); }));
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Saving…")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    await act(async () => release());
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
  });

  it("still shows 'Saved ✓' after the form remounts on the fresh updated_at, then resets after 3 seconds", async () => {
    vi.useFakeTimers();
    const { rerender } = render(<WeinsteinSettingsForm />);
    mockedMutate.mockImplementationOnce(async () => {
      serve({ ...STORED, ma_length: 40, updated_at: "2026-09-30T10:00:00" });
      act(() => rerender(<WeinsteinSettingsForm />));
      return undefined;
    });
    type("MA length", "40");
    await act(async () => fireEvent.click(save()));
    expect(field("MA length").value).toBe("40");
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("Saved ✓")).toBeNull();
  });
});

describe("WeinsteinSettingsForm: a rejected save", () => {
  it("shows the server's message beside 'Save failed', keeps the typed values, and keeps it until the next edit", async () => {
    vi.useFakeTimers();
    mockedPut.mockRejectedValue(
      new Error("PUT /config/weinstein failed: 422 - ma_length: Input should be greater than or equal to 2"),
    );
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed: ma_length: Input should be greater than or equal to 2")).toBeInTheDocument();
    expect(field("MA length").value).toBe("40");
    expect(save()).toBeEnabled();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByText(/^Save failed: ma_length/)).toBeInTheDocument(); // no timeout on a failure
    fireEvent.change(field("MA type"), { target: { value: "SMA" } }); // any edit, any control
    expect(screen.queryByText(/Save failed/)).toBeNull();
  });

  it("falls back to a plain 'Save failed' when the error has no detail", async () => {
    mockedPut.mockRejectedValue(new Error("PUT /config/weinstein failed: 500"));
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed")).toBeInTheDocument();
  });

  it("shows a real FastAPI 422 body (a list of {loc, msg}) end to end through the API client", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [{ type: "less_than_equal", loc: ["body", "slope_lookback"], msg: "Input should be less than or equal to 52", input: 60 }],
        }),
      }),
    );
    mockedPut.mockImplementation(actualClient.apiPut);
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed: slope_lookback: Input should be less than or equal to 52")).toBeInTheDocument();
  });

  it("clears the message on the next successful save", async () => {
    mockedPut.mockRejectedValueOnce(new Error("PUT /config/weinstein failed: 422 - x: bad"));
    render(<WeinsteinSettingsForm />);
    type("MA length", "40");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed: x: bad")).toBeInTheDocument();
    await act(async () => fireEvent.click(save()));
    expect(screen.queryByText(/x: bad/)).toBeNull();
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
  });
});
