// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import OpportunitiesPage from "@/app/opportunities/page";
import type { OpportunityDateOut, OpportunityRowOut, OpportunityRunOut } from "@/lib/api/types";
import { setMockRole } from "@/lib/auth/adminAuthMock";

// The component under test contains an admin control: render it as a signed-in admin (roles have their own tests).
vi.mock("@/lib/auth/AuthProvider", async () => (await import("@/lib/auth/adminAuthMock")).adminAuthModule());

afterEach(cleanup);

function row(over: Partial<OpportunityRowOut>): OpportunityRowOut {
  return {
    ticker: "AAA",
    company_name: "AAA Inc",
    list_name: "momentum",
    tier: "quality",
    list_order: 1,
    rule_ids: ["A.momentum_trend.v1"],
    tags: {},
    overall_score: 80,
    steps_score: 80,
    overall_verdict: "Pass",
    weinstein_stage: "advance",
    vs_ma_pct: 7.5,
    ma_slope_pct: 1,
    mansfield_rs: 2,
    momentum_rank: 12,
    close: 100,
    atr: 2,
    adv_usd: 123_000_000,
    sector: "Technology",
    exchange: "NASDAQ",
    weeks_in_advance: 20,
    inputs: { momentum_group: "stocks", momentum_group_size: 569 },
    ...over,
  };
}

const RUN: OpportunityRunOut = {
  id: 2,
  kind: "weekly",
  as_of_date: "2026-10-09",
  last_bar_date: "2026-10-09",
  universe_size: 608,
  rules_hash: "abcdef0123456789",
  rules_version: "1",
  score_formula_version: 6,
  weights_version: 2,
  created_at: "2026-10-10T04:00:00",
  summary: {
    list_totals: { momentum: 4, reversal: 2 },
    ranked_universe: { stocks: 569, etfs: 23, leveraged_etfs: 3 },
    gate_passed: 595,
    quality_not_covered: 50,
    quality_total: 118,
    stale_score_rows: 0,
    market: {
      breadth: { as_of_date: "2026-10-09", pct_above_sma50: 35.1, pct_above_sma200: 47.7, net_new_highs: 10 },
      sectors_in_advance: 4,
      sector_etfs: Object.fromEntries(["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"].map((e) => [e, { etf: e, stage: null, vs_ma_pct: null, momentum_rank: null, momentum_group_size: null, breadth: null }])),
    },
  },
  rule_labels: { "A.momentum_trend.v1": "Momentum trend", "B2.price_structure.v1": "Price structure", "B1.base_or_pending_advance.v1": "Base or pending advance" },
  momentum: [
    row({ ticker: "QUAL", company_name: "Quality Co", list_order: 1, tags: { late_trend: true } , weeks_in_advance: 60 }),
    row({
      ticker: "MOMO",
      company_name: "Momo Corp",
      tier: "momentum_only",
      list_order: 2,
      overall_verdict: "Fail",
      overall_score: 55,
      momentum_rank: 3,
      tags: { why_not_quality: { overall_verdict: "Fail", failed_steps: ["Debt"], incomplete_steps: [], moat: null }, deep_pullback: true },
    }),
    row({ ticker: "WARY", company_name: "Wary Co", tier: "momentum_only", list_order: 3, overall_verdict: "Pass with caution", overall_score: 75 }),
    row({ ticker: "SOXL", company_name: "Bull 3X ETF", tier: "etf", list_order: 4, overall_verdict: null, overall_score: null, sector: null, tags: { leveraged: 3 }, inputs: { momentum_group: "leveraged_etfs", momentum_group_size: 3 } }),
  ],
  reversal: [
    row({ ticker: "REVQ", company_name: "Reversal Q", list_name: "reversal", rule_ids: ["B1.base_or_pending_advance.v1", "B2.price_structure.v1"], tags: { signal_status: "not_covered" }, weeks_in_advance: null }),
    row({ ticker: "REVM", company_name: "Reversal M", list_name: "reversal", tier: "momentum_only", overall_verdict: "Fail", overall_score: 40, rule_ids: ["B2.price_structure.v1"], tags: { why_not_quality: { overall_verdict: "Fail", failed_steps: ["Debt"], incomplete_steps: [], moat: "no_moat" } } }),
  ],
};

const OLD: OpportunityRunOut = { ...RUN, id: 1, as_of_date: "2026-10-02", momentum: [row({ ticker: "OLDY", company_name: "Old Co" })], reversal: [] };

const DATES: OpportunityDateOut[] = [
  { as_of_date: "2026-10-09", kind: "weekly", created_at: "2026-10-10T04:00:00", momentum_count: 4, reversal_count: 2 },
  { as_of_date: "2026-10-02", kind: "weekly", created_at: "2026-10-03T04:00:00", momentum_count: 1, reversal_count: 0 },
];

let requested: string[] = [];
let posted: Record<string, unknown>[] = [];
const WATCHLISTS = [{ id: 1, name: "Picks", sort_field: "ticker", sort_direction: "asc", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", tickers: [] }];

function mockFetch(opts: { dates?: OpportunityDateOut[]; run?: OpportunityRunOut | null } = {}) {
  const dates = opts.dates ?? DATES;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      requested.push(`${init?.method ?? "GET"} ${url}`);
      const path = new URL(url, "http://localhost").pathname;
      if (path.endsWith("/opportunities/dates")) return new Response(JSON.stringify(dates), { status: 200 });
      if (path.endsWith("/opportunities/latest")) {
        const run = opts.run === undefined ? RUN : opts.run;
        return run ? new Response(JSON.stringify(run), { status: 200 }) : new Response(JSON.stringify({ detail: "none" }), { status: 404 });
      }
      if (path.endsWith("/opportunities/2026-10-02")) return new Response(JSON.stringify(OLD), { status: 200 });
      if (path.endsWith("/watchlists/1/tickers/bulk")) {
        posted.push(JSON.parse(String(init?.body)));
        return new Response(JSON.stringify({ added: 4, already_present: 0 }), { status: 200 });
      }
      if (path.endsWith("/watchlists/1/tickers")) {
        posted.push(JSON.parse(String(init?.body)));
        return new Response(JSON.stringify({ ticker: "OLDY", added_at: "2026-10-12T00:00:00" }), { status: 201 });
      }
      if (path.endsWith("/watchlists")) return new Response(JSON.stringify(WATCHLISTS), { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
}

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <OpportunitiesPage />
    </SWRConfig>,
  );
}

beforeEach(() => {
  requested = [];
  posted = [];
  mockFetch();
});

async function loaded() {
  renderPage();
  await waitFor(() => expect(screen.getByText("QUAL")).toBeInTheDocument());
}

const body = () => within(screen.getByRole("table"));

describe("OpportunitiesPage", () => {
  it("shows a pulsing skeleton before data arrives and the page title", () => {
    const { container } = renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Weekly Routine" })).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the snapshot date picker, the market strip, both tabs with counts and the segmented control", async () => {
    await loaded();
    const picker = screen.getByRole("combobox", { name: "Snapshot date" });
    expect(picker).toHaveValue("2026-10-09");
    expect(within(picker).getAllByRole("option").map((o) => o.textContent)).toEqual(["2026-10-09", "2026-10-02"]);

    const strip = within(screen.getByRole("region", { name: "Market context" }));
    expect(strip.getByText("35.1%")).toBeInTheDocument();
    expect(strip.getByText("47.7%")).toBeInTheDocument();
    expect(strip.getByText("+10")).toBeInTheDocument();
    expect(strip.getByText("4 of 11")).toBeInTheDocument();

    expect(screen.getByRole("tab", { name: /Momentum\s*4/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Reversal\s*2/ })).toBeInTheDocument();
    const tier = within(screen.getByRole("group", { name: "Tier" }));
    for (const label of ["All", "Quality", "Momentum-only", "ETF"]) expect(tier.getByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
  });

  it("draws the Momentum columns, with 'Weeks in Advance' and no 'Rule'", async () => {
    await loaded();
    for (const name of ["Ticker", "Tier", "Verdict", "vs MA", "Rank", "Weeks in Advance", "ADV $M", "Tags"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("columnheader", { name: "Rule" })).not.toBeInTheDocument();
    expect(body().getAllByText("123").length).toBe(4);
  });

  it("draws verdicts in display wording: 'May not pass' for a stored Fail, never 'Fail'", async () => {
    await loaded();
    expect(body().getByText("May not pass")).toBeInTheDocument();
    expect(body().getByText("Pass with caution")).toBeInTheDocument();
    expect(body().getAllByText("Pass").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/\bFail\b/);
  });

  it("uses the tinted pill tones: Pass green, Pass with caution amber, May not pass slate", async () => {
    await loaded();
    expect(body().getAllByText("Pass")[0].className).toMatch(/text-positive/);
    expect(body().getByText("Pass with caution").className).toMatch(/text-caution/);
    expect(body().getByText("May not pass").className).toMatch(/text-not-pass/);
  });

  it("segments the list by tier and updates the counts", async () => {
    await loaded();
    fireEvent.click(within(screen.getByRole("group", { name: "Tier" })).getByRole("button", { name: /^Momentum-only/ }));
    await waitFor(() => expect(screen.queryByText("QUAL")).not.toBeInTheDocument());
    expect(screen.getByText("MOMO")).toBeInTheDocument();
    expect(screen.getByText("WARY")).toBeInTheDocument();
    expect(screen.queryByText("SOXL")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Momentum\s*2/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Reversal\s*1/ })).toBeInTheDocument();
  });

  it("shows the Reversal tab with the rule that fired in place of Weeks in Advance", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    await waitFor(() => expect(screen.getByText("REVQ")).toBeInTheDocument());
    expect(screen.getByRole("columnheader", { name: "Rule" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Weeks in Advance" })).not.toBeInTheDocument();
    expect(body().getAllByText("Price structure").length).toBe(2);
    expect(body().getByText("Base or pending advance")).toBeInTheDocument();
    expect(body().getByText("Signals not covered")).toBeInTheDocument();
  });

  it("labels the second tier 'Momentum-only' on the Momentum tab and 'Technical only' on the Reversal tab (display only)", async () => {
    await loaded();
    const tier = () => within(screen.getByRole("group", { name: "Tier" }));
    expect(tier().getByRole("button", { name: /^Momentum-only/ })).toBeInTheDocument();
    expect(tier().queryByRole("button", { name: /Technical only/ })).not.toBeInTheDocument();
    expect(body().getAllByText("Momentum-only").length).toBe(2); // MOMO and WARY pills
    expect(body().queryByText("Technical only")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    await waitFor(() => expect(screen.getByText("REVM")).toBeInTheDocument());
    expect(tier().getByRole("button", { name: /^Technical only/ })).toBeInTheDocument();
    expect(tier().queryByRole("button", { name: /Momentum-only/ })).not.toBeInTheDocument();
    expect(body().getByText("Technical only")).toBeInTheDocument();
    expect(body().queryByText("Momentum-only")).not.toBeInTheDocument();
    expect(body().getByText("Fundamentals not passed: Debt")).toBeInTheDocument();
    expect(body().queryByText(/Not quality/)).not.toBeInTheDocument();

    // the Technical only segment filters on the stored tier
    fireEvent.click(tier().getByRole("button", { name: /^Technical only/ }));
    await waitFor(() => expect(screen.queryByText("REVQ")).not.toBeInTheDocument());
    expect(screen.getByText("REVM")).toBeInTheDocument();

    // and back on the Momentum tab the old wording returns
    fireEvent.click(screen.getByRole("tab", { name: /Momentum/ }));
    await waitFor(() => expect(screen.getByText("MOMO")).toBeInTheDocument());
    expect(tier().getByRole("button", { name: /^Momentum-only/ })).toBeInTheDocument();
    expect(body().getByText("Not quality: Debt")).toBeInTheDocument();
  });

  it("shows tags as pills, including why-not-quality and the leveraged tag", async () => {
    await loaded();
    expect(body().getByText("Late trend")).toBeInTheDocument();
    expect(body().getByText("Not quality: Debt")).toBeInTheDocument();
    expect(body().getByText("Deep pullback")).toBeInTheDocument();
    expect(body().queryByText(/Also on/)).not.toBeInTheDocument();
    expect(body().getByText("3x leveraged")).toBeInTheDocument();
  });

  it("opens the ticker page in a new tab: the ticker is a real link and the whole row opens it too", async () => {
    await loaded();
    const link = screen.getByRole("link", { name: "QUAL" });
    expect(link).toHaveAttribute("href", "/tickers/QUAL");
    expect(link).toHaveAttribute("target", "_blank");
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    fireEvent.click(link); // a click on the anchor is left to the browser: no second tab
    expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Quality Co"));
    expect(open).toHaveBeenCalledWith("/tickers/QUAL", "_blank", "noopener,noreferrer");
    open.mockRestore();
  });

  it("switches the snapshot by date", async () => {
    await loaded();
    fireEvent.change(screen.getByRole("combobox", { name: "Snapshot date" }), { target: { value: "2026-10-02" } });
    await waitFor(() => expect(screen.getByText("OLDY")).toBeInTheDocument());
    expect(requested.some((r) => r.endsWith("/opportunities/2026-10-02"))).toBe(true);
  });

  it("has the export menu with TradingView and thinkorswim, and a manual Add to watchlist button that stay enabled", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Export 4 shown" }));
    expect(screen.getByRole("menuitem", { name: "TradingView (.txt)" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "thinkorswim (.csv)" })).toBeEnabled();
    expect(screen.queryByRole("menuitem", { name: /multiple/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeEnabled(); // nothing selected: still enabled, it answers on use
  });

  it("a viewer gets the export menu but no Add to watchlist button (adding picks is an admin write)", async () => {
    setMockRole("viewer");
    try {
      await loaded();
      expect(screen.getByRole("button", { name: "Export 4 shown" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Add .*to watchlist/ })).toBeNull();
    } finally {
      setMockRole("admin");
    }
  });

  // --- selection --------------------------------------------------------------------------------------------------------------

  const box = (ticker: string) => screen.getByRole("checkbox", { name: `Select ${ticker}` }) as HTMLInputElement;
  const header = () => screen.getByRole("checkbox", { name: "Select all shown" }) as HTMLInputElement;
  const tierButton = (name: RegExp) => within(screen.getByRole("group", { name: "Tier" })).getByRole("button", { name });
  const picked = (...tickers: string[]) => tickers.forEach((t) => fireEvent.click(box(t)));

  it("selects one row: a count line, the count in both buttons, a Clear action", async () => {
    await loaded();
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
    picked("MOMO");
    expect(box("MOMO")).toBeChecked();
    expect(box("QUAL")).not.toBeChecked();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add 1 to watchlist" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export 1 selected" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(box("MOMO")).not.toBeChecked();
    expect(screen.queryByText("1 selected")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeInTheDocument();
  });

  it("keeps a fixed-height status line so the selection line appearing moves nothing", async () => {
    await loaded();
    const line = screen.getByRole("status");
    expect(line).toHaveClass("h-8");
    picked("QUAL");
    expect(screen.getByRole("status")).toBe(line);
    expect(line).toHaveClass("h-8");
  });

  it("the header checkbox selects exactly the shown rows and shows an indeterminate state for a partial selection", async () => {
    await loaded();
    expect(header().checked).toBe(false);
    expect(header().indeterminate).toBe(false);
    picked("QUAL");
    expect(header().indeterminate).toBe(true);
    expect(header().checked).toBe(false);
    fireEvent.click(header());
    expect(["QUAL", "MOMO", "WARY", "SOXL"].every((t) => box(t).checked)).toBe(true);
    expect(header().checked).toBe(true);
    expect(header().indeterminate).toBe(false);
    expect(screen.getByText("4 selected")).toBeInTheDocument();
    fireEvent.click(header()); // all shown selected -> deselect the shown rows
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
    expect(header().checked).toBe(false);
  });

  it("select-all follows the tier filter: only the shown rows are selected, and others already selected stay", async () => {
    await loaded();
    fireEvent.click(tierButton(/^Momentum-only/));
    fireEvent.click(header());
    expect(screen.getByText("2 selected")).toBeInTheDocument(); // MOMO and WARY, not QUAL or SOXL
    fireEvent.click(tierButton(/^All/));
    expect(box("MOMO")).toBeChecked();
    expect(box("QUAL")).not.toBeChecked();
    expect(header().indeterminate).toBe(true);
  });

  it("shift-click selects the range of shown rows from the last one clicked", async () => {
    await loaded();
    picked("QUAL");
    fireEvent.click(box("WARY"), { shiftKey: true });
    expect(["QUAL", "MOMO", "WARY"].every((t) => box(t).checked)).toBe(true);
    expect(box("SOXL")).not.toBeChecked();
    fireEvent.click(box("QUAL"), { shiftKey: true }); // anchor is WARY; QUAL is selected, so the range turns off
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });

  it("space toggles the focused checkbox (the keyboard path is a native click)", async () => {
    await loaded();
    box("MOMO").focus();
    fireEvent.click(document.activeElement as HTMLElement); // a space press on a checkbox dispatches a click
    expect(box("MOMO")).toBeChecked();
    expect(box("MOMO")).toHaveAttribute("type", "checkbox");
  });

  it("keeps the selection across the tier filter and across the Momentum / Reversal tabs", async () => {
    await loaded();
    picked("QUAL");
    fireEvent.click(tierButton(/^Momentum-only/));
    expect(screen.queryByText("QUAL")).not.toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument(); // the hidden selection still counts
    fireEvent.click(tierButton(/^All/));
    expect(box("QUAL")).toBeChecked();

    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    picked("REVQ");
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Momentum/ }));
    expect(box("QUAL")).toBeChecked();
    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    expect(box("REVQ")).toBeChecked();
  });

  it("clears the selection when the snapshot date changes", async () => {
    await loaded();
    picked("QUAL", "MOMO");
    fireEvent.change(screen.getByRole("combobox", { name: "Snapshot date" }), { target: { value: "2026-10-02" } });
    await waitFor(() => expect(screen.getByText("OLDY")).toBeInTheDocument());
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
    expect(box("OLDY")).not.toBeChecked();
    fireEvent.change(screen.getByRole("combobox", { name: "Snapshot date" }), { target: { value: "2026-10-09" } });
    await waitFor(() => expect(screen.getByText("QUAL")).toBeInTheDocument());
    expect(box("QUAL")).not.toBeChecked();
  });

  it("a checkbox click neither opens the ticker nor counts as a row click; the row itself still does", async () => {
    await loaded();
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(box("QUAL"));
    fireEvent.click(box("QUAL").closest("td") as HTMLElement); // the padding around the box
    fireEvent.click(header());
    expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Quality Co"));
    expect(open).toHaveBeenCalledWith("/tickers/QUAL", "_blank", "noopener,noreferrer");
    open.mockRestore();
  });

  // --- Add to watchlist -------------------------------------------------------------------------------------------------------

  const openPicks = () => {
    fireEvent.click(screen.getByRole("button", { name: /^Add (\d+ )?to watchlist$/ }));
    return within(screen.getByText("Picks").parentElement as HTMLElement);
  };

  it("with nothing selected, Add to watchlist does nothing but say so inline (no menu, no request, still enabled)", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    expect(screen.getByText("Select at least one ticker")).toBeInTheDocument();
    expect(screen.queryByText("Picks")).not.toBeInTheDocument();
    expect(posted).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeEnabled();
    picked("QUAL"); // the message goes away once something is selected
    expect(screen.queryByText("Select at least one ticker")).not.toBeInTheDocument();
  });

  it("adds only the selected tickers, with the id of the run shown, and clears the selection after", async () => {
    await loaded();
    picked("MOMO", "SOXL");
    fireEvent.click(openPicks().getByRole("button", { name: "Add" }));
    fireEvent.click(await screen.findByRole("button", { name: "Okay" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ tickers: ["MOMO", "SOXL"], opportunity_run_id: 2 });
    await waitFor(() => expect(screen.queryByText("2 selected")).not.toBeInTheDocument());
    expect(box("MOMO")).not.toBeChecked();
    expect(screen.getByText(/Added 4 to “Picks”/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeInTheDocument();
  });

  it("a selection that spans both tabs is added together, in the run's order", async () => {
    await loaded();
    picked("WARY");
    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    picked("REVM");
    expect(screen.getByRole("button", { name: "Add 2 to watchlist" })).toBeInTheDocument();
    fireEvent.click(openPicks().getByRole("button", { name: "Add" }));
    fireEvent.click(await screen.findByRole("button", { name: "Okay" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ tickers: ["WARY", "REVM"], opportunity_run_id: 2 });
  });

  it("a single selected ticker is added with the single-add call and the run id", async () => {
    await loaded();
    picked("QUAL");
    fireEvent.click(openPicks().getByRole("button", { name: "Add" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ ticker: "QUAL", opportunity_run_id: 2 });
    await waitFor(() => expect(screen.getByText("Added QUAL to “Picks”")).toBeInTheDocument());
  });

  it("a past snapshot sends that run's id", async () => {
    await loaded();
    fireEvent.change(screen.getByRole("combobox", { name: "Snapshot date" }), { target: { value: "2026-10-02" } });
    await waitFor(() => expect(screen.getByText("OLDY")).toBeInTheDocument());
    picked("OLDY");
    fireEvent.click(openPicks().getByRole("button", { name: "Add" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ ticker: "OLDY", opportunity_run_id: 1 });
  });

  // --- Export -----------------------------------------------------------------------------------------------------------------

  function captureDownloads() {
    const files: { name: string; blob: Blob }[] = [];
    let last: Blob | null = null;
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => ((last = b), "blob:x"), revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      files.push({ name: this.download, blob: last as unknown as Blob });
    });
    return { files, restore: () => click.mockRestore() };
  }

  it("with nothing selected exports everything in the current view (tab plus tier), labelled with the count and named as a view", async () => {
    await loaded();
    const d = captureDownloads();
    fireEvent.click(screen.getByRole("button", { name: "Export 4 shown" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "TradingView (.txt)" }));
    expect(d.files).toHaveLength(1);
    expect(d.files[0].name).toBe("opportunities-momentum-view-2026-10-09.txt");
    const text = await d.files[0].blob.text();
    expect(text).toContain("###Technology");
    expect(text).toContain("NASDAQ:QUAL");
    expect(text).toContain("###Other"); // the ETF has no sector
    expect(text).not.toContain("REVQ"); // the Reversal list is not in a Momentum view
    d.restore();

    fireEvent.click(tierButton(/^Momentum-only/));
    expect(screen.getByRole("button", { name: "Export 2 shown" })).toBeInTheDocument();
  });

  it("with rows selected exports exactly those rows, named as a selection with the list and the date", async () => {
    await loaded();
    const d = captureDownloads();
    picked("MOMO", "WARY");
    fireEvent.click(screen.getByRole("button", { name: "Export 2 selected" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "thinkorswim (.csv)" }));
    expect(d.files[0].name).toBe("opportunities-momentum-selection-2026-10-09_thinkorswim.csv");
    expect(await d.files[0].blob.text()).toBe("MOMO\nWARY\n");
    d.restore();
  });

  it("a selection spanning both lists is exported together and the file name carries both lists", async () => {
    await loaded();
    const d = captureDownloads();
    picked("QUAL");
    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    picked("REVQ");
    fireEvent.click(screen.getByRole("button", { name: "Export 2 selected" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "thinkorswim (.csv)" }));
    expect(d.files[0].name).toBe("opportunities-momentum-reversal-selection-2026-10-09_thinkorswim.csv");
    expect(await d.files[0].blob.text()).toBe("QUAL\nREVQ\n");
    d.restore();
  });

  it("exporting a view with no rows (and no selection) says so instead of writing a file", async () => {
    await loaded();
    const d = captureDownloads();
    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    fireEvent.click(tierButton(/^ETF/));
    fireEvent.click(screen.getByRole("button", { name: "Export 0 shown" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "thinkorswim (.csv)" }));
    expect(d.files).toHaveLength(0);
    expect(screen.getByText("Nothing to export")).toBeInTheDocument();
    d.restore();
  });

  it("makes no write request: the page only GETs", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("tab", { name: /Reversal/ }));
    expect(requested.every((r) => r.startsWith("GET "))).toBe(true);
  });

  it("says so when no snapshot exists yet", async () => {
    mockFetch({ dates: [], run: null });
    renderPage();
    await waitFor(() => expect(screen.getByText(/No snapshot yet/)).toBeInTheDocument());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("states the ranked universe and the rules version in the footnote", async () => {
    await loaded();
    expect(screen.getByText(/569 stocks, 23 ETFs and 3 leveraged ETFs/)).toBeInTheDocument();
    expect(screen.getByText(/Rules v1 \(abcdef01\)/)).toBeInTheDocument();
    expect(screen.getByText(/50 of 118 Quality tickers are not on a monitored watchlist/)).toBeInTheDocument();
  });
});
