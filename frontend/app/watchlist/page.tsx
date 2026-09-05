"use client";

import { useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { SegmentedControl } from "@/components/shared/SegmentedControl";
import { WatchlistTable } from "@/components/watchlist/WatchlistTable";
import type { WatchlistSortField } from "@/lib/api/types";
import { updateWatchlist, useWatchlists } from "@/lib/hooks/useWatchlists";
import { useWatchlistRows } from "@/lib/hooks/useWatchlistRows";

// Design handoff's own 6-option list (Ticker/Price/Change %/Market
// Cap/Beta/P-E) plus the app's existing score-based sort fields, which
// predate this redesign and stay available -- restyling shouldn't drop
// working functionality the mockup's sample data simply didn't exercise.
// Price/Change % removed (2026-08-03) along with the columns themselves --
// see WatchlistSortField's own comment. "5Y vs SPY" (perf_5y_vs_spy_pct)
// removed (2026-09-05), alongside the same field's column removal in
// WatchlistTable.tsx -- no longer a valid WatchlistSortField value at all
// (see that type's own comment), not just hidden from this list.
const SORT_FIELD_OPTIONS: { value: WatchlistSortField; label: string }[] = [
  { value: "ticker", label: "Ticker" },
  { value: "market_cap", label: "Market Cap" },
  { value: "beta", label: "Beta" },
  { value: "pe_ratio", label: "P/E" },
  { value: "overall_score", label: "Overall score" },
  { value: "step1_score", label: "Financials score" },
  { value: "step2_score", label: "Growth Rate score" },
  { value: "step4_score", label: "Profitability score" },
  { value: "step5_score", label: "Debt score" },
  { value: "blended_score", label: "Trend" },
  { value: "ad_divergence_swing_date", label: "A/D Div." },
  { value: "sma20_position_pct", label: "20SMA" },
  { value: "sma50_position_pct", label: "50SMA" },
  { value: "sma200_position_pct", label: "200SMA" },
];

const VALID_SORT_FIELDS = new Set(SORT_FIELD_OPTIONS.map((opt) => opt.value));

// Matches the backend's own Watchlist.sort_field default (core/models.py) --
// used as the fallback below for a watchlist whose persisted sort_field is
// no longer a valid option (e.g. "perf_5y_vs_spy_pct", removed above): the
// backend persists sort_field as an opaque string with no server-side
// validation (see WatchlistSortField's own comment), so an old value simply
// never becomes invalid there on its own. Without this fallback, the <select>
// below would render with no option visibly selected and the table would
// sort by a field with no live column or control for it -- this keeps both
// sane until the user next picks a real sort field, at which point the
// normal onChange persists a valid value again.
const DEFAULT_SORT_FIELD: WatchlistSortField = "overall_score";

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "watchlist";
}

export default function WatchlistPage() {
  const { data: watchlists, error } = useWatchlists();
  // null until the user picks a tab -- defaults to the first watchlist
  // below rather than needing an effect to sync it once data loads.
  const [manualActiveId, setManualActiveId] = useState<number | null>(null);

  const mostRecentlyCreated = watchlists?.length
    ? watchlists.reduce((latest, w) => (w.created_at > latest.created_at ? w : latest))
    : null;
  const activeId = manualActiveId ?? mostRecentlyCreated?.id ?? null;
  const active = watchlists?.find((w) => w.id === activeId) ?? null;
  const { data: rows, error: rowsError } = useWatchlistRows(active?.id ?? null);

  // Static "Fathom Watchlist" (set via layout.tsx metadata) covers the
  // loading/empty/error states -- this only overrides it once a specific
  // list is actually resolved, per the per-page title convention.
  useEffect(() => {
    if (active) {
      document.title = `Fathom Watchlist ${active.name}`;
    }
  }, [active]);

  function handleExport() {
    if (!active || !rows) return;
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
    a.download = `${slugify(active.name)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (error) {
    return (
      <PageContainer className="py-12">
        <p className="text-sm text-negative">Couldn&apos;t load watchlists — {error.message}</p>
      </PageContainer>
    );
  }

  if (!watchlists) {
    return (
      <PageContainer className="py-12">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Watchlists…</p>
      </PageContainer>
    );
  }

  if (watchlists.length === 0 || !active) {
    return (
      <PageContainer className="py-12">
        <p className="text-sm text-text-tertiary">No watchlists yet — add a ticker from its page to create one.</p>
      </PageContainer>
    );
  }

  // Falls back to DEFAULT_SORT_FIELD when `active.sort_field` is a value no
  // longer offered above (see that constant's own comment) -- drives both
  // the <select>'s displayed value and what the table actually sorts by, so
  // neither shows/uses a field with no corresponding option or column. Does
  // NOT persist the fallback back to the watchlist itself -- the next real
  // onChange below does that naturally.
  const effectiveSortField = VALID_SORT_FIELDS.has(active.sort_field) ? active.sort_field : DEFAULT_SORT_FIELD;
  const displayWatchlist = active.sort_field === effectiveSortField ? active : { ...active, sort_field: effectiveSortField };

  return (
    <PageContainer className="space-y-6 pb-12 pt-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl font-semibold text-text-primary">Watchlists</h1>
          <p className="text-xs text-text-tertiary">
            {active.name} · {active.tickers.length} ticker{active.tickers.length === 1 ? "" : "s"}
          </p>
        </div>
        <button
          type="button"
          onClick={handleExport}
          disabled={!rows || rows.length === 0}
          className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          Export List · TradingView
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          value={String(active.id)}
          onChange={(v) => setManualActiveId(Number(v))}
          options={watchlists.map((w) => ({ value: String(w.id), label: w.name }))}
        />
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Sort by</span>
          <select
            value={effectiveSortField}
            onChange={(e) => updateWatchlist(active.id, { sort_field: e.target.value as WatchlistSortField })}
            className="h-8 rounded-md border border-border-input bg-surface px-2 text-xs text-text-primary focus:border-brand focus:outline-none"
          >
            {SORT_FIELD_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => updateWatchlist(active.id, { sort_direction: active.sort_direction === "asc" ? "desc" : "asc" })}
            className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-2 text-xs text-text-secondary transition-colors hover:border-brand hover:text-text-primary"
            title={active.sort_direction === "asc" ? "Ascending" : "Descending"}
          >
            {active.sort_direction === "asc" ? "↑ Asc" : "↓ Desc"}
          </button>
        </div>
      </div>

      <WatchlistTable watchlist={displayWatchlist} rows={rows} error={rowsError} />
    </PageContainer>
  );
}
