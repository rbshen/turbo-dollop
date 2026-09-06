"use client";

import { useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { SegmentedControl } from "@/components/shared/SegmentedControl";
import { WatchlistTable } from "@/components/watchlist/WatchlistTable";
import { useWatchlists } from "@/lib/hooks/useWatchlists";
import { useWatchlistRows } from "@/lib/hooks/useWatchlistRows";
import { DEFAULT_SORT_RULES, parseSortRules, type SortRule } from "@/lib/watchlistSort";

// Sort state moved off the old page-level <select>/direction-toggle
// dropdown entirely (2026-09-05) -- WatchlistTable's column headers are now
// directly clickable (see SortableHead there). Persistence moved from the
// backend's Watchlist.sort_field/sort_direction columns (a single
// field+direction pair, which can't represent a SortRule[] anyway) to
// localStorage, keyed per watchlist id -- the backend columns and
// PUT /api/watchlists/{id} are left untouched and simply go unused by the
// frontend from here on (see useWatchlists.ts's own comment).
const SORT_STORAGE_KEY_PREFIX = "fathom-watchlist-sort-";

function loadSortRules(watchlistId: number): SortRule[] {
  if (typeof window === "undefined") return DEFAULT_SORT_RULES;
  try {
    // parseSortRules (watchlistSort.ts) is the one place that knows how to
    // tell "no key at all" apart from a persisted explicit empty array --
    // see its own comment.
    return parseSortRules(window.localStorage.getItem(`${SORT_STORAGE_KEY_PREFIX}${watchlistId}`));
  } catch {
    // localStorage unavailable entirely (private window, blocked site
    // data) -- fall back to the default rather than throwing during render.
    return DEFAULT_SORT_RULES;
  }
}

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

  // Reloaded from localStorage whenever the active watchlist tab changes --
  // each watchlist has its own independent sort state (see
  // SORT_STORAGE_KEY_PREFIX above). Adjusted during render (React's
  // "storing information from previous renders" pattern) rather than in a
  // useEffect, the same reason manualActiveId's own comment above gives for
  // not needing an effect to sync state off a prop/derived-value change.
  const [sortState, setSortState] = useState<{ activeId: number | null; rules: SortRule[] }>({
    activeId: null,
    rules: DEFAULT_SORT_RULES,
  });
  if (activeId !== sortState.activeId) {
    setSortState({ activeId, rules: activeId != null ? loadSortRules(activeId) : DEFAULT_SORT_RULES });
  }
  const sortRules = sortState.rules;

  function handleSortRulesChange(rules: SortRule[]) {
    setSortState({ activeId, rules });
    if (activeId == null) return;
    try {
      window.localStorage.setItem(`${SORT_STORAGE_KEY_PREFIX}${activeId}`, JSON.stringify(rules));
    } catch {
      // localStorage unavailable (private window, blocked site data, quota) --
      // the in-memory state above still updates for this session, it just
      // won't survive a reload.
    }
  }

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
      </div>

      <WatchlistTable watchlist={active} rows={rows} error={rowsError} sortRules={sortRules} onSortRulesChange={handleSortRulesChange} />
    </PageContainer>
  );
}
