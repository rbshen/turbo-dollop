// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mutate } from "swr";

import { StuckCheckSettingsForm } from "@/components/settings/StuckCheckSettingsForm";
import * as client from "@/lib/api/client";
import type { StuckCheckSettingsOut } from "@/lib/api/types";
import { useStuckCheckSettings } from "@/lib/hooks/useStuckCheckSettings";

vi.mock("swr", async (importOriginal) => ({ ...(await importOriginal<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: vi.fn(),
  apiPost: vi.fn(),
}));
vi.mock("@/lib/hooks/useStuckCheckSettings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/hooks/useStuckCheckSettings")>()),
  useStuckCheckSettings: vi.fn(),
}));

const mockedPut = vi.mocked(client.apiPut);
const mockedPost = vi.mocked(client.apiPost);
const mockedMutate = vi.mocked(mutate);
const mockedHook = vi.mocked(useStuckCheckSettings);

const DEFAULTS = {
  sbc_revenue_pct: 8,
  sbc_fcf_pct: 30,
  cash_conversion_line: 0.7,
  share_growth_pct: 2,
  one_off_pct: 60,
  sector_band_pp: 2,
  smoothing_days: 5,
  exemptions: [
    { ticker: "IBKR", reason: "Broker", rows: ["1", "2_fcf", "3", "5", "6"] },
    { ticker: "GM", reason: "Captive finance", rows: ["1", "3", "6"] },
  ],
};
const STORED: StuckCheckSettingsOut = {
  ...DEFAULTS,
  sbc_revenue_pct: 10,
  defaults: DEFAULTS,
  bounds: {
    sbc_revenue_pct: { min: 1, max: 50 },
    sbc_fcf_pct: { min: 5, max: 100 },
    cash_conversion_line: { min: 0.1, max: 1.5 },
    share_growth_pct: { min: 0.5, max: 10 },
    one_off_pct: { min: 30, max: 95 },
    sector_band_pp: { min: 0.5, max: 10 },
    smoothing_days: { min: 1, max: 20 },
  },
  row_options: [
    { key: "1", label: "Cash conversion" },
    { key: "2", label: "Stock-based compensation" },
    { key: "2_fcf", label: "SBC as % of free cash flow" },
    { key: "3", label: "FCF after stock-based compensation" },
    { key: "5", label: "Share count" },
    { key: "6", label: "Shareholder yield" },
  ],
  updated_at: "2026-10-09T09:00:00",
};

function serve(data: StuckCheckSettingsOut | undefined) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data, error: undefined, isLoading: false } as any);
}
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save" });
const type = (label: string, value: string) => fireEvent.change(field(label), { target: { value } });

beforeEach(() => {
  serve(STORED);
  mockedPut.mockResolvedValue(STORED);
  mockedPost.mockResolvedValue(STORED);
  mockedMutate.mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("StuckCheckSettingsForm", () => {
  it("renders the title, intro, the seven thresholds from the stored values and the seeded exemptions", () => {
    render(<StuckCheckSettingsForm />);
    expect(screen.getByRole("heading", { name: "Why might it be stuck?" })).toBeInTheDocument();
    expect(screen.getByText(/never changes a score, a verdict or the Screener/)).toBeInTheDocument();
    expect(field("SBC limit, % of revenue").value).toBe("10");
    expect(field("SBC limit, % of free cash flow").value).toBe("30");
    expect(field("Cash conversion line").value).toBe("0.7");
    expect(field("Time-stop smoothing").value).toBe("5");
    expect(field("Exemption 1 ticker").value).toBe("IBKR");
    expect(field("Exemption 2 reason").value).toBe("Captive finance");
    const first = screen.getByRole("group", { name: "Exemption 1" });
    expect((within(first).getByLabelText("SBC as % of free cash flow") as HTMLInputElement).checked).toBe(true);
    expect((within(first).getByLabelText("Share count") as HTMLInputElement).checked).toBe(true);
    expect((within(first).getByLabelText("Stock-based compensation") as HTMLInputElement).checked).toBe(false);
  });

  it("disables Save until something differs, then saves the typed values and the exemption list", async () => {
    render(<StuckCheckSettingsForm />);
    expect(save()).toBeDisabled();
    type("SBC limit, % of revenue", "12.5");
    expect(save()).toBeEnabled();
    fireEvent.click(save());
    await vi.waitFor(() => expect(mockedPut).toHaveBeenCalled());
    const [url, body] = mockedPut.mock.calls[0];
    expect(url).toBe("/config/stuck-check");
    expect(body).toMatchObject({ sbc_revenue_pct: 12.5, smoothing_days: 5, exemptions: DEFAULTS.exemptions });
    await vi.waitFor(() => expect(mockedMutate).toHaveBeenCalledWith("/config/stuck-check"));
  });

  it.each([
    ["SBC limit, % of revenue", "0"],
    ["SBC limit, % of revenue", "51"],
    ["SBC limit, % of free cash flow", "4"],
    ["Cash conversion line", "1.6"],
    ["One-off exception", "20"],
    ["In-line band", "11"],
    ["Time-stop smoothing", "2.5"],
    ["Time-stop smoothing", "21"],
    ["Share count growth per year", "abc"],
  ])("blocks Save for %s = %s, with an inline error, and clamps nothing", (label, value) => {
    render(<StuckCheckSettingsForm />);
    type(label, value);
    expect(save()).toBeDisabled();
    expect(field(label).value).toBe(value);
    expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
  });

  it("edits the exemption list: add, remove, row ticks, ticker upper-cased", async () => {
    render(<StuckCheckSettingsForm />);
    fireEvent.click(screen.getByRole("button", { name: "Remove GM" }));
    fireEvent.click(screen.getByRole("button", { name: "Add exempt ticker" }));
    expect(save()).toBeDisabled(); // empty entry is invalid
    type("Exemption 2 ticker", " abc ");
    type("Exemption 2 reason", "Hand-checked");
    const entry = screen.getByRole("group", { name: "Exemption 2" });
    expect(screen.getAllByRole("alert").map((a) => a.textContent).join(" ")).toContain("Tick at least one row.");
    fireEvent.click(within(entry).getByLabelText("Share count"));
    expect(save()).toBeEnabled();
    fireEvent.click(save());
    await vi.waitFor(() => expect(mockedPut).toHaveBeenCalled());
    expect(mockedPut.mock.calls[0][1]).toMatchObject({
      exemptions: [DEFAULTS.exemptions[0], { ticker: "ABC", reason: "Hand-checked", rows: ["5"] }],
    });
  });

  it("rejects a bad or duplicate ticker and a missing reason", () => {
    render(<StuckCheckSettingsForm />);
    type("Exemption 2 ticker", "ibkr");
    expect(screen.getByText("This ticker is already in the list.")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    type("Exemption 2 ticker", "bad ticker");
    expect(screen.getByText(/Enter a ticker such as IBKR/)).toBeInTheDocument();
    type("Exemption 2 ticker", "GM");
    type("Exemption 2 reason", "  ");
    expect(screen.getByText("Give a reason.")).toBeInTheDocument();
  });

  it("Reset to defaults posts the reset without a confirmation, and is disabled at the defaults", async () => {
    render(<StuckCheckSettingsForm />);
    const reset = screen.getByRole("button", { name: "Reset to defaults" });
    expect(reset).toBeEnabled();
    fireEvent.click(reset);
    await vi.waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/config/stuck-check/reset"));
    cleanup();
    serve({ ...STORED, sbc_revenue_pct: 8 });
    render(<StuckCheckSettingsForm />);
    expect(screen.getByRole("button", { name: "Reset to defaults" })).toBeDisabled();
  });

  it("shows the server's reason when a save is rejected", async () => {
    mockedPut.mockRejectedValue(new Error("PUT /config/stuck-check failed: 422 - A ticker is listed twice in the exemption list."));
    render(<StuckCheckSettingsForm />);
    type("SBC limit, % of revenue", "11");
    fireEvent.click(save());
    expect(await screen.findByText(/Save failed: A ticker is listed twice/)).toBeInTheDocument();
  });

  it("shows loading and error states", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockedHook.mockReturnValue({ data: undefined, error: undefined, isLoading: true } as any);
    render(<StuckCheckSettingsForm />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    cleanup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockedHook.mockReturnValue({ data: undefined, error: new Error("boom"), isLoading: false } as any);
    render(<StuckCheckSettingsForm />);
    expect(screen.getByText(/Couldn't load these settings — boom/)).toBeInTheDocument();
  });
});
