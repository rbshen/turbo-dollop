"use client";

import { useMemo } from "react";

import { HEAD_CLASS, openTickerPage, RemoveCell, SkeletonRows, SortableColumnHead, useRemoveFlow } from "@/components/watchlist/tableParts";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { EtfWatchlistRow, WatchlistOut } from "@/lib/api/types";
import { applyEtfHeaderClick, sortEtfWatchlistRows, type EtfSortableField, type EtfSortRule } from "@/lib/etfWatchlistSort";
import { fmtCompactMoney, fmtCompactNumber, fmtMoney, fmtNumber, fmtPct, fmtPlainPct, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  watchlist: WatchlistOut;
  rows: EtfWatchlistRow[] | undefined;
  error?: Error;
  sortRules: EtfSortRule[];
  onSortRulesChange: (rules: EtfSortRule[]) => void;
}

// The ETF table of the list named "ETF" (docs/specs/etf-page.md, "Watchlist rows"). Ticker, Name, Price, % Chg, Class,
// Exp %, AUM, Holdings, Avg Vol 30d, Yield %, Beta, YTD, 1Y, then the remove column. The figures are the stored
// EtfScreenerRow values from GET /api/watchlists/{id}/etf-rows, formatted with the same helpers as the ETFs screener
// card and the stock table; a missing value (including every figure of a member the nightly job has not reached yet) is
// an en dash.
//
// Width. The container (PageContainer max-w-7xl, px-8) is 1216px wide at a 1280px window (about 1200 with a scrollbar).
// The 13 fixed widths below total 1008px (each includes the cell's 16px right padding and room for the active sort
// caret), so the Name column gets 192px or more at 1280px (it is `w-full`, so it takes whatever the other columns leave).
// It never shrinks below MIN_NAME_WIDTH: the table's min-width is 1008 + 140 = 1148, rounded up to 1160. Below about
// 1240px of window the table is wider than its box and the container's overflow scrolls sideways (the fallback).
const FIXED_WIDTHS = {
  ticker: "w-[72px]",
  last_price: "w-[84px]",
  pct_change_1d: "w-[72px]",
  asset_class: "w-[104px]",
  expense_ratio: "w-[68px]",
  aum: "w-[80px]",
  holdings_count: "w-[88px]",
  avg_volume_30d: "w-[104px]",
  dividend_yield: "w-[80px]",
  beta: "w-[60px]",
  return_ytd: "w-[80px]",
  return_1y: "w-[80px]",
} as const;

// 13 data columns plus the remove column; spans the loading skeleton.
const COLUMN_COUNT = 14;

const DASH = "–";

const NUMBER_CELL = "text-right font-mono text-text-secondary";

function Dash() {
  return <span className="text-text-tertiary">{DASH}</span>;
}

/** A right-aligned mono cell: the formatted value, or the dash when the stored figure is null. */
function NumberCell({ value, format, tone }: { value: number | null; format: (n: number) => string; tone?: (n: number) => string }) {
  return (
    <TableCell className={cn(NUMBER_CELL, value != null && tone?.(value))}>{value != null ? format(value) : <Dash />}</TableCell>
  );
}

export function EtfWatchlistTable({ watchlist, rows, error, sortRules, onSortRulesChange }: Props) {
  const sorted = useMemo(() => (rows ? sortEtfWatchlistRows(rows, sortRules) : []), [rows, sortRules]);
  const removeFlow = useRemoveFlow(watchlist.id);

  function head(field: EtfSortableField, label: string, className: string, align?: "right") {
    return (
      <SortableColumnHead
        field={field}
        rules={sortRules}
        onSort={(f) => onSortRulesChange(applyEtfHeaderClick(sortRules, f))}
        align={align}
        className={`${HEAD_CLASS} ${className}${align === "right" ? " text-right" : ""}`}
      >
        {label}
      </SortableColumnHead>
    );
  }

  if (watchlist.tickers.length === 0) {
    return <p className="text-xs text-text-tertiary">No tickers in this watchlist yet — add one from its ticker page.</p>;
  }

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load this watchlist — {error.message}</p>;
  }

  if (!rows) {
    return (
      <Table className="min-w-[1160px]">
        <TableBody>
          <SkeletonRows columns={COLUMN_COUNT} />
        </TableBody>
      </Table>
    );
  }

  return (
    <Table containerClassName="max-h-[70vh] overflow-auto" className="min-w-[1160px]">
      <TableHeader>
        <TableRow className="h-9">
          {head("ticker", "Ticker", FIXED_WIDTHS.ticker)}
          {head("name", "Name", "w-full min-w-[140px]")}
          {head("last_price", "Price", FIXED_WIDTHS.last_price, "right")}
          {head("pct_change_1d", "% Chg", FIXED_WIDTHS.pct_change_1d, "right")}
          {head("asset_class", "Class", FIXED_WIDTHS.asset_class)}
          {head("expense_ratio", "Exp %", FIXED_WIDTHS.expense_ratio, "right")}
          {head("aum", "AUM", FIXED_WIDTHS.aum, "right")}
          {head("holdings_count", "Holdings", FIXED_WIDTHS.holdings_count, "right")}
          {head("avg_volume_30d", "Avg Vol 30d", FIXED_WIDTHS.avg_volume_30d, "right")}
          {head("dividend_yield", "Yield %", FIXED_WIDTHS.dividend_yield, "right")}
          {head("beta", "Beta", FIXED_WIDTHS.beta, "right")}
          {head("return_ytd", "YTD", FIXED_WIDTHS.return_ytd, "right")}
          {head("return_1y", "1Y", FIXED_WIDTHS.return_1y, "right")}
          <TableHead className={`${HEAD_CLASS} w-9`} />
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((row) => (
          <TableRow key={row.ticker} interactive onClick={() => openTickerPage(row.ticker)}>
            <TableCell className="font-mono text-sm font-bold text-text-primary">{row.ticker}</TableCell>
            <TableCell className="w-full min-w-[140px] max-w-0 truncate text-text-secondary" title={row.name ?? undefined}>
              {row.name ?? <Dash />}
            </TableCell>
            <NumberCell value={row.last_price} format={(n) => fmtMoney(n)} />
            <NumberCell value={row.pct_change_1d} format={(n) => fmtPct(n)} tone={pnlClass} />
            <TableCell className="max-w-[104px] truncate text-text-secondary" title={row.asset_class ?? undefined}>
              {row.asset_class ?? <Dash />}
            </TableCell>
            <NumberCell value={row.expense_ratio} format={(n) => fmtPlainPct(n, 2)} />
            <NumberCell value={row.aum} format={(n) => fmtCompactMoney(n)} />
            <NumberCell value={row.holdings_count} format={(n) => n.toLocaleString("en-US")} />
            <NumberCell value={row.avg_volume_30d} format={fmtCompactNumber} />
            <NumberCell value={row.dividend_yield} format={(n) => fmtPlainPct(n, 2)} />
            <NumberCell value={row.beta} format={(n) => fmtNumber(n)} />
            <NumberCell value={row.return_ytd} format={(n) => fmtPct(n)} tone={pnlClass} />
            <NumberCell value={row.return_1y} format={(n) => fmtPct(n)} tone={pnlClass} />
            <RemoveCell ticker={row.ticker} watchlistName={watchlist.name} flow={removeFlow} />
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
