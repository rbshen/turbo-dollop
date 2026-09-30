// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mutate } from "swr";

import { MoatSettingsForm } from "@/components/settings/MoatSettingsForm";
import { apiPut } from "@/lib/api/client";
import type { MoatScoreConfigOut } from "@/lib/api/types";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";

vi.mock("swr", async (importOriginal) => ({ ...(await importOriginal<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: vi.fn(),
}));
vi.mock("@/lib/hooks/useMoatConfig", () => ({ useMoatConfig: vi.fn() }));

const mockedPut = vi.mocked(apiPut);
const mockedMutate = vi.mocked(mutate);
const mockedHook = vi.mocked(useMoatConfig);

const STORED: MoatScoreConfigOut = {
  wide_moat_score: 100,
  narrow_moat_score: 65,
  no_moat_score: 0,
  updated_at: "2026-09-26T09:14:00",
};

function serve(data: MoatScoreConfigOut | undefined, extra: Record<string, unknown> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false, ...extra } as any);
}

const wide = () => screen.getByLabelText("Wide moat") as HTMLInputElement;
const narrow = () => screen.getByLabelText("Narrow moat") as HTMLInputElement;
const noMoat = () => screen.getByLabelText("No moat") as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save" });
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });

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

describe("MoatSettingsForm: layout", () => {
  it("renders with the Settings kit: sentence-case title, plain intro, three short rows, footer", () => {
    render(<MoatSettingsForm />);
    expect(screen.getByRole("heading", { name: "Economic moat point values" })).toBeInTheDocument();
    expect(screen.getByText(/Sets the points each moat rating counts for/)).toHaveClass("max-w-xl");
    for (const label of ["Wide moat", "Narrow moat", "No moat"]) {
      const row = screen.getByText(label, { selector: "label" }).closest("div.grid");
      expect(row).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
    }
    expect(screen.getByText(/^Last updated /)).toBeInTheDocument();
  });

  it("shows the stored values in short typed fields with no unit and no tooltip", () => {
    render(<MoatSettingsForm />);
    expect([wide().value, narrow().value, noMoat().value]).toEqual(["100", "65", "0"]);
    for (const el of [wide(), narrow(), noMoat()]) {
      expect(el).toHaveAttribute("type", "text");
      expect(el).toHaveClass("w-24");
    }
    expect(screen.queryByText("%")).toBeNull();
    expect(screen.queryByRole("button", { name: /About/ })).toBeNull();
  });

  it("gives each field a hint that states only what the specs support, with no formula or file names", () => {
    render(<MoatSettingsForm />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("counts for in the Overall Assessment");
    expect(text).toContain("makes up 31%");
    expect(text).not.toMatch(/0\.69|0\.31|×|CLAUDE\.md|\.md|§/);
    expect(text).not.toMatch(/\badds\b/);
    expect(wide().getAttribute("aria-describedby")).toContain("wide-moat-score-hint");
    expect(noMoat().getAttribute("aria-describedby")).toContain("no-moat-score-hint");
  });
});

describe("MoatSettingsForm: Save until edited", () => {
  it("is disabled until any field differs from the stored value, and again when reverted", () => {
    render(<MoatSettingsForm />);
    expect(save()).toBeDisabled();
    type(narrow(), "70");
    expect(save()).toBeEnabled();
    type(narrow(), "65.0");
    expect(save()).toBeDisabled();
  });

  it("does nothing when an untouched form is submitted", () => {
    render(<MoatSettingsForm />);
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });
});

describe("MoatSettingsForm: validation", () => {
  it.each(["abc", "", "1e2"])("flags %j inline on that field only, blocks Save and says why", (text) => {
    render(<MoatSettingsForm />);
    type(narrow(), text);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(narrow()).toHaveAttribute("aria-invalid", "true");
    expect(wide()).not.toHaveAttribute("aria-invalid");
    expect(save()).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    expect(screen.queryByText("Save failed")).toBeNull();
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("stays blocked while ANY field is invalid, even if another was validly edited", () => {
    render(<MoatSettingsForm />);
    type(wide(), "90");
    type(noMoat(), "x");
    expect(save()).toBeDisabled();
    type(noMoat(), "5");
    expect(save()).toBeEnabled();
  });

  it.each(["0", "100", "65", "0.5", "99.99"])("accepts %j (0 to 100, inclusive)", (text) => {
    render(<MoatSettingsForm />);
    type(narrow(), text);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(narrow()).not.toHaveAttribute("aria-invalid");
  });

  it.each(["-1", "101", "100.01", "-0.5"])("rejects %j with the range message, on that field only, and blocks Save", (text) => {
    render(<MoatSettingsForm />);
    type(narrow(), text);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value between 0 and 100.");
    expect(narrow()).toHaveAttribute("aria-invalid", "true");
    expect(narrow().value).toBe(text); // never clamped or corrected
    expect(save()).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it.each([
    ["wide", wide],
    ["no moat", noMoat],
  ])("checks the %s field the same way", (_name, pick) => {
    render(<MoatSettingsForm />);
    type(pick(), "101");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value between 0 and 100.");
    type(pick(), "50");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("still says 'Enter a number.' for text and empty, not the range message", () => {
    render(<MoatSettingsForm />);
    type(wide(), "");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    type(wide(), "abc");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
  });

  it("stays in range at both edges through the arrow keys (stepping stops at 0 and 100)", () => {
    render(<MoatSettingsForm />);
    fireEvent.keyDown(wide(), { key: "ArrowUp" });
    expect(wide().value).toBe("100");
    fireEvent.keyDown(noMoat(), { key: "ArrowDown" });
    expect(noMoat().value).toBe("0");
  });
});

describe("MoatSettingsForm: saving", () => {
  it("sends the boundary values 0 and 100 unchanged", async () => {
    render(<MoatSettingsForm />);
    type(wide(), "100");
    type(narrow(), "0");
    type(noMoat(), "100");
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledWith("/config/moat", {
      wide_moat_score: 100,
      narrow_moat_score: 0,
      no_moat_score: 100,
    });
  });

  it("sends the same endpoint and payload shape as before, all three values", async () => {
    render(<MoatSettingsForm />);
    type(narrow(), "70.5");
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/moat", {
      wide_moat_score: 100,
      narrow_moat_score: 70.5,
      no_moat_score: 0,
    });
  });

  it("revalidates the shared /config/moat key and nothing else", async () => {
    render(<MoatSettingsForm />);
    type(wide(), "95");
    await act(async () => fireEvent.click(save()));
    expect(mockedMutate.mock.calls).toEqual([["/config/moat"]]);
  });

  it("reports a failed save and keeps the typed values; the message stays until the next edit", async () => {
    vi.useFakeTimers();
    mockedPut.mockRejectedValue(new Error("500"));
    render(<MoatSettingsForm />);
    type(wide(), "95");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed")).toBeInTheDocument();
    expect(wide().value).toBe("95");
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByText("Save failed")).toBeInTheDocument();
    type(narrow(), "66");
    expect(screen.queryByText(/Save failed/)).toBeNull();
  });

  it("shows the server's reason and clears it when Save is attempted again", async () => {
    mockedPut.mockRejectedValueOnce(new Error("PUT /config/moat failed: 422 - wide_moat_score: bad"));
    render(<MoatSettingsForm />);
    type(wide(), "95");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed: wide_moat_score: bad")).toBeInTheDocument();
    await act(async () => fireEvent.click(save()));
    expect(screen.queryByText(/wide_moat_score: bad/)).toBeNull();
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
  });

  it("still shows 'Saved ✓' after the form remounts on the fresh updated_at, then resets after 3 seconds", async () => {
    vi.useFakeTimers();
    const { rerender } = render(<MoatSettingsForm />);
    mockedMutate.mockImplementationOnce(async () => {
      serve({ ...STORED, wide_moat_score: 95, updated_at: "2026-09-30T10:00:00" });
      act(() => rerender(<MoatSettingsForm />));
      return undefined;
    });
    type(wide(), "95");
    await act(async () => fireEvent.click(save()));
    expect(wide().value).toBe("95");
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("Saved ✓")).toBeNull();
  });
});
