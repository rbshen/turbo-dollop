// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SavedFiltersBarView } from "@/components/screener/SavedFiltersBar";
import { Step5Card } from "@/components/step5/Step5Card";
import { EconomicMoatTab } from "@/components/ticker/EconomicMoatTab";
import { EtfHeader } from "@/components/ticker/EtfHeader";
import { FinancialsStatementTable } from "@/components/ticker/FinancialsStatementTable";
import { TickerHeader } from "@/components/ticker/TickerHeader";
import { RemoveCell } from "@/components/watchlist/tableParts";
import { WatchlistNameEditor } from "@/components/watchlist/WatchlistNameEditor";
import { TestAuth } from "@/lib/auth/testAuth";
import type { Step5Out, TickerMoatOut, TickerSummaryOut, WatchlistOut } from "@/lib/api/types";

// One sample of each control group the viewer must not get (docs/specs/auth.md, "Frontend"): drawn once as an admin, to show the
// control exists, and once as a viewer, to show it is gone. The hooks and the leaf components with their own tests are replaced.
vi.mock("swr", async (orig) => ({ ...(await orig<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => ({ data: hooks.moat }) }));
vi.mock("@/lib/hooks/useSpeculativeGrowth", () => ({ useSpeculativeGrowth: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTrendAnalysis", () => ({ useTrendAnalysis: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useEtfOverview", () => ({ useEtfOverview: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTickerScore", () => ({ useTickerScore: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useMoatConfig", () => ({ useMoatConfig: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useMoatCheck", () => ({ useMoatCheck: () => ({ data: null }) }));
vi.mock("@/lib/hooks/useTickerBankCapitalMetrics", () => ({ useTickerBankCapitalMetrics: () => ({ data: undefined }) }));
vi.mock("@/components/ticker/UniverseControl", () => ({
  useUniverseControl: () => ({ control: <button>Remove from Universe</button>, note: <p>universe note</p> }),
}));
vi.mock("@/components/ticker/AddToWatchlistButton", () => ({ AddToWatchlistButton: () => <button>Add to watchlist</button> }));
vi.mock("@/components/ticker/EtfWatchlistButton", () => ({ EtfWatchlistButton: () => <button>Add ETF to watchlist</button> }));
vi.mock("@/components/ticker/RefreshButton", () => ({ RefreshButton: () => <button>Refresh</button> }));
vi.mock("@/components/ticker/SecCellCheckButton", () => ({ SecCellCheckButton: () => <button>Check SEC</button> }));
vi.mock("@/components/step5/BankCapitalMetricsForm", () => ({ BankCapitalMetricsForm: () => <p>CET1 and NPL form</p> }));
vi.mock("@/components/ticker/MoatCheckBoundary", () => ({ MoatCheckBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/components/ticker/MoatCheckCard", () => ({ MoatCheckCard: () => null }));
vi.mock("@/lib/hooks/useStep5", () => ({ useStep5: () => ({ data: hooks.step5 }) }));

const hooks = vi.hoisted(() => ({ moat: undefined as unknown, step5: undefined as unknown }));
beforeEach(() => {
  hooks.moat = undefined;
  hooks.step5 = undefined;
});
afterEach(cleanup);

const asRole = (role: "admin" | "viewer", ui: ReactElement) => render(<TestAuth role={role}>{ui}</TestAuth>);

const SUMMARY = {
  ticker: "AAPL",
  company_name: "Apple",
  exchange: "NASDAQ",
  sector: null,
  industry: null,
  index_memberships: [],
  price: 100,
  change: 1,
  change_percent: 1,
  quote_currency: "USD",
  reported_currency: "USD",
  fair_value_verdict: null,
  fair_value_price: null,
  fair_value_method: null,
  valuation_source: null,
  fair_value_reported_currency: null,
  perf_5y_vs_spy_status: null,
  perf_5y_insufficient_history: false,
  next_earnings_date: null,
} as unknown as TickerSummaryOut;

describe("ticker page header: universe, watchlist and refresh actions", () => {
  it("shows all three to an admin", () => {
    asRole("admin", <TickerHeader symbol="AAPL" data={SUMMARY} />);
    for (const name of ["Remove from Universe", "Add to watchlist", "Refresh"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.getByText("universe note")).toBeInTheDocument();
  });

  it("shows none to a viewer, who still gets the header itself", () => {
    asRole("viewer", <TickerHeader symbol="AAPL" data={SUMMARY} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByText("universe note")).toBeNull();
    expect(screen.getByRole("heading", { name: "Apple" })).toBeInTheDocument();
  });
});

describe("ETF page header: universe and ETF watchlist", () => {
  it("shows them to an admin and hides them from a viewer", () => {
    asRole("admin", <EtfHeader data={SUMMARY} />);
    expect(screen.getByRole("button", { name: "Add ETF to watchlist" })).toBeInTheDocument();
    cleanup();
    asRole("viewer", <EtfHeader data={SUMMARY} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});

describe("Moat tab: setting the rating", () => {
  beforeEach(() => {
    hooks.moat = { ticker: "AAPL", moat: "narrow_moat", updated_at: "2026-06-01T00:00:00" } as TickerMoatOut;
  });

  it("an admin gets the rating picker", () => {
    asRole("admin", <EconomicMoatTab ticker="AAPL" />);
    expect(screen.getByRole("button", { name: /Wide moat/ })).toBeInTheDocument();
  });

  it("a viewer reads the rating as text, with no picker", () => {
    asRole("viewer", <EconomicMoatTab ticker="AAPL" />);
    expect(screen.queryByRole("button", { name: /Wide moat/ })).toBeNull();
    expect(screen.getByTestId("moat-rating-readonly")).toHaveTextContent(/Narrow/);
  });

  it("a viewer of an unrated ticker reads 'Not rated'", () => {
    hooks.moat = { ticker: "AAPL", moat: null, updated_at: null } as unknown as TickerMoatOut;
    asRole("viewer", <EconomicMoatTab ticker="AAPL" />);
    expect(screen.getByTestId("moat-rating-readonly")).toHaveTextContent("Not rated");
  });
});

describe("watchlist page controls", () => {
  const LIST = { id: 1, name: "Core", tickers: ["AAPL", "MSFT"], created_at: "2026-01-01" } as unknown as WatchlistOut;

  it("the rename pencil is for an admin only; the name and count stay", () => {
    asRole("admin", <WatchlistNameEditor watchlist={LIST} />);
    expect(screen.getByRole("button", { name: "Rename Core" })).toBeInTheDocument();
    cleanup();
    asRole("viewer", <WatchlistNameEditor watchlist={LIST} />);
    expect(screen.queryByRole("button", { name: "Rename Core" })).toBeNull();
    expect(screen.getByText(/Core · 2 tickers/)).toBeInTheDocument();
  });

  it("the row's remove button is for an admin only; the cell stays so the column keeps its place", () => {
    const flow = { removeState: {}, setRemoveState: vi.fn(), confirmRemove: vi.fn() };
    const row = (
      <table>
        <tbody>
          <tr>
            <RemoveCell ticker="AAPL" watchlistName="Core" flow={flow} />
          </tr>
        </tbody>
      </table>
    );
    asRole("admin", row);
    expect(screen.getByRole("button", { name: "Remove AAPL" })).toBeInTheDocument();
    cleanup();
    const { container } = asRole("viewer", row);
    expect(screen.queryByRole("button", { name: "Remove AAPL" })).toBeNull();
    expect(container.querySelectorAll("td")).toHaveLength(1);
  });
});

describe("saved screener views", () => {
  const draw = (role: "admin" | "viewer") =>
    asRole(
      role,
      <SavedFiltersBarView
        universe="all"
        sortField="overall_score"
        sortDirection="desc"
        filters={{} as never}
        watchlistId={null}
        onLoad={vi.fn()}
        onReset={vi.fn()}
        saved={[{ id: 1, name: "Cheap quality" } as never]}
        onSave={vi.fn()}
        onDelete={vi.fn()}
        defaultListOpen
      />,
    );

  it("an admin can save the current view and delete a saved one", () => {
    draw("admin");
    expect(screen.getByRole("button", { name: "Save current view" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: 'Delete view "Cheap quality"' })).toBeInTheDocument();
  });

  it("a viewer can apply a saved view and Reset, but not save or delete", () => {
    draw("viewer");
    expect(screen.queryByRole("button", { name: "Save current view" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Delete view/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Cheap quality" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
  });
});

describe("Debt card: the CET1 / NPL form for a bank", () => {
  const ratio = { value: 1, adjusted_value: null, label: "safe", points: 100, saved_by_tiebreaker: false, breach_context: null, note: null };
  beforeEach(() => {
    hooks.step5 = {
      ticker: "BNK",
      company_type: "Bank",
      classification_note: "",
      ratios: { current_ratio: ratio, debt_to_ebitda: ratio, debt_servicing_ratio: ratio, interest_coverage_ratio: ratio },
      bank_capital_metrics_editable: true,
      deferred_revenue_current: null,
      score: 80,
      verdict: "Pass",
      unrescued_breaches: [],
      pass_with_caution: false,
      weights: {},
      outlier_warnings: [],
      data_quality: [],
    } as unknown as Step5Out;
  });

  it("an admin gets the form, a viewer does not", () => {
    asRole("admin", <Step5Card ticker="BNK" />);
    expect(screen.getByText("CET1 and NPL form")).toBeInTheDocument();
    cleanup();
    asRole("viewer", <Step5Card ticker="BNK" />);
    expect(screen.queryByText("CET1 and NPL form")).toBeNull();
  });
});

describe("Financials tab: the SEC cell check", () => {
  const data = {
    periods: ["2025-06-30", "2026-06-30"],
    groups: [{ label: null, items: [{ label: "Interest Paid", values: [0, 0], unit: "money", emphasis: false }] }],
  };

  it("an admin gets the check on a zero cell; a viewer does not (it is an admin-only SEC EDGAR call)", () => {
    asRole("admin", <FinancialsStatementTable ticker="AAPL" periodType="annual" data={data} statement="cash_flow" />);
    expect(screen.getAllByRole("button", { name: "Check SEC" }).length).toBeGreaterThan(0);
    cleanup();
    asRole("viewer", <FinancialsStatementTable ticker="AAPL" periodType="annual" data={data} statement="cash_flow" />);
    expect(screen.queryByRole("button", { name: "Check SEC" })).toBeNull();
  });
});
