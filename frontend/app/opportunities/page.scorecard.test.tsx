// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import OpportunitiesPage from "@/app/opportunities/page";
import type { ScorecardFlagsOut, ScorecardOut, ScorecardPicksOut, ScorecardValues } from "@/lib/api/types";
import { cell, group, out } from "@/lib/scorecardTestData";

// The page contains an admin control (Add to watchlist): render it as a signed-in admin, so "hidden on the Scorecard" is a real assertion.
vi.mock("@/lib/auth/AuthProvider", async () => (await import("@/lib/auth/adminAuthMock")).adminAuthModule());

const nav = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

afterEach(cleanup);

function values(over: Partial<ScorecardValues> = {}): ScorecardValues {
  return {
    median_excess: 0.0412, mean_excess: 0.0301, share_above: 0.62, cohorts_positive: 3, cohorts_counted: 4, benchmark_median_return: 0.0105,
    median_return: 0.052, stop_hit_rate: 0.1, stop_n: 30, median_with_stop_return: 0.04, median_with_stop_excess: 0.03, median_worst_move: -0.04,
    median_drawdown: -0.03, including_censored: { n: 32, median_excess: 0.02 }, ...over,
  };
}

function scorecard(): ScorecardOut {
  const quality = group("momentum:quality", { kind: "tier", tier: "quality" }, {
    n_complete: 32, n_pending: 5, cohorts: 4, cohorts_total: 4, state: "early", values: values(), mixed_weights: true, weights_versions: [8, 9],
    pool: { n_complete: 200, n_pending: 0, n_censored: 0, n_entry_gap: 0, n_no_benchmark: 0, cohorts: 4, cohorts_total: 4, state: "ok", values: values({ median_excess: 0.01 }) },
    listed_minus_pool: { median_excess: 0.0312, cohorts: 4 },
  });
  const okGroup = group("momentum", {}, { n_complete: 90, cohorts: 9, cohorts_total: 9, state: "ok", values: values({ median_excess: 0.02 }), n_censored: 2 });
  // the 10-session horizon of the same group has nothing complete yet
  okGroup.cells["10"] = { spy: cell({ n_pending: 90, cohorts_total: 9 }), sector: cell({ n_pending: 90, cohorts_total: 9 }) };
  return out({
    next_expected: { "5": "2026-10-26", "10": "2026-11-02" },
    groups: [
      okGroup,
      quality,
      group("momentum:momentum_only", { kind: "tier", tier: "momentum_only" }, { n_complete: 6, cohorts: 1, cohorts_total: 2, n_pending: 3 }),
      group("reversal", { list_name: "reversal" }, { n_complete: 23, cohorts: 1, cohorts_total: 2 }),
      group("reversal:momentum_only", { kind: "tier", list_name: "reversal", tier: "momentum_only" }, { n_complete: 5, cohorts: 1, cohorts_total: 1 }),
      group("reversal:leveraged", { kind: "leveraged", list_name: "reversal", tier: "etf" }, { n_complete: 1, cohorts: 1, cohorts_total: 1 }),
      group("rule:B2", { kind: "rule", list_name: null, rule: "B2", has_pool: false }, { n_complete: 10, cohorts: 1, cohorts_total: 2, n_entry_gap: 1 }),
    ],
  });
}

function flags(): ScorecardFlagsOut {
  const counts = { n_complete: 0, n_pending: 4, n_censored: 0, n_entry_gap: 0, n_no_benchmark: 0, n_unpriced: 1, cohorts: 0, cohorts_total: 1, state: "too_early" as const, values: null };
  const cells = Object.fromEntries(["5", "10", "20", "60"].map((h) => [h, { spy: { flagged: counts, unflagged: counts }, sector: { flagged: counts, unflagged: counts } }]));
  const trig = (t: "D1" | "D2" | "D3", over = {}) => ({
    trigger: t, eligible: 41, flagged: 9, not_covered: t === "D1" ? 18 : 0, incomplete: 0, unflagged: 14, cohorts: 2, cohorts_window_open: 1,
    flagged_in_open_cohorts: 5, comparator_provisional: true, per_cohort: [], cells, ...over,
  });
  return {
    has_data: true,
    versions: scorecard().versions,
    latest: scorecard().latest,
    thresholds: scorecard().thresholds,
    comparator_label: "Not a controlled comparison",
    pricing_note: "",
    excluded: { other_trigger_version_flags: 0, cohorts_other_weights_version: 0 },
    triggers: {
      D1: trig("D1"),
      D2: trig("D2"),
      D3: trig("D3", { split: { already_at_ma_on_list: { flagged: 19, cells }, not_at_ma_on_list: { flagged: 19, cells } } }),
    },
    any_flag: { flagged_names: 50, flagged_in_open_cohorts: 23, cells },
    ledger: [
      {
        flag_id: 1, ticker: "XLK", trigger: "D3", trigger_id: "D3.pullback_to_ma.v1", list_name: "momentum", tier: "etf", leveraged: false, list_as_of_date: "2026-10-16",
        flag_date: "2026-10-19", window_open: true, already_at_ma_on_list: true,
        horizons: { "5": null, "10": null, "20": null, "60": null },
      },
      {
        flag_id: 2, ticker: "AMAT", trigger: "D1", trigger_id: "D1.entry_event.v1", list_name: "reversal", tier: "momentum_only", leveraged: false, list_as_of_date: "2026-10-09",
        flag_date: "2026-10-13", window_open: false, already_at_ma_on_list: null,
        horizons: {
          "5": { status: "complete", forward_return: 0.052, excess_vs_spy: 0.0412, excess_vs_sector: 0.03, stop_hit: true, stop_fill_return: -0.1, with_stop_return: -0.1, entry_gap_flag: false },
          "10": null, "20": null, "60": null,
        },
      },
    ],
  };
}

const PICKS_EMPTY: ScorecardPicksOut = { label: "Priced from the list date, not your add date", count: 0, empty: true, cohorts: 0, unmatched: 0, message: "No picks yet.", cells: null };

let requested: string[] = [];
let picks: ScorecardPicksOut = PICKS_EMPTY;

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      requested.push(`${init?.method ?? "GET"} ${url}`);
      const path = new URL(url, "http://localhost").pathname;
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (path.endsWith("/opportunities/scorecard")) return json(scorecard());
      if (path.endsWith("/opportunities/scorecard/flags")) return json(flags());
      if (path.endsWith("/opportunities/scorecard/picks")) return json(picks);
      if (path.endsWith("/opportunities/scorecard/outcomes")) return json({ source: "listed", total: 1, offset: 0, limit: 20000, truncated: false, rows: [{ source: "listed", cohort: "2026-10-09", weights_version: 8, ticker: "AAA", list_name: "momentum", tier: "quality", horizon: 5, status: "complete", censor_reason: null, bucket: "complete" }] });
      if (path.endsWith("/opportunities/dates")) return json([{ as_of_date: "2026-10-16", kind: "weekly", created_at: "2026-10-17T04:00:00", momentum_count: 1, reversal_count: 0 }]);
      if (path.endsWith("/opportunities/latest")) return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
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

async function onScorecard() {
  nav.search = "view=scorecard";
  renderPage();
  await waitFor(() => expect(screen.getByRole("table", { name: "Scorecard" })).toBeInTheDocument());
}

const table = () => within(screen.getByRole("table", { name: "Scorecard" }));
const row = (key: string) => within(screen.getByTestId(`group-${key}`));

beforeEach(() => {
  requested = [];
  picks = PICKS_EMPTY;
  nav.search = "";
  window.history.replaceState(null, "", "/opportunities");
  mockFetch();
});

describe("Scorecard tab", () => {
  it("opens from ?view=scorecard, fetches only scorecard data and hides the list-only controls (hidden, not disabled)", async () => {
    await onScorecard();
    expect(screen.getByRole("tab", { name: "Scorecard" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("combobox", { name: "Snapshot date" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Export \d+ (shown|selected)/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add .*to watchlist/ })).not.toBeInTheDocument();
    expect(requested.some((r) => r.includes("/opportunities/latest") || r.includes("/opportunities/dates"))).toBe(false);
    expect(requested.some((r) => r.includes("/opportunities/scorecard"))).toBe(true);
  });

  it("switches between Lists and Scorecard and keeps ?view= in the URL", async () => {
    renderPage();
    expect(screen.getByRole("tab", { name: "Lists" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Snapshot date" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Scorecard" }));
    await waitFor(() => expect(screen.getByRole("table", { name: "Scorecard" })).toBeInTheDocument());
    expect(window.location.search).toBe("?view=scorecard");
    expect(screen.queryByRole("combobox", { name: "Snapshot date" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Lists" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Snapshot date" })).toBeInTheDocument());
    expect(window.location.search).toBe("");
    expect(screen.queryByRole("table", { name: "Scorecard" })).not.toBeInTheDocument();
  });

  it("does not request the scorecard while on the Lists tab", async () => {
    renderPage();
    await waitFor(() => expect(requested.some((r) => r.includes("/opportunities/latest"))).toBe(true));
    expect(requested.some((r) => r.includes("/opportunities/scorecard"))).toBe(false);
  });
});

describe("early state and gated cells", () => {
  it("shows the early-data banner with its dates from the response", async () => {
    await onScorecard();
    // at 5 sessions one list cell already has the cohorts for a full read, so there is nothing early left to say
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Horizon" })).getByRole("button", { name: "10" }));
    const banner = await screen.findByRole("note");
    expect(banner).toHaveTextContent("0 of 2 weekly lists have complete 10-session results");
    expect(banner).toHaveTextContent("prices through 2026-10-19");
    expect(banner).toHaveTextContent("2026-11-02 bar");
    expect(banner).toHaveTextContent("at least 20 complete rows from at least 3 weekly lists");
  });

  it("draws a cell below the gate with counts, dashes and a Too early pill, and no red or green", async () => {
    await onScorecard();
    const r = row("reversal");
    expect(r.getByText("Too early")).toBeInTheDocument();
    expect(r.getByText("23")).toBeInTheDocument();
    expect(screen.getByTestId("group-reversal").textContent).not.toMatch(/%/);
    expect(screen.getByTestId("group-reversal").innerHTML).not.toMatch(/text-positive|text-negative/);
    expect(row("reversal").getAllByText("—").length).toBeGreaterThanOrEqual(10);
  });

  it("labels a cell above the gate Early and keeps its figures neutral; a cell past Early is coloured", async () => {
    await onScorecard();
    const early = row("momentum:quality");
    expect(early.getByText("Early")).toBeInTheDocument();
    expect(early.getByText("+4.12%")).toBeInTheDocument();
    expect(screen.getByTestId("group-momentum:quality").innerHTML).not.toMatch(/text-positive|text-negative/);
    const ok = within(screen.getByTestId("group-momentum"));
    expect(ok.getByText("+2.00%").className).toMatch(/text-positive/);
    expect(ok.queryByText("Early")).not.toBeInTheDocument();
    expect(ok.queryByText("Too early")).not.toBeInTheDocument();
  });

  it("shows n with pending / censored / entry-gap counts on the cell", async () => {
    await onScorecard();
    expect(row("momentum").getByText("2 censored")).toBeInTheDocument();
    expect(row("momentum:quality").getByText("5 pending")).toBeInTheDocument();
    expect(row("rule:B2").getByText("1 entry gap")).toBeInTheDocument();
    expect(row("momentum").getByText(/incl\. censored \+2\.00%/)).toBeInTheDocument();
  });

  it("notes mixed weights versions on the Quality cell only", async () => {
    await onScorecard();
    expect(row("momentum:quality").getByText("Mixed weights")).toHaveAttribute("title", expect.stringContaining("v8, v9"));
    expect(row("momentum").queryByText("Mixed weights")).not.toBeInTheDocument();
  });

  it("follows the tab wording for tiers and gives leveraged funds their own row and rule cuts their own caveat", async () => {
    await onScorecard();
    expect(row("reversal:momentum_only").getByText("Technical only")).toBeInTheDocument();
    expect(row("momentum:momentum_only").getByText("Momentum-only")).toBeInTheDocument();
    expect(row("reversal:leveraged").getByText("Leveraged ETFs")).toBeInTheDocument();
    expect(table().getByText(/never added together/)).toBeInTheDocument();
    expect(row("rule:B2").getByText("B2 · Price structure")).toBeInTheDocument();
  });

  it("shows the pool baseline and listed minus pool once the cell is past the gate", async () => {
    await onScorecard();
    const q = row("momentum:quality");
    expect(q.getByText("+1.00%")).toBeInTheDocument();
    expect(q.getByText("+3.12%")).toBeInTheDocument();
  });
});

describe("controls", () => {
  it("switches the horizon: the same group shows its 10-session cell", async () => {
    await onScorecard();
    expect(row("momentum").getByText("90")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Horizon" })).getByRole("button", { name: "10" }));
    await waitFor(() => expect(row("momentum").getByText("90 pending")).toBeInTheDocument());
    expect(row("momentum").getByText("Too early")).toBeInTheDocument();
  });

  it("offers SPY and Sector ETF benchmarks", async () => {
    await onScorecard();
    const bench = within(screen.getByRole("group", { name: "Benchmark" }));
    expect(bench.getByRole("button", { name: "SPY" })).toBeInTheDocument();
    fireEvent.click(bench.getByRole("button", { name: "Sector ETF" }));
    await waitFor(() => expect(bench.getByRole("button", { name: "Sector ETF" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("asks the server for one weights version when it is picked (default: all)", async () => {
    await onScorecard();
    const select = screen.getByRole("combobox", { name: "Weights version" });
    expect(select).toHaveValue("all");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["All", "v8", "v9"]);
    fireEvent.change(select, { target: { value: "8" } });
    await waitFor(() => expect(requested.some((r) => r.includes("/opportunities/scorecard?") && r.includes("weights_version=8"))).toBe(true));
    expect(requested.filter((r) => r.includes("/opportunities/scorecard") && !r.includes("flags") && !r.includes("picks"))[0]).not.toContain("weights_version");
  });

  it("exports the table and the row-level outcomes as CSV files", async () => {
    const create = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
    await onScorecard();
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(create).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Export outcomes CSV" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(requested.some((r) => r.includes("/opportunities/scorecard/outcomes"))).toBe(true);
  });
});

describe("flags and picks", () => {
  it("shows trigger-level counts, the D3 split and a ledger with no averages", async () => {
    await onScorecard();
    await waitFor(() => expect(screen.getByRole("table", { name: "Flag counts" })).toBeInTheDocument());
    const counts = within(screen.getByRole("table", { name: "Flag counts" }));
    const d1 = within(screen.getByTestId("trigger-D1"));
    expect(d1.getByText("D1 · Entry event")).toBeInTheDocument();
    expect(d1.getByText("18")).toBeInTheDocument(); // not covered
    expect(counts.getByText("Already within 5% of the MA on the list date")).toBeInTheDocument();
    expect(counts.getByText("Any flag (first per name)")).toBeInTheDocument();
    expect(screen.getByText("Not a controlled comparison.")).toBeInTheDocument();

    const ledger = within(screen.getByRole("table", { name: "Flag ledger" }));
    expect(ledger.getByText("XLK")).toBeInTheDocument();
    expect(ledger.getByText("Window open")).toBeInTheDocument();
    expect(ledger.getByText("+5.20%")).toBeInTheDocument();
    expect(ledger.getByText("+4.12%")).toBeInTheDocument();
    expect(ledger.getByText("Stopped -10.0%")).toBeInTheDocument();
    expect(ledger.getByText("Technical only", { exact: false })).toBeInTheDocument();
  });

  it("draws a one-line empty state for picks", async () => {
    await onScorecard();
    await waitFor(() => expect(screen.getByText(/No picks yet/)).toBeInTheDocument());
  });

  it("labels picks as priced from the list date when there are some", async () => {
    picks = { ...PICKS_EMPTY, empty: false, count: 2, cohorts: 1, cells: null, message: null };
    await onScorecard();
    await waitFor(() => expect(screen.getByText(/2 picks across 1 weekly list/)).toBeInTheDocument());
    expect(screen.getByText(/Priced from the list date, not your add date/)).toBeInTheDocument();
  });
});

describe("wording", () => {
  it("carries the informational and price-only footnotes and none of the banned wording", async () => {
    await onScorecard();
    expect(screen.getByText(/Informational only/)).toBeInTheDocument();
    expect(screen.getByText(/Returns are price-only: dividends are not included/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("table", { name: "Flag ledger" })).toBeInTheDocument());
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/beats? the market|\bworks\b|p-value|\balpha\b|annuali[sz]ed|\bbest\b/i);
  });

  it("uses at most one accent-filled button", async () => {
    const { container } = renderPage();
    nav.search = "";
    fireEvent.click(screen.getByRole("tab", { name: "Scorecard" }));
    await waitFor(() => expect(screen.getByRole("table", { name: "Scorecard" })).toBeInTheDocument());
    expect(container.querySelectorAll("button.bg-brand").length).toBeLessThanOrEqual(1);
  });
});

describe("empty database", () => {
  it("says so in one line and still draws the table", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = new URL(url, "http://localhost").pathname;
        if (path.endsWith("/scorecard")) return new Response(JSON.stringify(out({ has_data: false, cohorts: [], groups: [group("momentum")], next_expected: {} })), { status: 200 });
        if (path.endsWith("/flags")) return new Response(JSON.stringify({ ...flags(), has_data: false, ledger: [] }), { status: 200 });
        if (path.endsWith("/picks")) return new Response(JSON.stringify(PICKS_EMPTY), { status: 200 });
        return new Response("{}", { status: 404 });
      }),
    );
    await onScorecard();
    expect(screen.getByText(/No outcomes yet/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
