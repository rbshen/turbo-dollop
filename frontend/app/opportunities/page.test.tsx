// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import OpportunitiesPage from "@/app/opportunities/page";
import type { OpportunityDateOut, OpportunityRowOut, OpportunityRunOut } from "@/lib/api/types";

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
    row({ ticker: "REVM", company_name: "Reversal M", list_name: "reversal", tier: "momentum_only", overall_verdict: "Fail", overall_score: 40, rule_ids: ["B2.price_structure.v1"] }),
  ],
};

const OLD: OpportunityRunOut = { ...RUN, id: 1, as_of_date: "2026-10-02", momentum: [row({ ticker: "OLDY", company_name: "Old Co" })], reversal: [] };

const DATES: OpportunityDateOut[] = [
  { as_of_date: "2026-10-09", kind: "weekly", created_at: "2026-10-10T04:00:00", momentum_count: 4, reversal_count: 2 },
  { as_of_date: "2026-10-02", kind: "weekly", created_at: "2026-10-03T04:00:00", momentum_count: 1, reversal_count: 0 },
];

let requested: string[] = [];

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
      if (path.endsWith("/watchlists")) return new Response("[]", { status: 200 });
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
    expect(screen.getByRole("heading", { level: 1, name: "Opportunities" })).toBeInTheDocument();
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

  it("has the export menu with TradingView and thinkorswim, and a manual Add to watchlist button", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: /Export list/ }));
    expect(screen.getByRole("menuitem", { name: "TradingView (.txt)" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "thinkorswim (.csv)" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /multiple/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeEnabled();
  });

  it("exports the visible rows as a TradingView list grouped by sector", async () => {
    await loaded();
    const created: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => (created.push(b), "blob:x"), revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: /Export list/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "TradingView (.txt)" }));
    expect(created).toHaveLength(1);
    const text = await created[0].text();
    expect(text).toContain("###Technology");
    expect(text).toContain("NASDAQ:QUAL");
    expect(text).toContain("###Other"); // the ETF has no sector
    click.mockRestore();
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
