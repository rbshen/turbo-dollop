// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MultiExportPanel } from "@/components/watchlist/MultiExportPanel";
import type { WatchlistExportListOut, WatchlistOut } from "@/lib/api/types";

afterEach(cleanup);

const wl = (id: number, name: string, count: number): WatchlistOut => ({
  id,
  name,
  sort_field: "ticker",
  sort_direction: "asc",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tickers: Array.from({ length: count }, (_, i) => ({ ticker: `T${i}`, added_at: "2026-01-01T00:00:00Z" })),
});

// Created order is E10, E2, ETF, Growth; the panel must show natural name order (E2 before E10).
const LISTS = [wl(1, "E10", 4), wl(2, "E2", 2), wl(3, "ETF", 1), wl(4, "Growth", 0)];

const PAYLOAD: Record<number, WatchlistExportListOut> = {
  1: { id: 1, name: "E10", tickers: [{ ticker: "AAPL", exchange: "NASDAQ", sector: "Technology" }, { ticker: "NEWCO", exchange: null, sector: null }] },
  2: { id: 2, name: "E2", tickers: [{ ticker: "AAPL", exchange: "NASDAQ", sector: "Technology" }, { ticker: "XOM", exchange: "NYSE", sector: "Energy" }] },
  3: { id: 3, name: "ETF", tickers: [{ ticker: "SPY", exchange: "AMEX", sector: null }] },
  4: { id: 4, name: "Growth", tickers: [] },
};

function setup(props: Partial<React.ComponentProps<typeof MultiExportPanel>> = {}) {
  const loadLists = vi.fn(async (ids: number[]) => ids.map((id) => PAYLOAD[id]));
  const download = vi.fn();
  const onClose = vi.fn();
  render(<MultiExportPanel watchlists={LISTS} onClose={onClose} loadLists={loadLists} download={download} {...props} />);
  return { loadLists, download, onClose };
}

const box = (name: RegExp) => screen.getByRole("checkbox", { name });
const exportButton = () => screen.getByRole("button", { name: /^Export/ });

describe("MultiExportPanel", () => {
  it("lists every watchlist in natural name order with its ticker count", () => {
    setup();
    const labels = within(screen.getByRole("group", { name: "Lists to export" })).getAllByRole("checkbox").map((el) => el.closest("label")?.textContent);
    expect(labels).toEqual(["E2 (2)", "E10 (4)", "ETF (1)", "Growth (0)"]);
  });

  it("keeps Export disabled until a list is ticked", () => {
    setup();
    expect(exportButton()).toBeDisabled();
    fireEvent.click(box(/^E2/));
    expect(exportButton()).toBeEnabled();
    fireEvent.click(box(/^E2/));
    expect(exportButton()).toBeDisabled();
  });

  it("selects all and clears", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getAllByRole("checkbox").every((el) => (el as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByRole("button", { name: "Select all" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getAllByRole("checkbox").some((el) => (el as HTMLInputElement).checked)).toBe(false);
    expect(screen.getByRole("button", { name: "Clear" })).toBeDisabled();
  });

  it("offers the two formats, TradingView first", () => {
    setup();
    const group = screen.getByRole("group", { name: "Export format" });
    expect(within(group).getAllByRole("button").map((el) => el.textContent)).toEqual(["TradingView (.txt)", "thinkorswim (.csv)"]);
  });

  it("exports the ticked lists, in natural name order, as one TradingView file", async () => {
    const { loadLists, download } = setup();
    fireEvent.click(box(/^E10/));
    fireEvent.click(box(/^E2/));
    fireEvent.click(exportButton());

    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(loadLists).toHaveBeenCalledWith([2, 1]);
    const [filename, content, mime] = download.mock.calls[0];
    expect(filename).toMatch(/^fathom-watchlists_2-lists_\d{4}-\d{2}-\d{2}_tradingview\.txt$/);
    expect(content).toBe("###Technology,NASDAQ:AAPL,###Energy,NYSE:XOM");
    expect(mime).toBe("text/plain");
  });

  it("exports one thinkorswim file when that format is chosen", async () => {
    const { download } = setup();
    fireEvent.click(box(/^E10/));
    fireEvent.click(box(/^E2/));
    fireEvent.click(screen.getByRole("button", { name: "thinkorswim (.csv)" }));
    fireEvent.click(exportButton());

    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    const [filename, content, mime] = download.mock.calls[0];
    expect(filename).toMatch(/_thinkorswim\.csv$/);
    expect(content).toBe("AAPL\nXOM\nNEWCO\n");
    expect(mime).toBe("text/csv");
  });

  it("shows the result line: symbols, duplicates, empty lists, and the skipped count in the caution tone", async () => {
    setup();
    fireEvent.click(box(/^E10/));
    fireEvent.click(box(/^E2/));
    fireEvent.click(box(/^Growth/));
    fireEvent.click(exportButton());

    const status = await screen.findByText(/^Exported 2 symbols from 3 lists/);
    expect(status.textContent).toBe("Exported 2 symbols from 3 lists · 1 duplicate removed · 1 empty list skipped · 1 skipped (no cached exchange)");
    expect(screen.getByText(/1 skipped \(no cached exchange\)/)).toHaveClass("text-caution");
    expect(status.closest("[role=status]")?.querySelector(".text-negative")).toBeNull();
  });

  it("downloads nothing when every selected list is empty, and says so", async () => {
    const { download } = setup();
    fireEvent.click(box(/^Growth/));
    fireEvent.click(exportButton());

    expect(await screen.findByText(/^Nothing to export/)).toHaveTextContent("Nothing to export · 1 empty list skipped");
    expect(download).not.toHaveBeenCalled();
  });

  it("shows the request failure inline and downloads nothing", async () => {
    const { download } = setup({ loadLists: vi.fn(async () => Promise.reject(new Error("GET /x failed: 404 - No watchlist with id 3"))) });
    fireEvent.click(box(/^ETF/));
    fireEvent.click(exportButton());

    expect(await screen.findByText(/Couldn't export — No watchlist with id 3/)).toBeInTheDocument();
    expect(download).not.toHaveBeenCalled();
    expect(exportButton()).toBeEnabled();
  });

  it("clears a stale result when the selection changes", async () => {
    setup();
    fireEvent.click(box(/^E2/));
    fireEvent.click(exportButton());
    await screen.findByText(/^Exported/);
    fireEvent.click(box(/^ETF/));
    expect(screen.queryByText(/^Exported/)).not.toBeInTheDocument();
  });

  it("closes from the Close button", () => {
    const { onClose } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
