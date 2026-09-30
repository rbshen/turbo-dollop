// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mutate } from "swr";

import { DiscountRateSettingsForm } from "@/components/settings/DiscountRateSettingsForm";
import { apiPut } from "@/lib/api/client";
import type { DiscountRateConfigOut } from "@/lib/api/types";
import { useDiscountRateConfigs } from "@/lib/hooks/useDiscountRateConfig";

vi.mock("swr", async (importOriginal) => ({ ...(await importOriginal<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiPut: vi.fn() }));
vi.mock("@/lib/hooks/useDiscountRateConfig", () => ({ useDiscountRateConfigs: vi.fn() }));

const mockedPut = vi.mocked(apiPut);
const mockedMutate = vi.mocked(mutate);
const mockedHook = vi.mocked(useDiscountRateConfigs);

// The live stored values (0.03608, 0.02728) and the one with a 4th decimal
// in percent (0.036085), which the old toFixed(3) form silently rounded.
const US: DiscountRateConfigOut = {
  region: "US",
  risk_free_rate: 0.03608,
  market_risk_premium: 0.02728,
  updated_at: "2026-07-22T14:51:36.910261",
};
const PRECISE: DiscountRateConfigOut = { ...US, risk_free_rate: 0.036085 };
const SECOND: DiscountRateConfigOut = {
  region: "CA",
  risk_free_rate: 0.031,
  market_risk_premium: 0.055,
  updated_at: "2026-08-01T10:00:00",
};

function serve(data: DiscountRateConfigOut[] | undefined, extra: Record<string, unknown> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false, ...extra } as any);
}

const rf = (region = "US") => screen.getByLabelText("Risk-free rate", { selector: `#risk-free-rate-${region}` }) as HTMLInputElement;
const mrp = (region = "US") =>
  screen.getByLabelText("Market risk premium", { selector: `#market-risk-premium-${region}` }) as HTMLInputElement;
const panel = (name: string) => screen.getByRole("group", { name });
const saveIn = (name: string) => within(panel(name).parentElement as HTMLElement).getByRole("button", { name: "Save" });
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });

beforeEach(() => {
  serve([US]);
  mockedPut.mockResolvedValue(US);
  mockedMutate.mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("DiscountRateSettingsForm: layout", () => {
  it("renders with the Settings kit: sentence-case title, plain intro, no Card", () => {
    const { container } = render(<DiscountRateSettingsForm />);
    expect(screen.getByRole("heading", { name: "Discount rate by country" })).toBeInTheDocument();
    expect(screen.getByText(/The rates used to work out each ticker/)).toHaveClass("max-w-xl");
    expect(document.body.textContent).not.toMatch(/CLAUDE\.md|valuation\.md|§/);
    // no bordered, filled Card wrapper anywhere
    expect(container.querySelector(".rounded-lg.border.bg-surface")).toBeNull();
  });

  it("shows each region as a group headed by its name, with two rows and its own footer", () => {
    render(<DiscountRateSettingsForm />);
    const group = panel("United States (US)");
    expect(within(group).getByRole("heading", { level: 3, name: "United States (US)" })).toBeInTheDocument();
    for (const label of ["Risk-free rate", "Market risk premium"]) {
      const row = within(group).getByText(label, { selector: "label" }).closest("div.grid");
      expect(row).toHaveClass("sm:grid-cols-[minmax(0,1fr)_16rem]");
    }
    expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(1);
    expect(screen.getByText(/^Last updated /)).toBeInTheDocument();
  });

  it("uses short typed fields with % as a suffix, not in the label, and hints instead of tooltips", () => {
    render(<DiscountRateSettingsForm />);
    for (const el of [rf(), mrp()]) {
      expect(el).toHaveAttribute("type", "text");
      expect(el).toHaveClass("w-24");
    }
    expect(screen.getAllByText("%")).toHaveLength(2);
    expect(screen.getByText("Risk-free rate", { selector: "label" }).textContent).toBe("Risk-free rate");
    expect(rf().getAttribute("aria-describedby")).toContain("risk-free-rate-US-hint");
    expect(screen.queryByRole("button", { name: /About/ })).toBeNull();
  });
});

describe("DiscountRateSettingsForm: stored values are shown at full precision", () => {
  it("shows 0.03608 and 0.02728 as 3.608 and 2.728", () => {
    render(<DiscountRateSettingsForm />);
    expect([rf().value, mrp().value]).toEqual(["3.608", "2.728"]);
  });

  it("shows 0.036085 as 3.6085, not the 3.608 the old form rounded it to", () => {
    serve([PRECISE]);
    render(<DiscountRateSettingsForm />);
    expect(rf().value).toBe("3.6085");
  });
});

describe("DiscountRateSettingsForm: Save until edited (the rounding fix)", () => {
  it.each([
    ["0.03608 / 0.02728", US],
    ["0.036085 / 0.02728", PRECISE],
  ])("sends nothing for an untouched form (%s): Save is disabled and pressing it does nothing", (_name, row) => {
    serve([row]);
    render(<DiscountRateSettingsForm />);
    const save = saveIn("United States (US)");
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("re-enables Save on an edit and disables it again when the edit is reverted", () => {
    render(<DiscountRateSettingsForm />);
    type(rf(), "3.5");
    expect(saveIn("United States (US)")).toBeEnabled();
    type(rf(), "3.608");
    expect(saveIn("United States (US)")).toBeDisabled();
    type(rf(), "3.6080");
    expect(saveIn("United States (US)")).toBeDisabled();
  });

  it("sends the market risk premium as its ORIGINAL stored value when only the risk-free rate is edited", async () => {
    render(<DiscountRateSettingsForm />);
    type(rf(), "3.5");
    await act(async () => fireEvent.click(saveIn("United States (US)")));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    const [path, body] = mockedPut.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/config/discount-rate");
    expect(body).toEqual({ region: "US", risk_free_rate: 0.035, market_risk_premium: 0.02728 });
    // strict equality: the old path sent 0.027280000000000002 here
    expect(body.market_risk_premium).toBe(0.02728);
  });

  it("sends the risk-free rate as its original stored value when only the premium is edited (0.036085 survives)", async () => {
    serve([PRECISE]);
    render(<DiscountRateSettingsForm />);
    type(mrp(), "3");
    await act(async () => fireEvent.click(saveIn("United States (US)")));
    const body = mockedPut.mock.calls[0][1] as Record<string, unknown>;
    expect(body).toEqual({ region: "US", risk_free_rate: 0.036085, market_risk_premium: 0.03 });
    expect(body.risk_free_rate).toBe(0.036085);
  });

  it("converts an edited value exactly: typing 3.608 sends 0.03608", async () => {
    serve([PRECISE]);
    render(<DiscountRateSettingsForm />);
    type(rf(), "3.608");
    await act(async () => fireEvent.click(saveIn("United States (US)")));
    const body = mockedPut.mock.calls[0][1] as Record<string, unknown>;
    expect(body.risk_free_rate).toBe(0.03608);
    expect(body.market_risk_premium).toBe(0.02728);
  });

  it("sends both edited values when both are edited", async () => {
    render(<DiscountRateSettingsForm />);
    type(rf(), "4.25");
    type(mrp(), "5.5");
    await act(async () => fireEvent.click(saveIn("United States (US)")));
    expect(mockedPut.mock.calls[0][1]).toEqual({ region: "US", risk_free_rate: 0.0425, market_risk_premium: 0.055 });
  });
});

describe("DiscountRateSettingsForm: validation", () => {
  it.each(["abc", "", "3,6", "1e2"])("flags %j inline on that field, blocks Save and says why", (text) => {
    render(<DiscountRateSettingsForm />);
    type(rf(), text);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(rf()).toHaveAttribute("aria-invalid", "true");
    expect(mrp()).not.toHaveAttribute("aria-invalid");
    expect(saveIn("United States (US)")).toBeDisabled();
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    expect(screen.queryByText("Save failed")).toBeNull();
    expect(mockedPut).not.toHaveBeenCalled();
  });

  it("invents no bounds and never rewrites what was typed", () => {
    render(<DiscountRateSettingsForm />);
    type(rf(), "-2.123456");
    fireEvent.blur(rf());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(rf().value).toBe("-2.123456");
  });
});

describe("DiscountRateSettingsForm: saving", () => {
  it("revalidates both config keys, then invalidates every cached step3 and summary key", async () => {
    render(<DiscountRateSettingsForm />);
    type(rf(), "3.5");
    await act(async () => fireEvent.click(saveIn("United States (US)")));
    expect(mockedMutate.mock.calls[0]).toEqual(["/config/discount-rate"]);
    expect(mockedMutate.mock.calls[1]).toEqual(["/config/discount-rates"]);
    const predicate = mockedMutate.mock.calls[2][0] as (key: unknown) => boolean;
    expect(predicate("/tickers/AAPL/step3")).toBe(true);
    expect(predicate("/tickers/AAPL/summary")).toBe(true);
    expect(predicate("/config/moat")).toBe(false);
  });

  it("reports a failed save, keeps the typed value, and resets after 3 seconds", async () => {
    vi.useFakeTimers();
    mockedPut.mockRejectedValue(new Error("500"));
    render(<DiscountRateSettingsForm />);
    type(rf(), "3.5");
    await act(async () => fireEvent.click(saveIn("United States (US)")));
    expect(screen.getByText("Save failed")).toBeInTheDocument();
    expect(rf().value).toBe("3.5");
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("Save failed")).toBeNull();
  });

  it("still shows 'Saved ✓' after the region remounts on the fresh updated_at, then resets after 3 seconds", async () => {
    vi.useFakeTimers();
    const { rerender } = render(<DiscountRateSettingsForm />);
    mockedMutate.mockImplementationOnce(async () => {
      serve([{ ...US, risk_free_rate: 0.035, updated_at: "2026-09-30T10:00:00" }]);
      act(() => rerender(<DiscountRateSettingsForm />));
      return undefined;
    });
    type(rf(), "3.5");
    await act(async () => fireEvent.click(saveIn("United States (US)")));
    expect(rf().value).toBe("3.5");
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
    expect(saveIn("United States (US)")).toBeDisabled();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("Saved ✓")).toBeNull();
  });
});

describe("DiscountRateSettingsForm: regions are independent", () => {
  beforeEach(() => serve([US, SECOND]));

  it("gives each region its own group and its own Save", () => {
    render(<DiscountRateSettingsForm />);
    expect(panel("United States (US)")).toBeInTheDocument();
    expect(panel("CA (CA)")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(2);
    expect(rf("CA").value).toBe("3.1");
    expect(mrp("CA").value).toBe("5.5");
  });

  it("editing one region enables only that region's Save", () => {
    render(<DiscountRateSettingsForm />);
    type(rf("US"), "3.5");
    expect(saveIn("United States (US)")).toBeEnabled();
    expect(saveIn("CA (CA)")).toBeDisabled();
  });

  it("an invalid entry in one region does not block, or mark, the other", () => {
    render(<DiscountRateSettingsForm />);
    type(rf("US"), "abc");
    type(mrp("CA"), "6");
    expect(saveIn("United States (US)")).toBeDisabled();
    expect(saveIn("CA (CA)")).toBeEnabled();
    expect(within(panel("CA (CA)")).queryByRole("alert")).toBeNull();
  });

  it("saves only the edited region, with its own code and its untouched original values", async () => {
    render(<DiscountRateSettingsForm />);
    type(mrp("CA"), "6");
    await act(async () => fireEvent.click(saveIn("CA (CA)")));
    expect(mockedPut).toHaveBeenCalledTimes(1);
    expect(mockedPut.mock.calls[0][1]).toEqual({ region: "CA", risk_free_rate: 0.031, market_risk_premium: 0.06 });
  });

  it("keeps an unsaved edit in one region when the other region saves and its data refreshes", async () => {
    const { rerender } = render(<DiscountRateSettingsForm />);
    type(rf("US"), "3.7");
    type(mrp("CA"), "6");
    mockedMutate.mockImplementationOnce(async () => {
      serve([US, { ...SECOND, market_risk_premium: 0.06, updated_at: "2026-09-30T10:00:00" }]);
      act(() => rerender(<DiscountRateSettingsForm />));
      return undefined;
    });
    await act(async () => fireEvent.click(saveIn("CA (CA)")));
    expect(rf("US").value).toBe("3.7");
    expect(saveIn("United States (US)")).toBeEnabled();
    expect(mrp("CA").value).toBe("6");
    expect(saveIn("CA (CA)")).toBeDisabled();
  });

  it("shows the status of a save only in the region that saved", async () => {
    render(<DiscountRateSettingsForm />);
    type(mrp("CA"), "6");
    await act(async () => fireEvent.click(saveIn("CA (CA)")));
    expect(within(panel("CA (CA)").parentElement as HTMLElement).getByText("Saved ✓")).toBeInTheDocument();
    expect(within(panel("United States (US)").parentElement as HTMLElement).queryByText("Saved ✓")).toBeNull();
  });
});
