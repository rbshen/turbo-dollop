// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EtfHeader } from "@/components/ticker/EtfHeader";
import { TickerHeader } from "@/components/ticker/TickerHeader";
import type { TickerSummaryOut, UniverseStatusOut } from "@/lib/api/types";

// The real shared control runs inside both headers; only its data hook and the two actions are mocked.
let universeStatus: UniverseStatusOut | undefined;
const addToUniverse = vi.fn();
vi.mock("@/lib/hooks/useUniverse", () => ({
  useUniverseStatus: () => ({ data: universeStatus }),
  addToUniverse: (...a: unknown[]) => addToUniverse(...a),
  removeFromUniverse: vi.fn(),
}));
vi.mock("@/components/ticker/AddToWatchlistButton", () => ({ AddToWatchlistButton: () => <button>Add to watchlist</button> }));
vi.mock("@/components/ticker/EtfWatchlistButton", () => ({ EtfWatchlistButton: () => <button>Add to watchlist</button> }));
vi.mock("@/components/ticker/RefreshButton", () => ({ RefreshButton: () => <button>Refresh data</button> }));
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useSpeculativeGrowth", () => ({ useSpeculativeGrowth: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTrendAnalysis", () => ({ useTrendAnalysis: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useTickerScore", () => ({ useTickerScore: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/useEtfOverview", () => ({ useEtfOverview: () => ({ data: undefined }) }));

beforeEach(() => {
  universeStatus = undefined;
  addToUniverse.mockReset();
});
afterEach(cleanup);

function status(over: Partial<UniverseStatusOut> = {}): UniverseStatusOut {
  return {
    ticker: "ABC",
    kind: "stock",
    in_universe: false,
    classification: "browsed",
    state: "browsed",
    reasons: [],
    can_add: true,
    can_remove: false,
    added_at: null,
    added_source: null,
    delisted: false,
    ...over,
  };
}
const PROTECTED: Partial<UniverseStatusOut> = { state: "protected", can_add: false, in_universe: true, classification: "index", reasons: ["index:dow", "index:nasdaq", "index:sp500", "watchlist:E1", "manual:moat"] };

// The action cluster is the nearest ancestor of the Refresh / watchlist button that carries the nowrap classes.
function cluster(name: string) {
  return screen.getByRole("button", { name }).parentElement!;
}
function expectNonWrappingRow(actionCluster: HTMLElement) {
  expect(actionCluster).toHaveClass("flex", "flex-nowrap", "items-center", "whitespace-nowrap");
  expect(actionCluster).not.toHaveClass("flex-wrap");
  const column = actionCluster.parentElement!;
  expect(column).toHaveClass("shrink-0", "flex-col");
  const row = column.parentElement!;
  expect(row).toHaveClass("flex", "justify-between");
  expect(row).not.toHaveClass("flex-wrap"); // the pre-3b layout wrapped here, which is how the cluster dropped to a second row
  expect(row.firstElementChild).toHaveClass("min-w-0"); // the title block is the part that shrinks
}

const SUMMARY = {
  ticker: "ABC",
  company_name: "Abc Corp",
  exchange: "NYSE",
  sector: null,
  industry: null,
  index_memberships: [],
  price: 10,
  change: 0,
  change_percent: 0,
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

const HEADERS: [string, (ticker: string) => ReturnType<typeof render>, string][] = [
  ["TickerHeader", (t) => render(<TickerHeader symbol={t} data={{ ...SUMMARY, ticker: t }} />), "Refresh data"],
  ["EtfHeader", (t) => render(<EtfHeader data={{ ...SUMMARY, ticker: t }} />), "Add to watchlist"],
];

describe.each(HEADERS)("%s: the universe control", (_name, draw, anchor) => {
  it("keeps the actions in a non-wrapping, non-shrinking cluster on the top right", () => {
    universeStatus = status();
    draw("ABC");
    expectNonWrappingRow(cluster(anchor));
  });

  it("puts the Add button first in that cluster, before the watchlist button", () => {
    universeStatus = status();
    draw("ABC");
    const buttons = Array.from(cluster(anchor).querySelectorAll("button")).map((b) => b.textContent);
    expect(buttons[0]).toBe("Add to Universe");
    expect(buttons).toContain("Add to watchlist");
  });

  it("shows nothing universe-related for a protected ticker, and the other buttons stay", () => {
    universeStatus = status(PROTECTED);
    const { container } = draw("GOOGL");
    expect(container).not.toHaveTextContent(/universe/i);
    expect(screen.getByRole("button", { name: anchor })).toBeInTheDocument();
    expectNonWrappingRow(cluster(anchor));
  });

  it("renders a note under the cluster, outside the action row", async () => {
    universeStatus = status();
    addToUniverse.mockRejectedValue(new Error("POST /tickers/ABC/universe failed: 503 - Profile data is paused."));
    draw("ABC");
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    const alert = await screen.findByRole("alert");
    const actionCluster = cluster(anchor);
    expect(actionCluster).not.toContainElement(alert);
    expect(actionCluster.parentElement).toContainElement(alert); // the same right-hand column, below the row
    expect(actionCluster.querySelectorAll("button")[0]).toHaveTextContent("Add to Universe"); // the button did not move
  });
});
