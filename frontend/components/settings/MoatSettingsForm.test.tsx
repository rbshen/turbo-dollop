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
// The recompute status the save starts (see ScoreWeightingForm): mocked so this file stays about the form.
const recompute = vi.hoisted(() => ({
  status: { run: null, running: false } as { run: unknown; running: boolean },
  refresh: vi.fn().mockResolvedValue(undefined),
  revalidate: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@/lib/hooks/useScoreWeights", () => ({
  useRecomputeStatus: () => recompute.status,
  refreshScoreWeights: recompute.refresh,
  revalidateScores: recompute.revalidate,
}));

const mockedPut = vi.mocked(apiPut);
const mockedMutate = vi.mocked(mutate);
const mockedHook = vi.mocked(useMoatConfig);

const STORED: MoatScoreConfigOut = {
  wide_moat_multiplier: 1,
  narrow_moat_multiplier: 0.85,
  no_moat_multiplier: 0.7,
  narrow_moat_multiplier_options: [0.8, 0.82, 0.85, 0.87, 0.9],
  updated_at: "2026-09-26T09:14:00",
};

function serve(data: MoatScoreConfigOut | undefined, extra: Record<string, unknown> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false, ...extra } as any);
}

const wide = () => screen.getByLabelText("Wide moat") as HTMLInputElement;
const narrow = () => screen.getByLabelText("Narrow moat") as HTMLSelectElement;
const noMoat = () => screen.getByLabelText("No moat / not rated") as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save" });
const pick = (value: string) => fireEvent.change(narrow(), { target: { value } });

beforeEach(() => {
  serve(STORED);
  mockedPut.mockResolvedValue(STORED);
  mockedMutate.mockResolvedValue(undefined);
});
afterEach(() => {
  recompute.status = { run: null, running: false };
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("MoatSettingsForm: layout", () => {
  it("renders with the Settings kit: sentence-case title, plain intro, three rows, footer", () => {
    render(<MoatSettingsForm />);
    expect(screen.getByRole("heading", { name: "Economic moat multipliers" })).toBeInTheDocument();
    expect(screen.getByText(/Overall score is its Fundamentals score/)).toHaveClass("max-w-xl");
    for (const label of ["Wide moat", "Narrow moat", "No moat / not rated"]) {
      const row = screen.getByText(label, { selector: "label" }).closest("div.grid");
      expect(row).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
    }
    expect(screen.getByText(/^Last updated /)).toBeInTheDocument();
  });

  it("shows Wide (1.0) and No moat / not rated (0.70) read-only, and Narrow as the saved value in a select", () => {
    render(<MoatSettingsForm />);
    expect(wide().value).toBe("1.0");
    expect(noMoat().value).toBe("0.70");
    for (const el of [wide(), noMoat()]) {
      expect(el).toHaveAttribute("readonly");
      expect(el).toBeDisabled();
    }
    expect(narrow().value).toBe("0.85");
    expect(narrow().tagName).toBe("SELECT");
  });

  it("offers exactly the allowed Narrow values, 0.80 / 0.82 / 0.85 / 0.87 / 0.90", () => {
    render(<MoatSettingsForm />);
    const options = Array.from(narrow().options).map((o) => o.value);
    expect(options).toEqual(["0.80", "0.82", "0.85", "0.87", "0.90"]);
  });

  it("explains the model in plain words, with no points, no 31% and no 'No moat <= 1' rule", () => {
    render(<MoatSettingsForm />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Fundamentals score");
    expect(text).toContain("A ticker with no moat rated is scored as No moat");
    expect(text).toContain("Saving the Narrow multiplier recomputes all scores.");
    expect(text).not.toMatch(/31%|points|capped at 1|Capped at 1|CLAUDE\.md|\.md/);
    expect(narrow().getAttribute("aria-describedby")).toContain("narrow-moat-multiplier-hint");
    expect(wide().getAttribute("aria-describedby")).toContain("wide-moat-multiplier-hint");
    expect(noMoat().getAttribute("aria-describedby")).toContain("no-moat-multiplier-hint");
  });
});

describe("MoatSettingsForm: Save until edited", () => {
  it("is disabled until the Narrow value differs from the stored one, and again when reverted", () => {
    render(<MoatSettingsForm />);
    expect(save()).toBeDisabled();
    pick("0.90");
    expect(save()).toBeEnabled();
    pick("0.85");
    expect(save()).toBeDisabled();
  });

  it("does nothing when an untouched form is submitted", () => {
    render(<MoatSettingsForm />);
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("has nothing to validate: a select cannot hold a value outside its options", () => {
    render(<MoatSettingsForm />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Fix the highlighted fields to save.")).toBeNull();
  });
});

describe("MoatSettingsForm: saving", () => {
  it.each(["0.80", "0.82", "0.87", "0.90"])("sends only the Narrow multiplier, as a number (%s)", async (value) => {
    render(<MoatSettingsForm />);
    pick(value);
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/moat", { narrow_moat_multiplier: Number(value) });
  });

  it("revalidates the shared /config/moat key and nothing else", async () => {
    render(<MoatSettingsForm />);
    pick("0.9");
    await act(async () => fireEvent.click(save()));
    expect(mockedMutate.mock.calls).toEqual([["/config/moat"]]);
  });

  it("reports a failed save and keeps the picked value; the message stays until the next edit", async () => {
    vi.useFakeTimers();
    mockedPut.mockRejectedValue(new Error("500"));
    render(<MoatSettingsForm />);
    pick("0.90");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed")).toBeInTheDocument();
    expect(narrow().value).toBe("0.90");
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByText("Save failed")).toBeInTheDocument();
    pick("0.82");
    expect(screen.queryByText(/Save failed/)).toBeNull();
  });

  it("shows the server's reason and clears it when Save is attempted again", async () => {
    mockedPut.mockRejectedValueOnce(new Error("PUT /config/moat failed: 422 - The Narrow moat multiplier must be one of 0.80"));
    render(<MoatSettingsForm />);
    pick("0.90");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText(/Save failed: The Narrow moat multiplier must be one of/)).toBeInTheDocument();
    await act(async () => fireEvent.click(save()));
    expect(screen.queryByText(/must be one of/)).toBeNull();
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
  });

  it("still shows 'Saved ✓' after the form remounts on the fresh updated_at, then resets after 3 seconds", async () => {
    vi.useFakeTimers();
    const { rerender } = render(<MoatSettingsForm />);
    mockedMutate.mockImplementationOnce(async () => {
      serve({ ...STORED, narrow_moat_multiplier: 0.9, updated_at: "2026-09-30T10:00:00" });
      act(() => rerender(<MoatSettingsForm />));
      return undefined;
    });
    pick("0.90");
    await act(async () => fireEvent.click(save()));
    expect(narrow().value).toBe("0.90");
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("Saved ✓")).toBeNull();
  });
});

describe("MoatSettingsForm: saving recomputes all scores", () => {
  it("reads the recompute status and refreshes the scores right after a save, so the busy state starts at once", async () => {
    render(<MoatSettingsForm />);
    pick("0.87");
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(recompute.refresh).toHaveBeenCalledTimes(1); // the status read that starts the polling (and the Screener's stale note)
    expect(recompute.revalidate).toHaveBeenCalledTimes(1);
  });

  it("cannot be saved while a recompute is running, and shows its progress", () => {
    recompute.status = { run: { state: "running", processed: 120, total: 582, failed: 0 }, running: true };
    render(<MoatSettingsForm />);
    pick("0.87");
    expect(save()).toBeDisabled();
    expect(screen.getByTestId("recompute-status")).toHaveTextContent("Recomputing scores, 120 of 582");
  });

  it("shows a server 409 as the save's failure reason", async () => {
    mockedPut.mockRejectedValueOnce(Object.assign(new Error("409"), { detail: "A score recompute is already running (5 of 582); try again when it finishes." }));
    render(<MoatSettingsForm />);
    pick("0.87");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText(/Save failed/)).toBeInTheDocument();
  });
});
