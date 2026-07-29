"use client";

import { useMemo } from "react";

import { MoatPill } from "@/components/ticker/MoatPill";
import { PriceChange } from "@/components/ticker/PriceChange";
import { ValuationBadge } from "@/components/screener/ValuationBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { WatchlistOut, WatchlistRowOut, WatchlistSortField } from "@/lib/api/types";
import { fmtCompactMoney, fmtMoney, fmtNumber } from "@/lib/format";
import type { SortDirection } from "@/lib/screenerFilters";
import { chipClassFor } from "@/lib/tierColor";
import { removeTickerFromWatchlist, updateWatchlist } from "@/lib/hooks/useWatchlists";
import { useWatchlistRows } from "@/lib/hooks/useWatchlistRows";
import { sortWatchlistRows } from "@/lib/watchlistSort";

interface Props {
  watchlist: WatchlistOut;
}

const SORT_FIELD_OPTIONS: { value: WatchlistSortField; label: string }[] = [
  { value: "ticker", label: "Ticker" },
  { value: "price", label: "Price" },
  { value: "change_percent", label: "Change %" },
  { value: "overall_score", label: "Overall" },
  { value: "step1_score", label: "Step 1" },
  { value: "step2_score", label: "Step 2" },
  { value: "step4_score", label: "Step 4" },
  { value: "step5_score", label: "Step 5" },
];

// Same F/G/D/P labels and order as ScreenerCard's STEP_CHIPS.
const STEP_CHIPS: { key: keyof WatchlistRowOut; verdictKey: keyof WatchlistRowOut; label: string }[] = [
  { key: "step1_score", verdictKey: "step1_verdict", label: "F" },
  { key: "step2_score", verdictKey: "step2_verdict", label: "G" },
  { key: "step5_score", verdictKey: "step5_verdict", label: "D" },
  { key: "step4_score", verdictKey: "step4_verdict", label: "P" },
];

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "watchlist";
}

export function WatchlistSection({ watchlist }: Props) {
  const { data: rows, error } = useWatchlistRows(watchlist.id);

  const sorted = useMemo(
    () => (rows ? sortWatchlistRows(rows, watchlist.sort_field as WatchlistSortField, watchlist.sort_direction as SortDirection) : []),
    [rows, watchlist.sort_field, watchlist.sort_direction]
  );

  function handleSortFieldChange(field: WatchlistSortField) {
    updateWatchlist(watchlist.id, { sort_field: field });
  }

  function handleSortDirectionChange(direction: SortDirection) {
    updateWatchlist(watchlist.id, { sort_direction: direction });
  }

  function openTicker(ticker: string) {
    window.open(`/tickers/${ticker}`, "_blank", "noopener,noreferrer");
  }

  function handleExport() {
    if (!rows) return;
    // TradingView's own watchlist "sections" feature exports as ###SectionName
    // inline in the same comma-separated list -- group by sector (falling
    // back to a literal "Other" bucket, never dropping the ### marker for
    // just those rows so the file's structure stays consistent throughout).
    // One pass over `rows` (raw fetch order, not the on-screen sort)
    // preserves each row's existing relative order within its own sector,
    // and sections appear in first-encounter order.
    const bySector = new Map<string, typeof rows>();
    for (const row of rows) {
      const key = row.sector ?? "Other";
      const bucket = bySector.get(key);
      if (bucket) {
        bucket.push(row);
      } else {
        bySector.set(key, [row]);
      }
    }

    const parts: string[] = [];
    for (const [sector, sectorRows] of bySector) {
      // Rows with no cached exchange yet (never-visited ticker) can't form
      // a valid EXCHANGE:SYMBOL pair -- skipped rather than written bare.
      // A sector left with nothing exportable is skipped entirely too, so
      // a ### marker never appears with zero tickers under it.
      const pairs = sectorRows.filter((r) => r.exchange != null).map((r) => `${r.exchange}:${r.ticker}`);
      if (pairs.length === 0) continue;
      parts.push(`###${sector}`, ...pairs);
    }

    const blob = new Blob([parts.join(",")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slugify(watchlist.name)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-heading text-lg font-semibold tracking-tight text-zinc-100">{watchlist.name}</h2>
        <span className="text-xs text-zinc-600">
          {watchlist.tickers.length} ticker{watchlist.tickers.length === 1 ? "" : "s"}
        </span>
        <div className="ml-auto flex items-center gap-1.5 text-xs">
          <label className="text-zinc-500" htmlFor={`sort-field-${watchlist.id}`}>
            Sort by
          </label>
          <select
            id={`sort-field-${watchlist.id}`}
            value={watchlist.sort_field}
            onChange={(e) => handleSortFieldChange(e.target.value as WatchlistSortField)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-300 focus:border-zinc-500 focus:outline-none"
          >
            {SORT_FIELD_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={watchlist.sort_direction}
            onChange={(e) => handleSortDirectionChange(e.target.value as SortDirection)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-300 focus:border-zinc-500 focus:outline-none"
          >
            <option value="asc">Asc</option>
            <option value="desc">Desc</option>
          </select>
          <button
            type="button"
            onClick={handleExport}
            disabled={!rows || rows.length === 0}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-300 hover:border-zinc-500 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Export
          </button>
        </div>
      </div>

      {watchlist.tickers.length === 0 ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6 text-center text-sm text-zinc-600">
          No tickers in this watchlist yet — add one from its ticker page.
        </div>
      ) : error ? (
        <p className="text-sm text-red-400">Couldn&apos;t load this watchlist — {error.message}</p>
      ) : !rows ? (
        <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>
      ) : (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40">
          <Table className="border-separate border-spacing-0">
            <TableHeader>
              <TableRow className="border-zinc-800">
                <TableHead className="text-zinc-500">Ticker</TableHead>
                <TableHead className="text-zinc-500">Sector</TableHead>
                <TableHead className="text-zinc-500">Price</TableHead>
                <TableHead className="text-zinc-500">Change</TableHead>
                <TableHead className="text-zinc-500">Moat</TableHead>
                <TableHead className="text-zinc-500">Valuation</TableHead>
                <TableHead className="text-zinc-500" colSpan={4}>
                  Analysis
                </TableHead>
                <TableHead className="text-zinc-500">Rating</TableHead>
                <TableHead className="text-zinc-500">Mkt Cap</TableHead>
                <TableHead className="text-zinc-500">P/E</TableHead>
                <TableHead className="text-zinc-500">Beta</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((row) => (
                <TableRow
                  key={row.ticker}
                  onClick={() => openTicker(row.ticker)}
                  className="cursor-pointer border-zinc-800"
                >
                  <TableCell className="font-mono font-bold text-zinc-100">{row.ticker}</TableCell>
                  <TableCell className="text-zinc-500">{row.sector ?? "—"}</TableCell>
                  <TableCell className="font-mono tabular-nums text-zinc-300">
                    {row.price != null ? fmtMoney(row.price) : "—"}
                  </TableCell>
                  <TableCell>
                    {row.change != null && row.change_percent != null ? (
                      <PriceChange change={row.change} changePercent={row.change_percent} />
                    ) : (
                      <span className="text-zinc-500">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <MoatPill moat={row.moat} />
                  </TableCell>
                  <TableCell>
                    <ValuationBadge verdict={row.valuation_verdict} />
                  </TableCell>
                  {STEP_CHIPS.map(({ key, verdictKey, label }) => {
                    const score = row[key] as number | null;
                    const verdict = row[verdictKey] as string | null;
                    return (
                      <TableCell key={label}>
                        <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${chipClassFor(score, verdict)}`}>
                          {label} · {score ?? "—"}
                        </span>
                      </TableCell>
                    );
                  })}
                  <TableCell className="text-zinc-400">{row.consensus_rating}</TableCell>
                  <TableCell className="font-mono text-zinc-300">
                    {row.market_cap != null ? fmtCompactMoney(row.market_cap) : "—"}
                  </TableCell>
                  <TableCell className="font-mono text-zinc-300">{row.pe_ratio != null ? fmtNumber(row.pe_ratio) : "—"}</TableCell>
                  <TableCell className="font-mono text-zinc-300">{row.beta != null ? fmtNumber(row.beta) : "—"}</TableCell>
                  <TableCell>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeTickerFromWatchlist(watchlist.id, row.ticker);
                      }}
                      className="text-zinc-600 hover:text-red-400"
                    >
                      Remove
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
