// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ManualCalculationPanel } from "@/components/step3/ManualCalculationPanel";
import type { Step3ManualOut, Step3Method, Step3Out, TickerCustomValuationOut } from "@/lib/api/types";

// Characterization tests for the Custom Valuation panel (the Valuation tab's
// "Manual Calculation" column): what each method shows, how every row parses
// and formats its text, what each slider and button does, and the exact
// payloads sent. The panel's own maths runs on the backend, so "the calculation
// is unchanged" is pinned here as the exact request body for each scenario.

const apiPost = vi.fn();
const apiPut = vi.fn();
const apiDelete = vi.fn();
const mutate = vi.fn();
let hook: { data?: TickerCustomValuationOut; error?: Error; isLoading?: boolean };

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiPut: (...args: unknown[]) => apiPut(...args),
  apiDelete: (...args: unknown[]) => apiDelete(...args),
}));
vi.mock("swr", async (importOriginal) => ({
  ...(await importOriginal<typeof import("swr")>()),
  mutate: (...args: unknown[]) => mutate(...args),
}));
vi.mock("@/lib/hooks/useTickerCustomValuation", () => ({
  useTickerCustomValuation: () => hook,
}));

const TICKER = "ACME";
const CALC_PATH = `/tickers/${TICKER}/step3/manual`;

const CALC_OK: Step3ManualOut = {
  intrinsic_value_per_share: 187.5,
  pb_bands: null,
  discount_premium_pct: -0.2,
  verdict: "undervalued",
  error: null,
};

function makeAuto(overrides: { selected_method?: Step3Method; inputs?: Record<string, unknown> } = {}): Step3Out {
  return {
    ticker: TICKER,
    selected_method: overrides.selected_method ?? "DCF",
    inputs: {
      current_value_candidates: {
        cfo_ttm: 48_253_000_000,
        fcf_ttm: 41_000_000_000,
        fcf_normalized: 40_000_000_000,
        net_income_ttm: 35_000_000_000,
        net_income_smoothed: 30_500_000_000,
        cfo_smoothed: 44_000_000_000,
        fcf_smoothed: 39_000_000_000,
      },
      growth_yr_1_5: 0.15,
      growth_yr_6_10: 0.09,
      growth_yr_11_20: 0.04,
      growth_yr_1_5_source: "Analyst consensus",
      discount_rate: 0.085,
      shares_outstanding: 1_000_000_000,
      total_debt: 12_000_000_000,
      cash_and_st_investments: 5_500_000_000,
      cash_and_st_investments_includes_short_term_investments: false,
      book_value_per_share: 25.5,
      pb_mean_ratio: 1.8,
      pb_sd_ratio: 0.4,
      book_value_per_share_standard: 22.1,
      pb_mean_ratio_standard: 1.5,
      pb_sd_ratio_standard: 0.3,
      sales_per_share: 12.5,
      projected_growth_rate: 0.35,
      fair_psg_ratio: 1.2,
      quote_currency: "USD",
      reported_currency: null,
      fx_rate: null,
      fx_rate_as_of: null,
      last_close: 150,
      ...overrides.inputs,
    },
  } as unknown as Step3Out;
}

const NOT_SAVED: TickerCustomValuationOut = {
  ticker: TICKER,
  saved: false,
  method: null,
  is_active: false,
  saved_at: null,
  active_verdict: CALC_OK,
};

function makeSaved(overrides: Partial<TickerCustomValuationOut> = {}): TickerCustomValuationOut {
  return {
    ...NOT_SAVED,
    saved: true,
    method: "DFCF",
    is_active: false,
    saved_at: "2026-09-01T12:00:00",
    current_value: 20_000_000_000,
    growth_yr_1_5: 0.12,
    growth_yr_6_10: 0.07,
    growth_yr_11_20: 0.03,
    discount_rate: 0.1,
    shares_outstanding: 500_000_000,
    total_debt: 1_000_000_000,
    cash_and_st_investments: 2_000_000_000,
    book_value_per_share: null,
    pb_mean_ratio: null,
    pb_sd_ratio: null,
    book_value_per_share_standard: null,
    pb_mean_ratio_standard: null,
    pb_sd_ratio_standard: null,
    sales_per_share: null,
    projected_growth_rate: null,
    fair_psg_ratio: null,
    ...overrides,
  };
}

// Every request carries all 17 fields whatever the method; this is the full
// request for the default auto fixture above under DCF.
const DCF_AUTO_PAYLOAD = {
  method: "DCF",
  current_value: 48_253_000_000,
  growth_yr_1_5: 0.15,
  growth_yr_6_10: 0.09,
  growth_yr_11_20: 0.04,
  discount_rate: 0.085,
  shares_outstanding: 1_000_000_000,
  total_debt: 12_000_000_000,
  cash_and_st_investments: 5_500_000_000,
  book_value_per_share: 25.5,
  pb_mean_ratio: 1.8,
  pb_sd_ratio: 0.4,
  book_value_per_share_standard: 22.1,
  pb_mean_ratio_standard: 1.5,
  pb_sd_ratio_standard: 0.3,
  sales_per_share: 12.5,
  projected_growth_rate: 0.35,
  fair_psg_ratio: 1.2,
  last_close: 150,
};

beforeEach(() => {
  hook = { data: NOT_SAVED };
  apiPost.mockReset().mockImplementation(async (path: string) => (path === CALC_PATH ? CALC_OK : undefined));
  apiPut.mockReset().mockResolvedValue(undefined);
  apiDelete.mockReset().mockResolvedValue(undefined);
  mutate.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

// Selectors live here only, so a markup change touches these helpers and
// nothing else. Labels are matched case-insensitively.
function rowInput(label: RegExp): HTMLInputElement {
  const cell = screen.getAllByText(label).find((el) => el.closest("tr"));
  if (!cell) throw new Error(`no row labelled ${label}`);
  return cell.closest("tr")!.querySelector("input") as HTMLInputElement;
}
const rowLabels = () =>
  Array.from(document.querySelectorAll("tbody tr"))
    .filter((tr) => tr.querySelector("input"))
    .map((tr) => (tr.querySelector("td")!.firstElementChild as HTMLElement).textContent);
const sliders = () => screen.getAllByRole("slider") as HTMLInputElement[];
const methodSelect = () => screen.getByRole("combobox") as HTMLSelectElement;
const btn = (name: RegExp) => screen.getByRole("button", { name });
const calcBodies = () => apiPost.mock.calls.filter((c) => c[0] === CALC_PATH).map((c) => c[1]);
const lastCalc = () => calcBodies().at(-1);

// Serve the backend's real answer for a golden scenario's final payload (each
// value below was produced by scoring.step3.run_manual_calculation on exactly
// the request the test asserts).
function serve(result: Partial<Step3ManualOut>) {
  apiPost.mockImplementation(async (path: string) => (path === CALC_PATH ? { ...CALC_OK, ...result } : undefined));
}

async function mountPanel(auto: Step3Out = makeAuto()) {
  render(<ManualCalculationPanel ticker={TICKER} autoData={auto} />);
  await waitFor(() => expect(calcBodies().length).toBeGreaterThan(0));
}

function type(input: HTMLInputElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
}

describe("ManualCalculationPanel: states", () => {
  it("shows the load error", () => {
    hook = { error: new Error("boom") };
    render(<ManualCalculationPanel ticker={TICKER} autoData={makeAuto()} />);
    expect(screen.getByText(/Couldn't load custom valuation — boom/i)).toBeInTheDocument();
  });

  it("shows Loading… until the saved state arrives", () => {
    hook = { isLoading: true };
    render(<ManualCalculationPanel ticker={TICKER} autoData={makeAuto()} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("calculates once on mount with the auto defaults for the selected method", async () => {
    await mountPanel();
    expect(calcBodies()).toEqual([DCF_AUTO_PAYLOAD]);
    expect(methodSelect().value).toBe("DCF");
  });

  it("falls back to DCF when auto landed on PASS", async () => {
    await mountPanel(makeAuto({ selected_method: "PASS" }));
    expect(methodSelect().value).toBe("DCF");
    expect(lastCalc()).toMatchObject({ method: "DCF" });
  });

  it("shows the result: intrinsic value, discount/premium and the status line", async () => {
    await mountPanel();
    await waitFor(() => expect(screen.getAllByText(/187\.50/).length).toBeGreaterThan(0));
    expect(screen.getAllByText("-20.0%").length).toBeGreaterThan(0);
    expect(screen.getByText(/Active:/)).toHaveTextContent("Active: Auto");
  });

  it("shows the backend's own message when the calculation reports an error", async () => {
    apiPost.mockImplementation(async (path: string) =>
      path === CALC_PATH ? { ...CALC_OK, intrinsic_value_per_share: null, error: "Missing required inputs for PSG" } : undefined,
    );
    await mountPanel();
    expect(await screen.findByText("Missing required inputs for PSG")).toBeInTheDocument();
  });

  it("shows the request error when the calculation call fails", async () => {
    apiPost.mockImplementation(async (path: string) => {
      if (path === CALC_PATH) throw new Error("POST /x failed: 500");
      return undefined;
    });
    await mountPanel();
    expect(await screen.findByText("POST /x failed: 500")).toBeInTheDocument();
  });
});

describe("ManualCalculationPanel: the method select", () => {
  it("lists the nine methods in order, plus the saved entry first once a valuation is saved", async () => {
    await mountPanel();
    expect(Array.from(methodSelect().options).map((o) => o.value)).toEqual([
      "DCF",
      "DFCF",
      "DNI",
      "DNI_NORMALIZED",
      "CF_NORMALIZED",
      "FCF_NORMALIZED",
      "PRICE_TO_BOOK_STANDARD",
      "PRICE_TO_BOOK",
      "PSG",
    ]);
    cleanup();
    hook = { data: makeSaved() };
    await mountPanel();
    expect(Array.from(methodSelect().options).map((o) => o.value)).toEqual([
      "SAVED_CUSTOM",
      "DCF",
      "DFCF",
      "DNI",
      "DNI_NORMALIZED",
      "CF_NORMALIZED",
      "FCF_NORMALIZED",
      "PRICE_TO_BOOK_STANDARD",
      "PRICE_TO_BOOK",
      "PSG",
    ]);
  });

  it("starts on the saved entry when a valuation is saved, with the saved values as defaults", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    expect(methodSelect().value).toBe("SAVED_CUSTOM");
    expect(rowInput(/^Total debt$/i).value).toBe("$1,000.00");
    expect(lastCalc()).toEqual({
      method: "DFCF",
      current_value: 20_000_000_000,
      growth_yr_1_5: 0.12,
      growth_yr_6_10: 0.07,
      growth_yr_11_20: 0.03,
      discount_rate: 0.1,
      shares_outstanding: 500_000_000,
      total_debt: 1_000_000_000,
      cash_and_st_investments: 2_000_000_000,
      book_value_per_share: null,
      pb_mean_ratio: null,
      pb_sd_ratio: null,
      book_value_per_share_standard: null,
      pb_mean_ratio_standard: null,
      pb_sd_ratio_standard: null,
      sales_per_share: null,
      projected_growth_rate: null,
      fair_psg_ratio: null,
      last_close: 150,
    });
  });

  it("shows the four cash-flow rows and four sliders for the six twenty-year methods", async () => {
    for (const method of ["DCF", "DFCF", "DNI", "DNI_NORMALIZED", "CF_NORMALIZED", "FCF_NORMALIZED"] as const) {
      cleanup();
      await mountPanel(makeAuto({ selected_method: method }));
      expect(rowLabels()).toHaveLength(4);
      expect(sliders()).toHaveLength(4);
    }
  });

  it("labels the current-value row after the selected method", async () => {
    const expected: Record<string, RegExp> = {
      DCF: /^Operating cash flow \(current\)$/i,
      DFCF: /^Free cash flow \(current\)$/i,
      DNI: /^Net income \(current\)$/i,
      DNI_NORMALIZED: /^Net income \(smoothed, 5yr avg\)$/i,
      CF_NORMALIZED: /^Operating cash flow \(smoothed, 5yr avg\)$/i,
      FCF_NORMALIZED: /^Free cash flow \(smoothed, 5yr avg\)$/i,
    };
    for (const [method, label] of Object.entries(expected)) {
      cleanup();
      await mountPanel(makeAuto({ selected_method: method as Step3Method }));
      expect(rowLabels()[0]).toMatch(label);
    }
  });

  it("pre-fills the current value from the candidate that belongs to each method", async () => {
    const expected = {
      DCF: 48_253_000_000,
      DFCF: 41_000_000_000,
      DNI: 35_000_000_000,
      DNI_NORMALIZED: 30_500_000_000,
      CF_NORMALIZED: 44_000_000_000,
      FCF_NORMALIZED: 39_000_000_000,
    } as const;
    for (const [method, value] of Object.entries(expected)) {
      cleanup();
      await mountPanel(makeAuto({ selected_method: method as Step3Method }));
      expect(lastCalc()).toMatchObject({ method, current_value: value });
    }
  });

  it("appends '+ ST Investments' to the cash row when the source includes short-term investments", async () => {
    await mountPanel(makeAuto({ inputs: { cash_and_st_investments_includes_short_term_investments: true } }));
    expect(rowLabels()[3]).toMatch(/^Cash \+ ST investments$/i);
  });

  it("switches to PSG: three rows, no sliders, a fresh request for PSG with the PSG defaults", async () => {
    await mountPanel();
    apiPost.mockClear();
    fireEvent.change(methodSelect(), { target: { value: "PSG" } });
    await waitFor(() => expect(calcBodies().length).toBeGreaterThan(0));
    expect(rowLabels()).toEqual(["Sales per share", "Projected growth rate", "Fair PSG ratio"].map((l) => expect.stringMatching(new RegExp(`^${l}$`, "i"))));
    expect(screen.queryAllByRole("slider")).toHaveLength(0);
    expect(lastCalc()).toEqual({ ...DCF_AUTO_PAYLOAD, method: "PSG", current_value: null });
  });

  it("switches to either price-to-book method: three rows, and the standard one reads the _standard fields", async () => {
    await mountPanel();
    fireEvent.change(methodSelect(), { target: { value: "PRICE_TO_BOOK_STANDARD" } });
    expect(rowLabels()).toEqual(
      ["Book value per share \\(standard\\)", "Mean P/B", "SD P/B"].map((l) => expect.stringMatching(new RegExp(`^${l}$`, "i"))),
    );
    expect(rowInput(/^Book value per share \(standard\)$/i).value).toBe("$22.10");
    expect(rowInput(/^Mean P\/B$/i).value).toBe("1.50");
    expect(rowInput(/^SD P\/B$/i).value).toBe("0.30");
    fireEvent.change(methodSelect(), { target: { value: "PRICE_TO_BOOK" } });
    expect(rowInput(/^Book value per share \(custom\)$/i).value).toBe("$25.50");
    expect(rowInput(/^Mean P\/B$/i).value).toBe("1.80");
    expect(rowInput(/^SD P\/B$/i).value).toBe("0.40");
  });

  it("throws away what was typed for the previous method when the method changes", async () => {
    await mountPanel();
    type(rowInput(/^Total debt$/i), "999");
    fireEvent.change(methodSelect(), { target: { value: "DFCF" } });
    expect(rowInput(/^Total debt$/i).value).toBe("$12,000.00");
    expect(lastCalc()).toMatchObject({ method: "DFCF", total_debt: 12_000_000_000, current_value: 41_000_000_000 });
  });

  it("clears the previous result immediately and shows the new one after the new request", async () => {
    await mountPanel();
    await waitFor(() => expect(screen.getAllByText(/187\.50/).length).toBeGreaterThan(0));
    let release: (v: Step3ManualOut) => void = () => {};
    apiPost.mockImplementation((path: string) => (path === CALC_PATH ? new Promise((r) => (release = r)) : Promise.resolve(undefined)));
    fireEvent.change(methodSelect(), { target: { value: "DNI" } });
    await waitFor(() => expect(screen.queryAllByText(/187\.50/)).toHaveLength(0));
    await act(async () => release({ ...CALC_OK, intrinsic_value_per_share: 99.25 }));
    await waitFor(() => expect(screen.getAllByText(/99\.25/).length).toBeGreaterThan(0));
  });

  it("shows the P/B bands table under a price-to-book method when the result carries bands", async () => {
    apiPost.mockImplementation(async (path: string) =>
      path === CALC_PATH
        ? { ...CALC_OK, pb_bands: { minus_2sd: 10, minus_1sd: 20, mean: 30, plus_1sd: 40, plus_2sd: 50 } }
        : undefined,
    );
    await mountPanel(makeAuto({ selected_method: "PRICE_TO_BOOK_STANDARD" }));
    expect(await screen.findByText("Mean − 2 SD")).toBeInTheDocument();
    expect(screen.getByText("$50.00")).toBeInTheDocument();
  });
});

describe("ManualCalculationPanel: formatted rows", () => {
  it("shows the formatted text while idle and the raw number while focused", async () => {
    await mountPanel();
    const debt = rowInput(/^Total debt$/i);
    expect(debt.value).toBe("$12,000.00");
    fireEvent.focus(debt);
    expect(debt.value).toBe("12000");
    fireEvent.blur(debt);
    expect(debt.value).toBe("$12,000.00");
  });

  it("formats each kind: money in millions, shares, ratio and percent", async () => {
    await mountPanel();
    expect(rowInput(/^Operating cash flow \(current\)$/i).value).toBe("$48,253.00");
    expect(rowInput(/^Shares outstanding$/i).value).toBe("1,000.00");
    expect(rowInput(/^Total debt$/i).value).toBe("$12,000.00");
    expect(rowInput(/^Cash$/i).value).toBe("$5,500.00");
    fireEvent.change(methodSelect(), { target: { value: "PSG" } });
    expect(rowInput(/^Sales per share$/i).value).toBe("$12.50");
    expect(rowInput(/^Projected growth rate$/i).value).toBe("+35.0%");
    expect(rowInput(/^Fair PSG ratio$/i).value).toBe("1.20");
  });

  it("shows the raw editable text for each scaled kind while focused", async () => {
    await mountPanel();
    const shares = rowInput(/^Shares outstanding$/i);
    fireEvent.focus(shares);
    expect(shares.value).toBe("1000");
    fireEvent.blur(shares);
    fireEvent.change(methodSelect(), { target: { value: "PSG" } });
    const growth = rowInput(/^Projected growth rate$/i);
    fireEvent.focus(growth);
    expect(growth.value).toBe("35");
  });

  it("uses the quote currency's prefix for money rows", async () => {
    await mountPanel(makeAuto({ inputs: { quote_currency: "EUR" } }));
    expect(rowInput(/^Total debt$/i).value).toBe("€12,000.00");
  });

  it("starts empty (and sends null) when the auto data has no value", async () => {
    await mountPanel(makeAuto({ inputs: { total_debt: null } }));
    expect(rowInput(/^Total debt$/i).value).toBe("");
    expect(lastCalc()).toMatchObject({ total_debt: null });
  });

  it("scales millions rows by 1e6 and percent rows by 1/100 when sending, and sends plain rows as typed", async () => {
    await mountPanel();
    type(rowInput(/^Total debt$/i), "12.5");
    expect(lastCalc()).toMatchObject({ total_debt: 12_500_000 });
    type(rowInput(/^Shares outstanding$/i), "2.5");
    expect(lastCalc()).toMatchObject({ shares_outstanding: 2_500_000 });
    fireEvent.change(methodSelect(), { target: { value: "PSG" } });
    type(rowInput(/^Projected growth rate$/i), "25");
    expect(lastCalc()).toMatchObject({ projected_growth_rate: 0.25 });
    type(rowInput(/^Sales per share$/i), "20");
    expect(lastCalc()).toMatchObject({ sales_per_share: 20 });
  });

  it("recalculates on every keystroke", async () => {
    await mountPanel();
    apiPost.mockClear();
    const debt = rowInput(/^Total debt$/i);
    type(debt, "1");
    type(debt, "12");
    type(debt, "123");
    expect(calcBodies().map((b) => b.total_debt)).toEqual([1_000_000, 12_000_000, 123_000_000]);
  });

  // The parse is parseFloat on the trimmed text, and anything it cannot read
  // (including text it silently cuts short) is sent as given by that rule.
  it.each([
    ["12.5", 12_500_000],
    ["  7  ", 7_000_000],
    ["-3", -3_000_000],
    [".5", 500_000],
    ["5.", 5_000_000],
    ["+4", 4_000_000],
    ["12abc", 12_000_000],
    ["1e3", 1_000_000_000],
    ["1,234", 1_000_000],
    ["abc", null],
    ["-", null],
    ["", null],
    ["   ", null],
  ])("parses %j in a millions row as %j", async (text, expected) => {
    await mountPanel();
    type(rowInput(/^Total debt$/i), text);
    expect(lastCalc()).toMatchObject({ total_debt: expected });
  });

  it("never rewrites the typed text: invalid text stays visible as typed and is sent as null", async () => {
    await mountPanel();
    const debt = rowInput(/^Total debt$/i);
    fireEvent.focus(debt);
    type(debt, "abc");
    expect(debt.value).toBe("abc");
    fireEvent.blur(debt);
    expect(debt.value).toBe("abc");
    expect(lastCalc()).toMatchObject({ total_debt: null });
  });

  it("formats typed text it can read once the row loses focus", async () => {
    await mountPanel();
    const debt = rowInput(/^Total debt$/i);
    fireEvent.focus(debt);
    type(debt, "7.5");
    fireEvent.blur(debt);
    expect(debt.value).toBe("$7.50");
  });
});

describe("ManualCalculationPanel: sliders", () => {
  it("has four sliders with these ranges, in this order", async () => {
    await mountPanel();
    const spec = sliders().map((s) => [s.min, s.max, s.step, s.value]);
    expect(spec).toEqual([
      ["-50", "100", "0.1", "15"],
      ["-50", "100", "0.1", "9"],
      ["-50", "100", "0.1", "4"],
      ["0", "30", "0.1", "8.5"],
    ]);
  });

  it("shows each value as a signed percent beside its label", async () => {
    await mountPanel();
    expect(screen.getByText("+15.0%")).toBeInTheDocument();
    expect(screen.getByText("+9.0%")).toBeInTheDocument();
    expect(screen.getByText("+4.0%")).toBeInTheDocument();
    expect(screen.getByText("+8.5%")).toBeInTheDocument();
  });

  it("shows the analyst source under the first slider, or '% per year' without one", async () => {
    await mountPanel();
    expect(screen.getByText("Analyst consensus")).toBeInTheDocument();
    cleanup();
    await mountPanel(makeAuto({ inputs: { growth_yr_1_5_source: null } }));
    expect(screen.getByText("% per year")).toBeInTheDocument();
  });

  it("sends percentage points divided by 100 on every change, for each slider", async () => {
    await mountPanel();
    const [g15, g610, g1120, discount] = sliders();
    fireEvent.change(g15, { target: { value: "20" } });
    expect(lastCalc()).toMatchObject({ growth_yr_1_5: 0.2 });
    fireEvent.change(g610, { target: { value: "12.5" } });
    expect(lastCalc()).toMatchObject({ growth_yr_1_5: 0.2, growth_yr_6_10: 0.125 });
    fireEvent.change(g1120, { target: { value: "-5" } });
    expect(lastCalc()).toMatchObject({ growth_yr_11_20: -0.05 });
    fireEvent.change(discount, { target: { value: "10" } });
    expect(lastCalc()).toMatchObject({ discount_rate: 0.1 });
  });

  it("updates the readout and the fill when moved", async () => {
    await mountPanel();
    const g15 = sliders()[0];
    fireEvent.change(g15, { target: { value: "25" } });
    expect(screen.getByText("+25.0%")).toBeInTheDocument();
    expect(g15.value).toBe("25");
    // (25 - -50) / 150 = 50%
    expect(g15.style.getPropertyValue("--range-fill")).toBe("50%");
  });

  it("shows a dash and parks the thumb at 0 when there is no value", async () => {
    await mountPanel(makeAuto({ inputs: { growth_yr_1_5: null } }));
    const g15 = sliders()[0];
    expect(g15.value).toBe("0");
    expect(within(g15.parentElement as HTMLElement).getByText("—")).toBeInTheDocument();
    expect(lastCalc()).toMatchObject({ growth_yr_1_5: null });
  });

  it("keeps an out-of-range stored value as it is (the fill clamps, the state does not)", async () => {
    await mountPanel(makeAuto({ inputs: { growth_yr_1_5: 2.0 } }));
    expect(lastCalc()).toMatchObject({ growth_yr_1_5: 2 });
    expect(sliders()[0].style.getPropertyValue("--range-fill")).toBe("100%");
    expect(screen.getByText("+200.0%")).toBeInTheDocument();
  });
});

describe("ManualCalculationPanel: the action bar", () => {
  it("Save sends the method and all 17 fields to the custom-valuation endpoint, then revalidates", async () => {
    await mountPanel();
    fireEvent.click(btn(/^save$/i));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    const { last_close: _unused, ...saveBody } = DCF_AUTO_PAYLOAD;
    void _unused;
    expect(apiPut).toHaveBeenCalledWith(`/tickers/${TICKER}/custom-valuation`, saveBody);
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(3));
    expect(mutate.mock.calls[2]).toEqual(["/screener"]);
    const [byTicker, byWatchlist] = [mutate.mock.calls[0][0], mutate.mock.calls[1][0]];
    expect(byTicker(`/tickers/${TICKER}/step3`)).toBe(true);
    expect(byTicker("/tickers/OTHER/step3")).toBe(false);
    expect(byWatchlist("/watchlists/3/rows")).toBe(true);
  });

  it("Save saves what is currently typed, with the real method behind a saved entry", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    type(rowInput(/^Total debt$/i), "3");
    fireEvent.click(btn(/^save$/i));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut.mock.calls[0][1]).toMatchObject({ method: "DFCF", total_debt: 3_000_000, shares_outstanding: 500_000_000 });
  });

  it("shows 'Working…' and disables the buttons while an action is in flight", async () => {
    let release: () => void = () => {};
    apiPut.mockImplementation(() => new Promise<void>((r) => (release = r)));
    await mountPanel();
    fireEvent.click(btn(/^save$/i));
    const working = await screen.findByRole("button", { name: /working…/i });
    expect(working).toBeDisabled();
    await act(async () => release());
    await waitFor(() => expect(btn(/^save$/i)).toBeEnabled());
  });

  it("shows only Save when nothing is saved", async () => {
    await mountPanel();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Save"]);
  });

  it("a saved, inactive valuation offers Activate and Delete, and Activate posts to the activate endpoint", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Save", "Activate", "Delete"]);
    expect(screen.getByText(/Active:/)).toHaveTextContent("Active: Auto");
    expect(screen.getByText(/— saved/)).toBeInTheDocument();
    apiPost.mockClear();
    fireEvent.click(btn(/^activate$/i));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(`/tickers/${TICKER}/custom-valuation/activate`));
  });

  it("an active valuation offers Revert to auto, which posts to the deactivate endpoint", async () => {
    hook = { data: makeSaved({ is_active: true }) };
    await mountPanel();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Save", "Revert to auto", "Delete"]);
    expect(screen.getByText(/Active:/)).toHaveTextContent("Active: Custom");
    apiPost.mockClear();
    fireEvent.click(btn(/^revert to auto$/i));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(`/tickers/${TICKER}/custom-valuation/deactivate`));
  });

  it("Delete asks first; Cancel backs out without calling the server", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    fireEvent.click(btn(/^delete$/i));
    expect(screen.getByText(/Delete this saved custom valuation for ACME\?/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).not.toBeInTheDocument();
    fireEvent.click(btn(/^cancel$/i));
    expect(screen.queryByText(/Delete this saved custom valuation/i)).not.toBeInTheDocument();
    expect(btn(/^delete$/i)).toBeInTheDocument();
    expect(apiDelete).not.toHaveBeenCalled();
  });

  it("the confirm text adds the revert warning only when the valuation is active", async () => {
    hook = { data: makeSaved({ is_active: true }) };
    await mountPanel();
    fireEvent.click(btn(/^delete$/i));
    expect(screen.getByText(/revert the ticker to auto calculation everywhere/i)).toBeInTheDocument();
  });

  it("Confirm delete calls the delete endpoint and revalidates", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    fireEvent.click(btn(/^delete$/i));
    fireEvent.click(btn(/^confirm delete$/i));
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith(`/tickers/${TICKER}/custom-valuation`));
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(3));
  });

  it("shows the server's reason when an action fails, else the action's own fallback", async () => {
    apiPut.mockRejectedValueOnce(new Error("PUT /x failed: 400 - Missing required inputs for PSG"));
    await mountPanel();
    fireEvent.click(btn(/^save$/i));
    expect(await screen.findByText("Missing required inputs for PSG")).toBeInTheDocument();
    apiPut.mockRejectedValueOnce(new Error("PUT /x failed: 500"));
    fireEvent.click(btn(/^save$/i));
    expect(await screen.findByText(/Failed to save — please try again\./)).toBeInTheDocument();
    expect(screen.queryByText("Missing required inputs for PSG")).not.toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("the other actions have their own fallbacks", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    apiPost.mockImplementation(async (path: string) => {
      if (path === CALC_PATH) return CALC_OK;
      throw new Error("POST failed: 500");
    });
    fireEvent.click(btn(/^activate$/i));
    expect(await screen.findByText(/Failed to activate — please try again\./)).toBeInTheDocument();
    apiDelete.mockRejectedValueOnce(new Error("DELETE failed: 500"));
    fireEvent.click(btn(/^delete$/i));
    fireEvent.click(btn(/^confirm delete$/i));
    expect(await screen.findByText(/Failed to delete — please try again\./)).toBeInTheDocument();
  });
});

describe("ManualCalculationPanel: the method select (kit)", () => {
  it("is a native select named by a visible 'Method' label", async () => {
    await mountPanel();
    const select = screen.getByLabelText("Method");
    expect(select).toBe(methodSelect());
    expect(select.tagName).toBe("SELECT");
    expect(select).toHaveAttribute("id", "manual-method");
    expect(screen.getByText("Method")).toBeVisible();
  });

  it("is the wide token and never removes its own focus ring", async () => {
    await mountPanel();
    expect(methodSelect().parentElement).toHaveClass("w-80", "max-w-full");
    expect(methodSelect().className).not.toMatch(/outline-none/);
  });

  it("shows sentence-case option labels (the values are unchanged)", async () => {
    hook = { data: makeSaved({ method: "FCF_NORMALIZED" }) };
    await mountPanel();
    expect(Array.from(methodSelect().options).map((o) => o.textContent)).toEqual([
      "Discounted free cash flow (normalized) · custom",
      "Discounted cash flow (operating CF)",
      "Discounted free cash flow",
      "Discounted net income",
      "Discounted net income (normalized)",
      "Discounted cash flow (normalized)",
      "Discounted free cash flow (normalized)",
      "Price to book (standard)",
      "Price to book (custom)",
      "Price to sales growth",
    ]);
  });

  it("changes the method with the keyboard-equivalent change event exactly as before", async () => {
    await mountPanel();
    fireEvent.change(methodSelect(), { target: { value: "DNI" } });
    expect(methodSelect().value).toBe("DNI");
    expect(rowLabels()[0]).toBe("Net income (current)");
  });
});

describe("ManualCalculationPanel: the rows (kit Input)", () => {
  it("names every box by its visible label and links the sublabel as its description", async () => {
    await mountPanel();
    const names = ["Operating cash flow (current)", "Shares outstanding", "Total debt", "Cash"];
    for (const name of names) {
      const box = screen.getByRole("textbox", { name });
      expect(box).toHaveAttribute("inputmode", "decimal");
      expect(box).toHaveAccessibleDescription("(in millions)");
    }
    fireEvent.change(methodSelect(), { target: { value: "PRICE_TO_BOOK_STANDARD" } });
    for (const name of ["Book value per share (standard)", "Mean P/B", "SD P/B"]) {
      const box = screen.getByRole("textbox", { name });
      expect(box).not.toHaveAttribute("aria-describedby");
    }
  });

  it("no control in the panel removes its focus ring", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    expect(document.querySelector('[class*="outline-none"]')).toBeNull();
  });

  it("shows an inline error, and marks the box invalid, for text the parse cannot read", async () => {
    await mountPanel();
    const debt = rowInput(/^Total debt$/i);
    type(debt, "abc");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Enter a number.");
    expect(debt).toHaveAttribute("aria-invalid", "true");
    expect(debt).toHaveAccessibleDescription("(in millions) Enter a number.");
    expect(debt.value).toBe("abc");
    expect(lastCalc()).toMatchObject({ total_debt: null });
  });

  it("clears the error the moment the text reads", async () => {
    await mountPanel();
    const debt = rowInput(/^Total debt$/i);
    type(debt, "abc");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    type(debt, "12");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(debt).not.toHaveAttribute("aria-invalid");
  });

  it.each(["", "   ", "12.5", "12abc", "1e3", "+4", "1,234", ".5", "5."])("shows no error for %j", async (text) => {
    await mountPanel();
    type(rowInput(/^Total debt$/i), text);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("gives '-', '.' and '-.' no error while the box has focus, and an error once it loses it", async () => {
    await mountPanel();
    const debt = rowInput(/^Total debt$/i);
    for (const text of ["-", ".", "-."]) {
      fireEvent.focus(debt);
      type(debt, text);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      fireEvent.blur(debt);
      expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    }
  });

  it("never blocks the calculation or Save on an unreadable row", async () => {
    await mountPanel();
    type(rowInput(/^Total debt$/i), "abc");
    expect(lastCalc()).toMatchObject({ total_debt: null });
    fireEvent.click(btn(/^save$/i));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut.mock.calls[0][1]).toMatchObject({ total_debt: null });
  });

  it("shows one error line per bad row, under that row's box", async () => {
    await mountPanel();
    type(rowInput(/^Total debt$/i), "x");
    type(rowInput(/^Shares outstanding$/i), "y");
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(2);
    expect(rowInput(/^Total debt$/i).closest("td")).toContainElement(alerts[1]);
    expect(rowInput(/^Shares outstanding$/i).closest("td")).toContainElement(alerts[0]);
  });

  it("is a plain text input: no native number spinner and no min or max", async () => {
    await mountPanel();
    const debt = rowInput(/^Total debt$/i);
    expect(debt).toHaveAttribute("type", "text");
    expect(debt).not.toHaveAttribute("min");
    expect(debt).not.toHaveAttribute("max");
    expect(debt).not.toHaveAttribute("step");
  });
});

describe("ManualCalculationPanel: sliders (accessibility)", () => {
  const NAMES = ["Growth yr 1-5", "Growth yr 6-10", "Growth yr 11-20 (terminal)", "Discount rate (CAPM)"];

  it("names each slider by its visible label", async () => {
    await mountPanel();
    for (const name of NAMES) {
      const slider = screen.getByRole("slider", { name });
      expect(slider).toHaveAttribute("type", "range");
    }
  });

  it("gives each slider an aria-valuetext equal to the readout beside it", async () => {
    await mountPanel();
    const [g15, g610, g1120, discount] = NAMES.map((name) => screen.getByRole("slider", { name }));
    expect(g15).toHaveAttribute("aria-valuetext", "+15.0%");
    expect(g610).toHaveAttribute("aria-valuetext", "+9.0%");
    expect(g1120).toHaveAttribute("aria-valuetext", "+4.0%");
    expect(discount).toHaveAttribute("aria-valuetext", "+8.5%");
    fireEvent.change(g15, { target: { value: "-12.5" } });
    expect(g15).toHaveAttribute("aria-valuetext", "-12.5%");
    expect(screen.getByText("-12.5%")).toBeInTheDocument();
  });

  it("says 'No value' when the readout is a dash", async () => {
    await mountPanel(makeAuto({ inputs: { growth_yr_1_5: null } }));
    expect(screen.getByRole("slider", { name: "Growth yr 1-5" })).toHaveAttribute("aria-valuetext", "No value");
  });

  it("links the analyst-source note as the first slider's description", async () => {
    await mountPanel();
    expect(screen.getByRole("slider", { name: "Growth yr 1-5" })).toHaveAccessibleDescription("Analyst consensus");
    expect(screen.getByRole("slider", { name: "Growth yr 6-10" })).not.toHaveAttribute("aria-describedby");
  });

  it("keeps the .range-slider styling and restores a visible keyboard focus ring", async () => {
    await mountPanel();
    for (const slider of sliders()) {
      expect(slider).toHaveClass("range-slider", "focus-visible:outline-2", "focus-visible:outline-offset-2", "focus-visible:outline-brand");
      expect(slider.className).not.toMatch(/outline-none/);
    }
  });

  it("leaves the arrow, Home, End and Page keys to the browser", async () => {
    await mountPanel();
    const slider = screen.getByRole("slider", { name: "Growth yr 1-5" });
    for (const key of ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"]) {
      // fireEvent returns false only when something called preventDefault.
      expect(fireEvent.keyDown(slider, { key })).toBe(true);
    }
  });
});

describe("ManualCalculationPanel: buttons (kit)", () => {
  it("Save is the one primary button, 32px like the outline buttons beside it", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    const save = btn(/^save$/i);
    expect(save).toHaveClass("bg-brand", "h-8", "text-xs");
    expect(save).toHaveAttribute("type", "button");
    for (const name of [/^activate$/i, /^delete$/i]) {
      expect(btn(name)).toHaveClass("h-8", "border", "text-xs");
      expect(btn(name).className).not.toMatch(/bg-brand/);
    }
  });

  it("Revert to auto is a plain outline button", async () => {
    hook = { data: makeSaved({ is_active: true }) };
    await mountPanel();
    expect(btn(/^revert to auto$/i)).toHaveClass("border-border-input", "h-8", "text-text-secondary");
  });

  it("Activate and Delete keep their positive and negative tone", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    expect(btn(/^activate$/i)).toHaveClass("text-positive", "border-positive/40", "bg-positive/10");
    expect(btn(/^activate$/i).className).not.toMatch(/text-text-secondary|border-border-input/);
    expect(btn(/^delete$/i)).toHaveClass("text-negative", "border-negative/40", "bg-negative/10");
    expect(btn(/^delete$/i).className).not.toMatch(/text-text-secondary|border-border-input/);
  });

  it("the delete confirmation has a danger Confirm delete and an outline Cancel, both 36px", async () => {
    hook = { data: makeSaved() };
    await mountPanel();
    fireEvent.click(btn(/^delete$/i));
    expect(btn(/^confirm delete$/i)).toHaveClass("text-negative", "h-9");
    expect(btn(/^cancel$/i)).toHaveClass("border-border-input", "h-9");
  });

  it("shows 'Deleting…' while the delete is in flight", async () => {
    let release: () => void = () => {};
    apiDelete.mockImplementation(() => new Promise<void>((r) => (release = r)));
    hook = { data: makeSaved() };
    await mountPanel();
    fireEvent.click(btn(/^delete$/i));
    fireEvent.click(btn(/^confirm delete$/i));
    expect(await screen.findByRole("button", { name: /deleting…/i })).toBeDisabled();
    expect(btn(/^cancel$/i)).toBeDisabled();
    await act(async () => release());
  });

  it("every button has an accessible name and none is hand-built", async () => {
    hook = { data: makeSaved({ is_active: true }) };
    await mountPanel();
    fireEvent.click(btn(/^delete$/i));
    for (const b of screen.getAllByRole("button")) {
      expect(b).toHaveAccessibleName();
      expect(b.className).toMatch(/inline-flex/);
    }
    expect(document.querySelector('[class*="outline-none"]')).toBeNull();
  });

  it("the revert action falls back to its own sentence-case message", async () => {
    hook = { data: makeSaved({ is_active: true }) };
    await mountPanel();
    apiPost.mockImplementation(async (path: string) => {
      if (path === CALC_PATH) return CALC_OK;
      throw new Error("POST failed: 500");
    });
    fireEvent.click(btn(/^revert to auto$/i));
    expect(await screen.findByText("Failed to revert to auto — please try again.")).toBeInTheDocument();
  });
});

describe("ManualCalculationPanel: sentence case", () => {
  it("uses sentence case for the heading, the readout label and every row and slider label", async () => {
    await mountPanel();
    expect(screen.getByRole("heading", { name: "Custom valuation" })).toBeInTheDocument();
    expect(screen.getByText("Discount/premium")).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    for (const old of ["Custom Valuation", "Discount/Premium", "Growth Yr", "Discount Rate", "Total Debt", "Shares Outstanding", "Revert to Auto"]) {
      expect(text).not.toContain(old);
    }
  });

  it("keeps the backend's own strings untouched", async () => {
    apiPost.mockImplementation(async (path: string) =>
      path === CALC_PATH ? { ...CALC_OK, intrinsic_value_per_share: null, error: "Missing Required Inputs For PSG" } : undefined,
    );
    await mountPanel();
    expect(await screen.findByText("Missing Required Inputs For PSG")).toBeInTheDocument();
  });
});

// Golden scenarios: different methods and input sets, each pinned to the exact
// request the backend receives (and the number it renders back).
describe("ManualCalculationPanel: golden scenarios", () => {
  it("golden 1, discounted cash flow: edited shares, growth and discount rate", async () => {
    serve({ intrinsic_value_per_share: 736.1980869974531, discount_premium_pct: -0.796250489305443, verdict: "undervalued" });
    await mountPanel();
    type(rowInput(/^Shares outstanding$/i), "1250");
    fireEvent.change(sliders()[0], { target: { value: "12" } });
    fireEvent.change(sliders()[3], { target: { value: "9.5" } });
    expect(lastCalc()).toEqual({
      ...DCF_AUTO_PAYLOAD,
      shares_outstanding: 1_250_000_000,
      growth_yr_1_5: 0.12,
      discount_rate: 0.095,
    });
    await waitFor(() => expect(screen.getAllByText("$736.20").length).toBeGreaterThan(0));
    expect(screen.getAllByText("-79.6%").length).toBeGreaterThan(0);
  });

  it("golden 2, price to sales growth: edited sales per share, growth and PSG ratio", async () => {
    serve({ intrinsic_value_per_share: 750, discount_premium_pct: -0.8, verdict: "undervalued" });
    await mountPanel(makeAuto({ selected_method: "PSG" }));
    type(rowInput(/^Sales per share$/i), "20");
    type(rowInput(/^Projected growth rate$/i), "25");
    type(rowInput(/^Fair PSG ratio$/i), "1.5");
    expect(lastCalc()).toEqual({
      ...DCF_AUTO_PAYLOAD,
      method: "PSG",
      current_value: null,
      sales_per_share: 20,
      projected_growth_rate: 0.25,
      fair_psg_ratio: 1.5,
    });
    await waitFor(() => expect(screen.getAllByText("$750.00").length).toBeGreaterThan(0));
    expect(screen.getAllByText("-80.0%").length).toBeGreaterThan(0);
  });

  it("golden 3, price to book (standard): edited book value, mean and SD", async () => {
    serve({
      intrinsic_value_per_share: 48,
      discount_premium_pct: 2.125,
      verdict: "overvalued",
      pb_bands: { minus_2sd: 33, minus_1sd: 40.5, mean: 48, plus_1sd: 55.5, plus_2sd: 63 },
    });
    await mountPanel(makeAuto({ selected_method: "PRICE_TO_BOOK_STANDARD" }));
    type(rowInput(/^Book value per share \(standard\)$/i), "30");
    type(rowInput(/^Mean P\/B$/i), "1.6");
    type(rowInput(/^SD P\/B$/i), "0.25");
    expect(lastCalc()).toEqual({
      ...DCF_AUTO_PAYLOAD,
      method: "PRICE_TO_BOOK_STANDARD",
      current_value: null,
      book_value_per_share_standard: 30,
      pb_mean_ratio_standard: 1.6,
      pb_sd_ratio_standard: 0.25,
    });
    expect(await screen.findByText("Mean − 2 SD")).toBeInTheDocument();
    expect(screen.getByText("$33.00")).toBeInTheDocument();
    expect(screen.getByText("$63.00")).toBeInTheDocument();
    expect(screen.getAllByText("$48.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+212.5%").length).toBeGreaterThan(0);
  });

  it("golden 4, saved free-cash-flow valuation: saved values in, the same values saved back", async () => {
    serve({ intrinsic_value_per_share: 686.0377988553931, discount_premium_pct: -0.7813531553942586, verdict: "undervalued" });
    hook = { data: makeSaved() };
    await mountPanel();
    type(rowInput(/^Cash/i), "2500");
    fireEvent.click(btn(/^save$/i));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut.mock.calls[0][1]).toEqual({
      method: "DFCF",
      current_value: 20_000_000_000,
      growth_yr_1_5: 0.12,
      growth_yr_6_10: 0.07,
      growth_yr_11_20: 0.03,
      discount_rate: 0.1,
      shares_outstanding: 500_000_000,
      total_debt: 1_000_000_000,
      cash_and_st_investments: 2_500_000_000,
      book_value_per_share: null,
      pb_mean_ratio: null,
      pb_sd_ratio: null,
      book_value_per_share_standard: null,
      pb_mean_ratio_standard: null,
      pb_sd_ratio_standard: null,
      sales_per_share: null,
      projected_growth_rate: null,
      fair_psg_ratio: null,
    });
    expect(screen.getAllByText("$686.04").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-78.1%").length).toBeGreaterThan(0);
  });
});
