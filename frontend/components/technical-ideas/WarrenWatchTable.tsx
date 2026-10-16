import { useState, type MouseEvent } from "react";
import { ArrowDown, ArrowUp, Info } from "@phosphor-icons/react";

import { WarrenWatchRemoveButton } from "@/components/technical-ideas/WarrenWatchRemoveButton";
import { Badge } from "@/components/ui/badge";
import { pillVariants } from "@/components/ui/pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { WarrenWatchRowOut } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";
import {
  BREACHED_PL_NOTE,
  entryTitle,
  fmtBarsAgo,
  fmtEtDate,
  fmtEtStamp,
  fmtSignedPct1,
  instructionDisplay,
  lastEntryRefreshTitle,
  NO_ENTRY_NOTE,
  sortByLatestArrow,
  STOP_BASIS_LABEL,
  stopAboveEntry,
  stopAboveEntryNote,
} from "@/lib/technicalIdeas";
import { cn } from "@/lib/utils";

// Sticky header cells paint bg-page (not a surface fill) inside the table's own bounded scroll box, as the Watchlist table does.
// The table fits the page container (max-w-7xl, 1216px of content) with no horizontal scroll: cells use a tight right padding
// instead of the kit's pr-4, numbers are compact mono, and only the Instruction cell is allowed to wrap.
const PAD = "pr-2.5";
const HEAD_CLASS = `sticky top-0 z-20 bg-page ${PAD} text-xs font-medium text-text-tertiary`;
const NUM_CLASS = `${PAD} whitespace-nowrap text-right font-mono text-xs`;

// The arrow's colour as the chart draws it: Blue is the chart's blue (chart-ema21), Yellow and Gray their own chart-warren tokens.
// Literal class names so Tailwind sees them.
const SIGNAL_TONE_CLASS: Record<WarrenWatchRowOut["latest_arrow_color"], string> = {
  blue: "bg-chart-ema21/16 text-chart-ema21",
  yellow: "bg-chart-warren-yellow/16 text-chart-warren-yellow",
  gray: "bg-chart-warren-gray/16 text-chart-warren-gray",
};
const SIGNAL_LABEL: Record<WarrenWatchRowOut["latest_arrow_color"], string> = { blue: "Blue", yellow: "Yellow", gray: "Gray" };

interface Props {
  rows: WarrenWatchRowOut[];
}

// The whole row opens the ticker page in a new tab (as MomentumTable does); a click that starts on the ticker link or the Remove
// control is left to that element.
function handleRowClick(e: MouseEvent<HTMLTableRowElement>, ticker: string) {
  if ((e.target as HTMLElement).closest("a, button")) return;
  window.open(`/tickers/${ticker}`, "_blank", "noopener,noreferrer");
}

function SignalPill({ row }: { row: WarrenWatchRowOut }) {
  const Arrow = row.latest_arrow_direction === "up" ? ArrowUp : ArrowDown;
  const label = `${SIGNAL_LABEL[row.latest_arrow_color]} ${row.latest_arrow_direction === "up" ? "Up" : "Down"}`;
  return (
    <span
      className={cn(pillVariants({ size: "compact" }), SIGNAL_TONE_CLASS[row.latest_arrow_color])}
      title={`${label} · candle ${fmtEtStamp(row.latest_arrow_at)} ET`}
    >
      <Arrow size={10} weight="bold" aria-hidden="true" />
      {label}
    </span>
  );
}

function InstructionCell({ row }: { row: WarrenWatchRowOut }) {
  const { primary, secondary, title } = instructionDisplay(row);
  return (
    <TableCell className={`${PAD} min-w-[160px] max-w-[300px] whitespace-normal text-xs text-text-secondary`}>
      <div title={title} className="line-clamp-2 break-words">
        {primary}
      </div>
      {secondary && <div className="text-text-tertiary">{secondary}</div>}
    </TableCell>
  );
}

function StatusCell({ row }: { row: WarrenWatchRowOut }) {
  return (
    <TableCell className={`${PAD} whitespace-nowrap`}>
      {row.status === "breached" ? (
        <Badge
          size="compact"
          tone="negative"
          title={row.breached_at ? `Low reached the stop on the ${fmtEtStamp(row.breached_at)} ET candle` : undefined}
        >
          Stop breached
        </Badge>
      ) : row.entry_price == null ? (
        <Badge size="compact" tone="neutral" title={NO_ENTRY_NOTE}>
          No entry
        </Badge>
      ) : (
        <Badge size="compact" tone="positive">
          Active
        </Badge>
      )}
    </TableCell>
  );
}

function EntryCell({ row, nowMs }: { row: WarrenWatchRowOut; nowMs: number }) {
  if (row.entry_price == null) return <TableCell className={`${NUM_CLASS} text-text-tertiary`}>—</TableCell>;
  return (
    <TableCell className={`${NUM_CLASS} text-text-secondary`} title={entryTitle(row, nowMs)}>
      {fmtMoney(row.entry_price)}
    </TableCell>
  );
}

function LastCell({ row }: { row: WarrenWatchRowOut }) {
  if (row.last_price == null) return <TableCell className={`${NUM_CLASS} text-text-tertiary`}>—</TableCell>;
  return (
    <TableCell
      className={`${NUM_CLASS} text-text-primary`}
      title={row.last_price_date ? `Daily close of ${fmtEtDate(row.last_price_date)}` : "Daily close"}
    >
      {fmtMoney(row.last_price)}
    </TableCell>
  );
}

// Green above the entry, red below; a breached row's P/L is hypothetical (the trade ended at its stop), so it is muted with a note.
function PlCell({ row }: { row: WarrenWatchRowOut }) {
  if (row.pl_pct == null) return <TableCell className={`${NUM_CLASS} text-text-tertiary`}>—</TableCell>;
  const breached = row.status === "breached";
  const tone = breached ? "text-text-tertiary" : row.pl_pct > 0 ? "text-positive" : row.pl_pct < 0 ? "text-negative" : "text-text-secondary";
  return (
    <TableCell className={`${NUM_CLASS} ${tone}`} title={breached ? BREACHED_PL_NOTE : undefined}>
      {fmtSignedPct1(row.pl_pct)}
    </TableCell>
  );
}

// Negative = the last close is already below the stop: red on an active row (a missed breach), neutral otherwise.
function StopDistanceCell({ row }: { row: WarrenWatchRowOut }) {
  if (row.stop_distance_pct == null) return <TableCell className={`${NUM_CLASS} text-text-tertiary`}>—</TableCell>;
  const missed = row.status === "active" && row.stop_distance_pct < 0;
  return (
    <TableCell
      className={`${NUM_CLASS} ${missed ? "text-negative" : "text-text-secondary"}`}
      title={missed ? "The last close is below the stop on a row still marked active." : undefined}
    >
      {fmtSignedPct1(row.stop_distance_pct)}
    </TableCell>
  );
}

function StopCell({ row }: { row: WarrenWatchRowOut }) {
  if (row.stop_price == null) return <TableCell className={`${NUM_CLASS} text-text-tertiary`}>—</TableCell>;
  const above = stopAboveEntry(row);
  const basis = row.stop_basis === "none" ? null : STOP_BASIS_LABEL[row.stop_basis];
  return (
    <TableCell className={`${PAD} whitespace-nowrap text-right`}>
      <span className="inline-flex items-center justify-end gap-1.5">
        {above && (
          <span title={stopAboveEntryNote(row)} aria-label={stopAboveEntryNote(row)} className="inline-flex text-text-tertiary">
            <Info size={14} aria-hidden="true" />
          </span>
        )}
        <span className="font-mono text-text-primary">{fmtMoney(row.stop_price)}</span>
        {basis && (
          <Badge size="compact" tone="neutral">
            {basis}
          </Badge>
        )}
      </span>
    </TableCell>
  );
}

export function WarrenWatchTable({ rows }: Props) {
  const [nowMs] = useState(() => Date.now());
  return (
    <Table containerClassName="max-h-[70vh] overflow-auto">
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className={`${HEAD_CLASS} w-20`}>Ticker</TableHead>
          <TableHead className={HEAD_CLASS}>Signal</TableHead>
          <TableHead className={HEAD_CLASS}>Instruction</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Entry</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Last</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>P/L %</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Stop</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Stop dist.</TableHead>
          <TableHead className={HEAD_CLASS}>Status</TableHead>
          <TableHead className={HEAD_CLASS}>Last signal</TableHead>
          <TableHead className={HEAD_CLASS}>Last updated</TableHead>
          <TableHead className={`${HEAD_CLASS} w-px`}>
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sortByLatestArrow(rows).map((row) => (
          <TableRow key={row.ticker} interactive onClick={(e) => handleRowClick(e, row.ticker)}>
            <TableCell className={PAD}>
              <a
                href={`/tickers/${row.ticker}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-sm font-semibold text-text-primary"
              >
                {row.ticker}
              </a>
              {row.profile !== "any" && <p className="text-xs uppercase text-text-tertiary">{row.profile} profile</p>}
            </TableCell>
            <TableCell className={`${PAD} whitespace-nowrap`}>
              <SignalPill row={row} />
            </TableCell>
            <InstructionCell row={row} />
            <EntryCell row={row} nowMs={nowMs} />
            <LastCell row={row} />
            <PlCell row={row} />
            <StopCell row={row} />
            <StopDistanceCell row={row} />
            <StatusCell row={row} />
            <TableCell className={`${PAD} whitespace-nowrap font-mono text-xs text-text-secondary`} title={lastEntryRefreshTitle(row)}>
              {fmtEtStamp(row.latest_arrow_at)}
              {fmtBarsAgo(row.age_bars) && <span className="block font-sans text-text-tertiary">{fmtBarsAgo(row.age_bars)}</span>}
            </TableCell>
            <TableCell className={`${PAD} whitespace-nowrap font-mono text-xs text-text-secondary`}>{fmtEtStamp(row.last_updated_at)}</TableCell>
            <TableCell className="pr-0 text-right">
              <WarrenWatchRemoveButton ticker={row.ticker} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
