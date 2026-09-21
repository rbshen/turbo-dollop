// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import BreadthPage from "@/app/breadth/page";
import type { MarketBreadthOut, MarketBreadthPointOut } from "@/lib/api/types";

afterEach(cleanup);

// jsdom has no layout engine; recharts' ResponsiveContainer needs ResizeObserver to mount at all.
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", NoopResizeObserver);

const point = (as_of_date: string, is_backfilled: boolean, overrides: Partial<MarketBreadthPointOut> = {}): MarketBreadthPointOut => ({
  as_of_date, pct_above_sma20: 17.89, pct_above_sma50: 27.83, pct_above_sma200: 49.3, sma20_above: 90, sma50_above: 140, sma200_above: 247, new_highs: 5, new_lows: 29,
  net_new_highs: -24, constituents: 503, stale_excluded: 0, sma20_eligible: 503, sma50_eligible: 503, sma200_eligible: 501, hl_eligible: 500, is_backfilled,
  ...overrides,
});

const body = (series: MarketBreadthPointOut[]): MarketBreadthOut => ({
  universe: "sp500",
  as_of_date: series.at(-1)?.as_of_date ?? null,
  computed_at: series.length ? "2026-09-21T03:35:00" : null,
  latest: series.at(-1) ?? null,
  series,
});

const ALL_BACKFILLED = body([point("2026-09-17", true), point("2026-09-18", true)]);
const MIXED = body([point("2026-09-17", true), point("2026-09-18", false), point("2026-09-19", false)]);
const EMPTY = body([]);

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <BreadthPage />
    </SWRConfig>
  );
}

function stubFetch(payload: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } })));
}

beforeEach(() => stubFetch(ALL_BACKFILLED));

describe("BreadthPage", () => {
  it("shows a loading state before data arrives", () => {
    renderPage();
    expect(screen.getByText("Loading market breadth…")).toBeInTheDocument();
  });

  it("renders the latest readings with their denominators and the as-of date (timezone-safe)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("27.8%")).toBeInTheDocument());
    expect(screen.getByText("49.3%")).toBeInTheDocument();
    expect(screen.getByText("-24")).toBeInTheDocument();
    expect(screen.getByText("17.9%")).toBeInTheDocument();
    expect(screen.getByText("90 of 503 stocks")).toBeInTheDocument();
    expect(screen.getByText("140 of 503 stocks")).toBeInTheDocument();
    expect(screen.getByText("247 of 501 stocks")).toBeInTheDocument();
    expect(screen.getByText("5 highs · 29 lows")).toBeInTheDocument();
    expect(screen.getByText(/As of close Sep 18, 2026/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /moving averages over time/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Net new 52-week highs/ })).toBeInTheDocument();
  });

  it("says so when every session is backfilled", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/Every session shown is backfilled/)).toBeInTheDocument());
    expect(screen.getByText(/survivorship-biased/)).toBeInTheDocument();
  });

  it("names the first live session when there is a backfilled past before it", async () => {
    stubFetch(MIXED);
    renderPage();
    await waitFor(() => expect(screen.getByText(/Sessions before Sep 18, 2026 are backfilled/)).toBeInTheDocument());
    expect(screen.queryByText(/Every session shown is backfilled/)).not.toBeInTheDocument();
  });

  it("shows an em dash for a metric with no eligible constituents", async () => {
    stubFetch(body([point("2026-09-18", false, { pct_above_sma200: null, sma200_eligible: 0, sma200_above: 0 })]));
    renderPage();
    await waitFor(() => expect(screen.getByText("—")).toBeInTheDocument());
    expect(screen.getByText("0 of 0 stocks")).toBeInTheDocument();
  });

  it("shows a 20-day tile that has no reading yet when the row predates the metric", async () => {
    stubFetch(body([point("2026-09-18", true, { pct_above_sma20: null, sma20_above: null, sma20_eligible: null })]));
    renderPage();
    await waitFor(() => expect(screen.getByText("Not computed yet")).toBeInTheDocument());
    expect(screen.getByText("27.8%")).toBeInTheDocument(); // the other tiles still render
  });

  it("shows the no-data state when the nightly job has never run", async () => {
    stubFetch(EMPTY);
    renderPage();
    await waitFor(() => expect(screen.getByText(/No data yet/)).toBeInTheDocument());
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows an error when the request fails", async () => {
    stubFetch({ detail: "boom" }, 500);
    renderPage();
    await waitFor(() => expect(screen.getByText("Failed to load market breadth.")).toBeInTheDocument());
  });

  it("keeps the methodology footnote visible", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("27.8%")).toBeInTheDocument());
    expect(screen.getByText(/Breadth across the current S&P 500 constituents/)).toBeInTheDocument();
  });
});
