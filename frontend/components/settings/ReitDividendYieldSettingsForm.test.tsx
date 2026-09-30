// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mutate } from "swr";

import { ReitDividendYieldSettingsForm } from "@/components/settings/ReitDividendYieldSettingsForm";
import { apiPut } from "@/lib/api/client";
import type { ReitDividendYieldConfigOut } from "@/lib/api/types";
import { useReitDividendYieldConfig } from "@/lib/hooks/useReitDividendYieldConfig";

vi.mock("swr", async (importOriginal) => ({ ...(await importOriginal<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiPut: vi.fn() }));
vi.mock("@/lib/hooks/useReitDividendYieldConfig", () => ({ useReitDividendYieldConfig: vi.fn() }));

const mockedPut = vi.mocked(apiPut);
const mockedMutate = vi.mocked(mutate);
const mockedHook = vi.mocked(useReitDividendYieldConfig);

const STORED: ReitDividendYieldConfigOut = { threshold_pct: 5, updated_at: "2026-09-26T09:14:00" };

function serve(data: ReitDividendYieldConfigOut | undefined, extra: Record<string, unknown> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false, ...extra } as any);
}

const field = () => screen.getByLabelText("Threshold") as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save" });
const type = (value: string) => fireEvent.change(field(), { target: { value } });

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

describe("ReitDividendYieldSettingsForm: layout", () => {
  it("renders with the Settings kit: sentence-case title, plain intro, one row, footer", () => {
    render(<ReitDividendYieldSettingsForm />);
    expect(screen.getByRole("heading", { name: "REIT dividend yield threshold" })).toBeInTheDocument();
    expect(screen.getByText(/flagged as a possible bargain on its Valuation tab/)).toHaveClass("max-w-xl");
    expect(document.body.textContent).not.toMatch(/CLAUDE\.md|valuation\.md|§/);
    const label = screen.getByText("Threshold", { selector: "label" });
    expect(label.closest("div.grid")).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
    expect(screen.getByText(/A REIT or property developer is flagged when/)).toBeInTheDocument();
    expect(screen.getByText(/^Last updated /)).toBeInTheDocument();
  });

  it("shows the value in a short typed field with the unit as a suffix, not in the label", () => {
    render(<ReitDividendYieldSettingsForm />);
    expect(field().value).toBe("5");
    expect(field()).toHaveAttribute("type", "text");
    expect(field()).toHaveClass("w-24");
    expect(screen.getByText("%")).toBeInTheDocument();
    expect(screen.getByText("Threshold", { selector: "label" }).textContent).toBe("Threshold");
    expect(screen.queryByRole("button", { name: /About/ })).toBeNull();
  });

  it("links the hint to the field with aria-describedby", () => {
    render(<ReitDividendYieldSettingsForm />);
    expect(field().getAttribute("aria-describedby")).toContain("reit-dividend-yield-threshold-hint");
  });

  it("shows the loading and error states unchanged", () => {
    serve(undefined, { isLoading: true });
    const { unmount } = render(<ReitDividendYieldSettingsForm />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    unmount();
    serve(undefined, { error: new Error("boom") });
    render(<ReitDividendYieldSettingsForm />);
    expect(screen.getByText(/Couldn.t load REIT dividend yield settings — boom/)).toBeInTheDocument();
  });
});

describe("ReitDividendYieldSettingsForm: Save until edited", () => {
  it("is disabled until the value differs from the stored one, and again when reverted", () => {
    render(<ReitDividendYieldSettingsForm />);
    expect(save()).toBeDisabled();
    type("6");
    expect(save()).toBeEnabled();
    type("5.0");
    expect(save()).toBeDisabled();
  });

  it("does nothing when an untouched form is submitted", () => {
    render(<ReitDividendYieldSettingsForm />);
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });
});

describe("ReitDividendYieldSettingsForm: validation", () => {
  it.each(["abc", "", "1e3", "5,5"])("flags %j inline, blocks Save, and says why", (text) => {
    render(<ReitDividendYieldSettingsForm />);
    type(text);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(save()).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    expect(screen.queryByText("Save failed")).toBeNull();
    fireEvent.click(save());
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("never leaves a sticky 'Save failed' for an invalid entry, and clears once fixed", () => {
    render(<ReitDividendYieldSettingsForm />);
    type("abc");
    expect(screen.queryByText("Save failed")).toBeNull();
    type("6");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(save()).toBeEnabled();
  });

  it("invents no bounds: negative and large numbers are accepted as typed", async () => {
    render(<ReitDividendYieldSettingsForm />);
    type("-3");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(field().value).toBe("-3");
    type("250");
    expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledWith("/config/reit-dividend-yield", { threshold_pct: 250 });
  });

  it("never rewrites what was typed", () => {
    render(<ReitDividendYieldSettingsForm />);
    type("5.55555");
    fireEvent.blur(field());
    expect(field().value).toBe("5.55555");
  });
});

describe("ReitDividendYieldSettingsForm: saving", () => {
  it("sends the same endpoint and payload shape as before", async () => {
    render(<ReitDividendYieldSettingsForm />);
    type("6.5");
    await act(async () => fireEvent.click(save()));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/reit-dividend-yield", { threshold_pct: 6.5 });
  });

  it("revalidates its own key, then invalidates every cached step3 and summary key", async () => {
    render(<ReitDividendYieldSettingsForm />);
    type("6");
    await act(async () => fireEvent.click(save()));
    expect(mockedMutate.mock.calls[0]).toEqual(["/config/reit-dividend-yield"]);
    const predicate = mockedMutate.mock.calls[1][0] as (key: unknown) => boolean;
    expect(typeof predicate).toBe("function");
    expect(predicate("/tickers/AAPL/step3")).toBe(true);
    expect(predicate("/tickers/AAPL/summary")).toBe(true);
    expect(predicate("/config/moat")).toBe(false);
    expect(predicate(["/tickers/AAPL/step3"])).toBe(false);
  });

  it("shows Saving… while in flight and disables Save", async () => {
    let release: () => void = () => {};
    mockedPut.mockReturnValue(new Promise((resolve) => { release = () => resolve(STORED); }));
    render(<ReitDividendYieldSettingsForm />);
    type("6");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Saving…")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    await act(async () => release());
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
  });

  it("reports a failed save, keeps the typed value, and resets the status after 3 seconds", async () => {
    vi.useFakeTimers();
    mockedPut.mockRejectedValue(new Error("500"));
    render(<ReitDividendYieldSettingsForm />);
    type("6");
    await act(async () => fireEvent.click(save()));
    expect(screen.getByText("Save failed")).toBeInTheDocument();
    expect(field().value).toBe("6");
    expect(save()).toBeEnabled();
    act(() => { vi.advanceTimersByTime(2999); });
    expect(screen.getByText("Save failed")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.queryByText("Save failed")).toBeNull();
  });

  it("still shows 'Saved ✓' after the form remounts on the fresh updated_at, then resets after 3 seconds", async () => {
    vi.useFakeTimers();
    const { rerender } = render(<ReitDividendYieldSettingsForm />);
    // The revalidation lands new data (a new updated_at) mid-save, as SWR does.
    mockedMutate.mockImplementationOnce(async () => {
      serve({ threshold_pct: 6, updated_at: "2026-09-30T10:00:00" });
      act(() => rerender(<ReitDividendYieldSettingsForm />));
      return undefined;
    });
    type("6");
    await act(async () => fireEvent.click(save()));
    expect(field().value).toBe("6");
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
    expect(save()).toBeDisabled(); // matches the new stored value again
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("Saved ✓")).toBeNull();
  });
});
