// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScoreWeightingForm } from "@/components/settings/ScoreWeightingForm";
import { apiPost, apiPut } from "@/lib/api/client";
import type { RecomputeRunOut, ScoreWeightsOut } from "@/lib/api/types";

const h = vi.hoisted(() => ({
  data: undefined as unknown,
  running: false,
  run: null as unknown,
  refresh: vi.fn().mockResolvedValue(undefined),
  revalidate: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: vi.fn(),
  apiPost: vi.fn(),
}));
vi.mock("@/lib/hooks/useScoreWeights", () => ({
  useScoreWeights: () => ({ data: h.data, error: undefined, isLoading: h.data === undefined }),
  useRecomputeStatus: () => ({ run: h.run, running: h.running }),
  refreshScoreWeights: h.refresh,
  revalidateScores: h.revalidate,
}));

const mockedPut = vi.mocked(apiPut);
const mockedPost = vi.mocked(apiPost);

const DEFAULTS = {
  overall: { financials: 30, growth: 20, profitability: 20, debt: 30 },
  step1: { revenue: 35, net_income: 20, cfo: 30, margins: 10, fcf: 5 },
  step2: { magnitude: 70, agreement: 30 },
  step4: { roe: 25, roic: 35, ar: 20, ccc: 20 },
  step5: { current_ratio: 33, debt_to_ebitda: 33, debt_servicing: 34 },
};

const BOUNDS = {
  overall: { financials: { min: 10, max: 50 }, growth: { min: 5, max: 50 }, profitability: { min: 5, max: 50 }, debt: { min: 10, max: 50 } },
  step1: { revenue: { min: 20, max: 50 }, net_income: { min: 10, max: 40 }, cfo: { min: 10, max: 40 }, margins: { min: 0, max: 25 }, fcf: { min: 0, max: 15 } },
  step2: { magnitude: { min: 50, max: 100 }, agreement: { min: 0, max: 50 } },
  step4: { roe: { min: 15, max: 60 }, roic: { min: 15, max: 60 }, ar: { min: 0, max: 30 }, ccc: { min: 0, max: 30 } },
  step5: { current_ratio: { min: 15, max: 60 }, debt_to_ebitda: { min: 15, max: 60 }, debt_servicing: { min: 15, max: 60 } },
};

function payload(overrides: Partial<ScoreWeightsOut> = {}): ScoreWeightsOut {
  return {
    weights: structuredClone(DEFAULTS),
    defaults: structuredClone(DEFAULTS),
    overall_total: 100,
    bounds: structuredClone(BOUNDS),
    sums: { overall: 100, step1: 100, step2: 100, step4: 100, step5: 100 },
    weights_version: 1,
    formula_version: 2,
    updated_at: "2026-10-06T09:00:00",
    recompute: null,
    ...overrides,
  } as ScoreWeightsOut;
}

const run = (over: Partial<RecomputeRunOut>): RecomputeRunOut => ({
  id: 1,
  state: "running",
  trigger: "weights",
  started_at: "2026-10-06T09:00:00",
  finished_at: null,
  processed: 0,
  skipped: 0,
  total: 582,
  failed: 0,
  weights_version: 2,
  error: null,
  ...over,
});

const input = (group: string, field: string) => document.getElementById(`weight-${group}-${field}`) as HTMLInputElement;
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });
const save = () => screen.getByRole("button", { name: "Save" });
const reset = () => screen.getByRole("button", { name: "Reset to defaults" });
const sums = () => screen.getAllByTestId("weight-sum").map((el) => el.textContent);

beforeEach(() => {
  h.data = payload();
  h.running = false;
  h.run = null;
  mockedPut.mockResolvedValue(payload());
  mockedPost.mockResolvedValue(payload());
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScoreWeightingForm: layout", () => {
  it("has the section title, a plain intro, an Overall group and the four step groups in order", () => {
    render(<ScoreWeightingForm />);
    expect(screen.getByRole("heading", { name: "Score weighting" })).toBeInTheDocument();
    expect(screen.getByText(/Sets how much each check counts/)).toHaveClass("max-w-xl");
    const titles = screen.getAllByRole("group").map((g) => g.getAttribute("aria-labelledby")).map((id) => document.getElementById(id!)?.textContent);
    expect(titles).toEqual(["Overall weights", "Financials", "Growth Rate", "Profitability", "Debt"]);
  });

  it("shows the saved values, one row per component, in the Settings kit", () => {
    render(<ScoreWeightingForm />);
    expect([input("overall", "financials").value, input("overall", "growth").value, input("overall", "profitability").value, input("overall", "debt").value]).toEqual(["30", "20", "20", "30"]);
    expect(["revenue", "net_income", "cfo", "margins", "fcf"].map((f) => input("step1", f).value)).toEqual(["35", "20", "30", "10", "5"]);
    expect(["magnitude", "agreement"].map((f) => input("step2", f).value)).toEqual(["70", "30"]);
    expect(["roe", "roic", "ar", "ccc"].map((f) => input("step4", f).value)).toEqual(["25", "35", "20", "20"]);
    expect(["current_ratio", "debt_to_ebitda", "debt_servicing"].map((f) => input("step5", f).value)).toEqual(["33", "33", "34"]);
    const row = input("overall", "debt").closest("div.grid");
    expect(row).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
  });

  it("has no Economic moat row: Moat is a multiplier now, set under Economic moat", () => {
    render(<ScoreWeightingForm />);
    expect(document.getElementById("weight-moat-locked")).toBeNull();
    expect(screen.queryByText(/Fixed at 31%/)).toBeNull();
    expect(screen.queryByText("Economic moat", { selector: "label" })).toBeNull();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/31%|69%/);
    expect(text).toContain("The four automated checks add up to 100% and give the Steps score");
  });

  it("carries the help text and the applies-to-all note", () => {
    render(<ScoreWeightingForm />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("A weight of 0 means the part is not counted in the score, but missing data can still affect the check.");
    expect(text).toContain("Banks, Insurance, Utilities and REITs use fewer parts");
    expect(text).toContain("A hard fail still reads Fail whatever the weights.");
    expect(text).toContain("Applies to all tickers. Saving recomputes all scores (about a minute).");
  });
});

describe("ScoreWeightingForm: validation", () => {
  it("shows a Sum caption per set, 'Sum 100 of 100' for the defaults", () => {
    render(<ScoreWeightingForm />);
    expect(sums()).toEqual(["Sum 100 of 100", "Sum 100 of 100", "Sum 100 of 100", "Sum 100 of 100", "Sum 100 of 100"]);
  });

  it("flags a set that does not add up, 'Sum 102, needs 100', and blocks Save until it does", () => {
    render(<ScoreWeightingForm />);
    type(input("overall", "financials"), "32");
    expect(sums()[0]).toBe("Sum 102, needs 100");
    expect(screen.getAllByTestId("weight-sum")[0]).toHaveClass("text-negative");
    expect(save()).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    type(input("overall", "growth"), "18");
    expect(sums()[0]).toBe("Sum 100 of 100");
    expect(save()).toBeEnabled();
  });

  it("takes each field's bounds from the endpoint, not from constants", () => {
    h.data = payload({ bounds: { ...BOUNDS, overall: { ...BOUNDS.overall, debt: { min: 12, max: 28 } } } });
    render(<ScoreWeightingForm />);
    type(input("overall", "debt"), "11");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value between 12 and 28.");
    expect(input("overall", "debt")).toHaveAttribute("aria-invalid", "true");
    expect(save()).toBeDisabled();
  });

  it.each([
    ["overall", "financials", "9", "Enter a value between 10 and 50."],
    ["overall", "financials", "51", "Enter a value between 10 and 50."],
    ["step1", "revenue", "19", "Enter a value between 20 and 50."],
    ["step1", "margins", "26", "Enter a value between 0 and 25."],
    ["step2", "magnitude", "49", "Enter a value between 50 and 100."],
    ["step4", "roe", "14", "Enter a value between 15 and 60."],
    ["step5", "current_ratio", "61", "Enter a value between 15 and 60."],
  ])("rejects %s/%s = %s with the range message and blocks Save", (group, field, value, message) => {
    render(<ScoreWeightingForm />);
    type(input(group, field), value);
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent(message);
    expect(input(group, field).value).toBe(value); // never clamped or corrected
    expect(save()).toBeDisabled();
  });

  it.each(["17.5", "abc", ""])("rejects %j as not a whole number", (value) => {
    render(<ScoreWeightingForm />);
    type(input("step1", "cfo"), value);
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent(value === "17.5" ? "Enter a whole number." : "Enter a number.");
    expect(save()).toBeDisabled();
  });

  it("accepts the bounds themselves (0 where 0 is allowed)", () => {
    render(<ScoreWeightingForm />);
    type(input("step1", "margins"), "0");
    type(input("step1", "revenue"), "45");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(sums()[1]).toBe("Sum 100 of 100");
    expect(save()).toBeEnabled();
  });
});

describe("ScoreWeightingForm: Save", () => {
  it("is disabled until something differs from the saved weights, and again when reverted", () => {
    render(<ScoreWeightingForm />);
    expect(save()).toBeDisabled();
    type(input("step2", "magnitude"), "60");
    type(input("step2", "agreement"), "40");
    expect(save()).toBeEnabled();
    type(input("step2", "magnitude"), "70");
    type(input("step2", "agreement"), "30");
    expect(save()).toBeDisabled();
  });

  it("asks for confirmation first; Cancel sends nothing", () => {
    render(<ScoreWeightingForm />);
    type(input("step2", "magnitude"), "60");
    type(input("step2", "agreement"), "40");
    fireEvent.click(save());
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Save these weights? This recomputes the scores of all tracked tickers (about a minute)");
    expect(mockedPut).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("Confirm sends the full set to PUT /config/score-weights, then refreshes the status and the scores", async () => {
    render(<ScoreWeightingForm />);
    type(input("overall", "financials"), "32");
    type(input("overall", "growth"), "18");
    type(input("step5", "current_ratio"), "20");
    type(input("step5", "debt_to_ebitda"), "40");
    type(input("step5", "debt_servicing"), "40");
    fireEvent.click(save());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm" })));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut).toHaveBeenCalledWith("/config/score-weights", {
      overall: { financials: 32, growth: 18, profitability: 20, debt: 30 },
      step1: DEFAULTS.step1,
      step2: DEFAULTS.step2,
      step4: DEFAULTS.step4,
      step5: { current_ratio: 20, debt_to_ebitda: 40, debt_servicing: 40 },
    });
    expect(h.refresh).toHaveBeenCalledTimes(1);
    expect(h.revalidate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("never sends a Moat field", async () => {
    render(<ScoreWeightingForm />);
    type(input("step2", "magnitude"), "60");
    type(input("step2", "agreement"), "40");
    fireEvent.click(save());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm" })));
    expect(JSON.stringify(mockedPut.mock.calls[0][1])).not.toMatch(/moat/i);
  });

  it("shows the server's reason when the save fails (a 409 while a run is going, a 422)", async () => {
    mockedPut.mockRejectedValueOnce(new Error("A score recompute is already running (5 of 582); try again when it finishes."));
    render(<ScoreWeightingForm />);
    type(input("step2", "magnitude"), "60");
    type(input("step2", "agreement"), "40");
    fireEvent.click(save());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm" })));
    expect(screen.getByText(/Save failed/)).toBeInTheDocument();
    expect(h.refresh).not.toHaveBeenCalled();
  });
});

describe("ScoreWeightingForm: Reset to defaults", () => {
  it("is disabled while the saved weights already are the defaults", () => {
    render(<ScoreWeightingForm />);
    expect(reset()).toBeDisabled();
  });

  it("asks for confirmation, then posts the reset and refreshes", async () => {
    h.data = payload({ weights: { ...DEFAULTS, overall: { financials: 17, growth: 17, profitability: 17, debt: 18 } } });
    render(<ScoreWeightingForm />);
    expect(reset()).toBeEnabled();
    fireEvent.click(reset());
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Reset every weight to its default?");
    expect(mockedPost).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm" })));
    expect(mockedPost).toHaveBeenCalledWith("/config/score-weights/reset");
    expect(h.refresh).toHaveBeenCalledTimes(1);
    expect(h.revalidate).toHaveBeenCalledTimes(1);
  });

  it("Cancel on the reset confirmation changes nothing", () => {
    h.data = payload({ weights: { ...DEFAULTS, step2: { magnitude: 60, agreement: 40 } } });
    render(<ScoreWeightingForm />);
    fireEvent.click(reset());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockedPost).not.toHaveBeenCalled();
    expect(input("step2", "magnitude").value).toBe("60");
  });
});

describe("ScoreWeightingForm: a recompute in progress", () => {
  it("shows 'Recomputing scores, N of M' and locks every control", () => {
    h.running = true;
    h.run = run({ processed: 214 });
    h.data = payload({ recompute: h.run as RecomputeRunOut });
    render(<ScoreWeightingForm />);
    expect(screen.getByTestId("recompute-status")).toHaveTextContent("Recomputing scores, 214 of 582");
    expect(input("overall", "financials")).toBeDisabled();
    expect(input("step5", "debt_servicing")).toBeDisabled();
    expect(save()).toBeDisabled();
    expect(reset()).toBeDisabled();
  });

  it("is quiet when the last run succeeded", () => {
    h.run = run({ state: "done", processed: 582, finished_at: "2026-10-06T09:01:00" });
    render(<ScoreWeightingForm />);
    expect(screen.queryByTestId("recompute-status")).toBeNull();
  });

  it("shows a failed run's reason, says the settings are saved, and keeps showing the saved weights", () => {
    h.run = run({ state: "failed", error: "The recompute worker stopped responding." });
    h.data = payload({ weights: { ...DEFAULTS, step2: { magnitude: 60, agreement: 40 } } });
    render(<ScoreWeightingForm />);
    const status = screen.getByTestId("recompute-status");
    expect(status).toHaveTextContent("The last score recompute failed: The recompute worker stopped responding.");
    expect(status).toHaveTextContent("Your settings are saved");
    expect(input("step2", "magnitude").value).toBe("60");
    expect(input("step2", "magnitude")).toBeEnabled();
  });

  it("mentions tickers that could not be scored in a finished run", () => {
    h.run = run({ state: "done", failed: 2 });
    render(<ScoreWeightingForm />);
    expect(screen.getByTestId("recompute-status")).toHaveTextContent("2 tickers could not be scored");
  });
});

describe("ScoreWeightingForm: loading", () => {
  it("shows Loading until the weights arrive", () => {
    h.data = undefined;
    render(<ScoreWeightingForm />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
