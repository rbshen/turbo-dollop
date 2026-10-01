// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BankCapitalMetricsForm } from "@/components/step5/BankCapitalMetricsForm";
import type { Step5Out, TickerBankCapitalMetricsOut } from "@/lib/api/types";

const apiPut = vi.fn();
const mutate = vi.fn();
let hook: { data?: TickerBankCapitalMetricsOut; error?: Error; isLoading?: boolean };

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));
vi.mock("swr", () => ({ mutate: (...args: unknown[]) => mutate(...args) }));
vi.mock("@/lib/hooks/useTickerBankCapitalMetrics", () => ({
  useTickerBankCapitalMetrics: () => hook,
}));

const EMPTY: TickerBankCapitalMetricsOut = {
  ticker: "JPM",
  cet1_ratio_pct: null,
  cet1_as_of: null,
  npl_ratio_pct: null,
  npl_as_of: null,
  updated_at: null,
};

const SAVED: TickerBankCapitalMetricsOut = {
  ticker: "JPM",
  cet1_ratio_pct: 12.5,
  cet1_as_of: "Q2 2026",
  npl_ratio_pct: 0.8,
  npl_as_of: "Q1 2026",
  updated_at: "2026-06-01T00:00:00",
};

function makeStep5(overrides: Record<string, unknown> = {}): Step5Out {
  return {
    ticker: "JPM",
    npl_source: null,
    npl_as_of: null,
    ratios: { npl_ratio: null },
    ...overrides,
  } as unknown as Step5Out;
}

beforeEach(() => {
  hook = { data: EMPTY };
  apiPut.mockReset().mockResolvedValue(SAVED);
  mutate.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

// The only place that knows how a field is found, so a markup change touches
// these four helpers and nothing else.
const cet1 = () => screen.getByLabelText(/^CET1 ratio/i) as HTMLInputElement;
const npl = () => screen.getByLabelText(/^NPL ratio/i) as HTMLInputElement;
const cet1AsOf = () => screen.getByLabelText("CET1 as of") as HTMLInputElement;
const nplAsOf = () => screen.getByLabelText("NPL as of") as HTMLInputElement;
const confirm = () => screen.getByRole("button", { name: /^(Confirm|Saving…)$/ });

describe("BankCapitalMetricsForm: states", () => {
  it("shows the load error", () => {
    hook = { error: new Error("boom") };
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    expect(screen.getByText(/Couldn't load CET1\/NPL inputs — boom/)).toBeInTheDocument();
  });

  it("shows Loading… until the data arrives", () => {
    hook = { isLoading: true };
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders empty fields with placeholders and no save panel when nothing is saved", () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    expect(cet1().value).toBe("");
    expect(cet1()).toHaveAttribute("placeholder", "Not yet entered");
    expect(npl().value).toBe("");
    expect(npl()).toHaveAttribute("placeholder", "Not available");
    expect(cet1AsOf().value).toBe("");
    expect(nplAsOf().value).toBe("");
    expect(cet1AsOf()).toHaveAttribute("placeholder", "e.g. Q2 2026");
    expect(screen.queryByText(/Save these CET1\/NPL values/)).not.toBeInTheDocument();
  });

  it("renders saved values", () => {
    hook = { data: SAVED };
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    expect(cet1().value).toBe("12.5");
    expect(cet1AsOf().value).toBe("Q2 2026");
    expect(npl().value).toBe("0.8");
    expect(nplAsOf().value).toBe("Q1 2026");
  });

  it("offers the auto-computed NPL as the placeholder and a helper line while the source is auto", () => {
    render(
      <BankCapitalMetricsForm
        ticker="JPM"
        step5={makeStep5({ npl_source: "auto", npl_as_of: "FY2025", ratios: { npl_ratio: { value: 1.2 } } })}
      />,
    );
    expect(npl()).toHaveAttribute("placeholder", "auto: +1.2%");
    expect(screen.getByText(/Auto-computed: \+1\.2% \(as of FY2025\)/)).toBeInTheDocument();
  });

  it("shows no auto helper once a manual override is active", () => {
    hook = { data: SAVED };
    render(
      <BankCapitalMetricsForm
        ticker="JPM"
        step5={makeStep5({ npl_source: "manual", ratios: { npl_ratio: { value: 0.8 } } })}
      />,
    );
    expect(screen.queryByText(/Auto-computed/)).not.toBeInTheDocument();
  });
});

describe("BankCapitalMetricsForm: edit and save", () => {
  it("opens the confirm panel on an edit and Cancel puts the saved values back", () => {
    hook = { data: SAVED };
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "13" } });
    expect(screen.getByText(/Save these CET1\/NPL values\? This recomputes Debt and Overall Assessment for JPM\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/Save these CET1\/NPL values/)).not.toBeInTheDocument();
    expect(cet1().value).toBe("12.5");
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("closes the panel again when an edit is typed back to the saved value", () => {
    hook = { data: SAVED };
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "13" } });
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    expect(screen.queryByText(/Save these CET1\/NPL values/)).not.toBeInTheDocument();
  });

  it("PUTs the numbers (not strings) and the as-of text, then refreshes this ticker's data and the Screener", async () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    fireEvent.change(cet1AsOf(), { target: { value: "Q2 2026" } });
    fireEvent.change(npl(), { target: { value: "0.8" } });
    fireEvent.change(nplAsOf(), { target: { value: "Q1 2026" } });
    fireEvent.click(confirm());
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut).toHaveBeenCalledWith("/tickers/JPM/bank-capital-metrics", {
      cet1_ratio_pct: 12.5,
      cet1_as_of: "Q2 2026",
      npl_ratio_pct: 0.8,
      npl_as_of: "Q1 2026",
    });
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
    const keyMatcher = mutate.mock.calls[0][0] as (key: unknown) => boolean;
    expect(keyMatcher("/tickers/JPM/step5")).toBe(true);
    expect(keyMatcher("/tickers/MSFT/step5")).toBe(false);
    expect(mutate.mock.calls[1][0]).toBe("/screener");
  });

  it("sends null for an empty number or as-of box, which clears a saved value", async () => {
    hook = { data: SAVED };
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "" } });
    fireEvent.change(nplAsOf(), { target: { value: "   " } });
    fireEvent.click(confirm());
    await waitFor(() => expect(apiPut).toHaveBeenCalled());
    expect(apiPut).toHaveBeenCalledWith("/tickers/JPM/bank-capital-metrics", {
      cet1_ratio_pct: null,
      cet1_as_of: "Q2 2026",
      npl_ratio_pct: 0.8,
      npl_as_of: null,
    });
  });

  it("disables Confirm and Cancel and says Saving… while the request is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    apiPut.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    fireEvent.click(confirm());
    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    resolve(SAVED);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Saving…" })).not.toBeInTheDocument());
  });

  it("shows a failure message when the save is rejected, and keeps the typed values", async () => {
    apiPut.mockRejectedValue(new Error("PUT x failed: 500"));
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    fireEvent.click(confirm());
    expect(await screen.findByText("Failed to save — please try again.")).toBeInTheDocument();
    expect(cet1().value).toBe("12.5");
    expect(confirm()).toBeEnabled();
  });
});

describe("BankCapitalMetricsForm: typed validation and the kit controls", () => {
  it("uses typed text fields, not native number inputs (no browser spinner or wheel change)", () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    for (const input of [cet1(), npl()]) {
      expect(input).toHaveAttribute("type", "text");
      expect(input).toHaveAttribute("inputmode", "decimal");
      expect(input).not.toHaveAttribute("step");
      expect(input).not.toHaveAttribute("min");
      expect(input).not.toHaveAttribute("max");
    }
  });

  it("labels every field visibly, in sentence case, and shows the % unit on the two ratios", () => {
    const { container } = render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    for (const name of ["CET1 ratio", "CET1 as of", "NPL ratio override", "NPL as of"]) {
      expect(screen.getByText(name, { selector: "label" })).toBeInTheDocument();
    }
    expect(screen.getByText("CET1 & NPL ratios")).toBeInTheDocument();
    expect(screen.getAllByText("%")).toHaveLength(2);
    expect(container.querySelector(".uppercase")).toBeNull();
    expect(container.innerHTML).not.toContain("outline-none");
  });

  it("explains the blank NPL as-of box with a hint linked to it", () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    const hint = screen.getByText("Leave blank to keep auto.");
    expect(nplAsOf().getAttribute("aria-describedby")).toContain(hint.id);
  });

  it("is a kit Card", () => {
    const { container } = render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    expect(container.firstElementChild).toHaveClass("rounded-lg", "border-border-card", "p-6");
  });

  it("draws Cancel as an outline Button", () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("border-border-input", "h-9");
  });

  it("blocks Save on non-numeric text with an inline error, and sends nothing", () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12x" } });
    const alert = screen.getByText("Enter a number.");
    expect(alert).toHaveAttribute("role", "alert");
    expect(cet1()).toHaveAttribute("aria-invalid", "true");
    expect(cet1().getAttribute("aria-describedby")).toContain(alert.id);
    expect(screen.getByText("Fix the highlighted fields to save.")).toBeInTheDocument();
    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("never leaves a sticky failure: fixing the text re-enables Save and clears the message", async () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(npl(), { target: { value: "abc" } });
    expect(screen.getByText("Enter a number.")).toBeInTheDocument();
    fireEvent.change(npl(), { target: { value: "0.8" } });
    expect(screen.queryByText("Enter a number.")).not.toBeInTheDocument();
    expect(confirm()).toBeEnabled();
    fireEvent.click(confirm());
    await waitFor(() =>
      expect(apiPut).toHaveBeenCalledWith("/tickers/JPM/bank-capital-metrics", {
        cet1_ratio_pct: null,
        cet1_as_of: null,
        npl_ratio_pct: 0.8,
        npl_as_of: null,
      }),
    );
  });

  it("does not clamp or correct what was typed (negative and large values are sent as typed)", async () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "-3.5" } });
    fireEvent.change(npl(), { target: { value: "250" } });
    expect(cet1().value).toBe("-3.5");
    fireEvent.click(confirm());
    await waitFor(() => expect(apiPut).toHaveBeenCalled());
    expect(apiPut.mock.calls[0][1]).toMatchObject({ cet1_ratio_pct: -3.5, npl_ratio_pct: 250 });
  });

  it("accepts a trailing dot and a leading dot, and trims spaces", async () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12." } });
    fireEvent.change(npl(), { target: { value: " .5 " } });
    expect(confirm()).toBeEnabled();
    fireEvent.click(confirm());
    await waitFor(() => expect(apiPut).toHaveBeenCalled());
    expect(apiPut.mock.calls[0][1]).toMatchObject({ cet1_ratio_pct: 12, npl_ratio_pct: 0.5 });
  });

  it("shows the server's own message when the save is rejected, and clears it on the next edit", async () => {
    apiPut.mockRejectedValue(new Error("PUT /tickers/JPM/bank-capital-metrics failed: 422 - cet1_ratio_pct: bad value"));
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    fireEvent.click(confirm());
    expect(await screen.findByText("Failed to save — cet1_ratio_pct: bad value")).toBeInTheDocument();
    fireEvent.change(cet1(), { target: { value: "12.6" } });
    expect(screen.queryByText(/Failed to save/)).not.toBeInTheDocument();
  });

  it("drops a stale failure message when the panel is cancelled", async () => {
    apiPut.mockRejectedValue(new Error("PUT x failed: 500"));
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    fireEvent.click(confirm());
    await screen.findByText("Failed to save — please try again.");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.change(cet1(), { target: { value: "13" } });
    expect(screen.queryByText(/Failed to save/)).not.toBeInTheDocument();
  });
});

describe("BankCapitalMetricsForm: the Confirm button", () => {
  it("is the one primary Button, in the warn fill, 36px like the outline Cancel beside it", () => {
    render(<BankCapitalMetricsForm ticker="JPM" step5={makeStep5()} />);
    fireEvent.change(cet1(), { target: { value: "12.5" } });
    expect(confirm()).toHaveClass("bg-warn", "text-on-brand", "px-4", "h-9", "text-sm"); // primary, with the warn fill winning over brand
    expect(confirm().className).not.toMatch(/border-warn|bg-warn\/15|bg-brand/);
    expect(confirm()).toHaveAttribute("type", "button");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("h-9", "border");
  });
});
