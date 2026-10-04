"use client";

import { useState } from "react";
import { Check, Minus, X } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { SortHeader } from "@/components/ui/sort-header";
import { TableCell, TableHead, TableRow } from "@/components/ui/table";
import { removeTickerFromWatchlist } from "@/lib/hooks/useWatchlists";
import { cn } from "@/lib/utils";
import type { SortDirection } from "@/lib/screenerFilters";

// Pieces shared by the stock table (WatchlistTable) and the ETF table (EtfWatchlistTable) of the Watchlists page, so
// the two stay identical in header look, sort click target, remove flow and loading skeleton.

// Sticky header cell: a bounded two-axis scroll box plus `top-0` inside it (see the long comment in WatchlistTable.tsx
// for why the sticky context must be the table's own container). `bg-page`, not a surface fill, on each cell: sticky is
// applied per-th, and an unpainted cell would let body rows show through as they scroll underneath.
export const HEAD_CLASS = "sticky top-0 z-20 bg-page";

/** Click-to-sort column header over any table's field set: the priority numeral only appears once 2+ rules are
 * active, `sort` goes onto the th for aria-sort. `onSort(field)` applies the table's own click cycle. */
export function SortableColumnHead<F extends string>({
  field,
  rules,
  onSort,
  className,
  align,
  children,
}: {
  field: F;
  rules: { field: F; direction: SortDirection }[];
  onSort: (field: F) => void;
  className?: string;
  align?: "left" | "right";
  children: React.ReactNode;
}) {
  const priority = rules.findIndex((r) => r.field === field);
  const active = priority !== -1;
  const direction = active ? rules[priority].direction : undefined;
  const ariaSort: "ascending" | "descending" | "none" = !active ? "none" : direction === "asc" ? "ascending" : "descending";
  return (
    <TableHead className={className} sort={ariaSort}>
      <SortHeader
        label={children}
        active={active}
        direction={direction}
        priority={active && rules.length > 1 ? priority + 1 : undefined}
        onClick={() => onSort(field)}
        align={align}
      />
    </TableHead>
  );
}

// idle -> confirming (click the minus) -> removing (click the check) -> idle (mutate() flips the row out of `rows`) or
// error (auto-reverts after 4s).
export type RemoveState = "idle" | "confirming" | "removing" | "error";

/** The remove flow's state for one watchlist. Keyed by ticker only and reset whenever the watchlist changes, so a
 * lingering "confirming"/"error" never bleeds onto a same-ticker row of another list (adjusted during render, the
 * "storing information from previous renders" pattern, rather than in an effect). */
export function useRemoveFlow(watchlistId: number) {
  const [removeState, setRemoveState] = useState<Record<string, RemoveState>>({});
  const [lastWatchlistId, setLastWatchlistId] = useState(watchlistId);
  if (watchlistId !== lastWatchlistId) {
    setLastWatchlistId(watchlistId);
    setRemoveState({});
  }

  async function confirmRemove(ticker: string) {
    setRemoveState((prev) => ({ ...prev, [ticker]: "removing" }));
    try {
      await removeTickerFromWatchlist(watchlistId, ticker);
    } catch {
      setRemoveState((prev) => ({ ...prev, [ticker]: "error" }));
      setTimeout(() => setRemoveState((prev) => ({ ...prev, [ticker]: "idle" })), 4000);
    }
  }

  return { removeState, setRemoveState, confirmRemove };
}

/** The trailing remove cell: the minus button, then Confirm (check) and Cancel (x). Clicks never reach the row. */
export function RemoveCell({
  ticker,
  watchlistName,
  flow,
}: {
  ticker: string;
  watchlistName: string;
  flow: ReturnType<typeof useRemoveFlow>;
}) {
  const { removeState, setRemoveState, confirmRemove } = flow;
  return (
    <TableCell className="text-center">
      {(removeState[ticker] ?? "idle") === "confirming" ? (
        <div className="flex items-center justify-center gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            onClick={(e) => {
              e.stopPropagation();
              confirmRemove(ticker);
            }}
            aria-label={`Confirm: remove ${ticker} from ${watchlistName}`}
            title={`Remove ${ticker} from ${watchlistName}?`}
            className="border-warn/50 text-warn hover:border-warn hover:text-warn"
          >
            <Check size={16} aria-hidden="true" />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={(e) => {
              e.stopPropagation();
              setRemoveState((prev) => ({ ...prev, [ticker]: "idle" }));
            }}
            aria-label="Cancel"
            title="Cancel"
            className="text-text-tertiary"
          >
            <X size={16} aria-hidden="true" />
          </Button>
        </div>
      ) : (
        <Button
          variant="outline"
          size="icon-sm"
          onClick={(e) => {
            e.stopPropagation();
            setRemoveState((prev) => ({ ...prev, [ticker]: "confirming" }));
          }}
          disabled={removeState[ticker] === "removing"}
          aria-label={`Remove ${ticker}`}
          title={removeState[ticker] === "error" ? "Failed to remove — retry" : `Remove ${ticker}`}
          className={cn(
            removeState[ticker] === "error"
              ? "border-negative text-negative hover:border-negative"
              : "text-text-tertiary hover:border-negative hover:text-negative"
          )}
        >
          <Minus size={16} aria-hidden="true" />
        </Button>
      )}
    </TableCell>
  );
}

/** Five pulsing rows spanning `columns`, the loading state of both tables. */
export function SkeletonRows({ columns }: { columns: number }) {
  return (
    <>
      {Array.from({ length: 5 }, (_, i) => (
        <TableRow key={i} className="animate-pulse bg-surface-2">
          <TableCell colSpan={columns} />
        </TableRow>
      ))}
    </>
  );
}

export function openTickerPage(ticker: string) {
  window.open(`/tickers/${ticker}`, "_blank", "noopener,noreferrer");
}
