"use client";

import { useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs } from "@/components/ui/tabs";
import { ExportMenu } from "@/components/watchlist/ExportMenu";
import { WatchlistDeleteButton } from "@/components/watchlist/WatchlistDeleteButton";
import { WatchlistNameEditor } from "@/components/watchlist/WatchlistNameEditor";
import { EtfWatchlistTable } from "@/components/watchlist/EtfWatchlistTable";
import { WatchlistTable } from "@/components/watchlist/WatchlistTable";
import { DEFAULT_ETF_SORT_RULES, ETF_SORT_STORAGE_KEY_PREFIX, parseEtfSortRules, type EtfSortRule } from "@/lib/etfWatchlistSort";
import { useEtfWatchlistRows } from "@/lib/hooks/useEtfWatchlistRows";
import { useWatchlists } from "@/lib/hooks/useWatchlists";
import { useWatchlistRows } from "@/lib/hooks/useWatchlistRows";
import { ETF_WATCHLIST_NAME } from "@/lib/monitoredWatchlists";
import { buildTradingViewText } from "@/lib/watchlistExport";
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

// The ETF table keeps its own rules under its own key (a different field set and default), so nothing stored for the
// stock table under the same list id can reach it; an unreadable or foreign value falls back to the ETF default.
function loadEtfSortRules(watchlistId: number): EtfSortRule[] {
  if (typeof window === "undefined") return DEFAULT_ETF_SORT_RULES;
  try {
    return parseEtfSortRules(window.localStorage.getItem(`${ETF_SORT_STORAGE_KEY_PREFIX}${watchlistId}`));
  } catch {
    return DEFAULT_ETF_SORT_RULES;
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
  // The list named "ETF" has its own table and its own rows endpoint; every other list keeps the stock table. Only the
  // active view's rows are fetched.
  const isEtfList = active?.name === ETF_WATCHLIST_NAME;
  const { data: stockRows, error: stockRowsError } = useWatchlistRows(active && !isEtfList ? active.id : null);
  const { data: etfRows, error: etfRowsError } = useEtfWatchlistRows(active && isEtfList ? active.id : null);
  // What the TradingView export and its enabled state need from either kind of row. An ETF row has no sector.
  const rows = isEtfList ? etfRows : stockRows;
  const exportRows = rows?.map((r) => ({ ticker: r.ticker, exchange: r.exchange, sector: "sector" in r ? r.sector : null }));

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

  // The same per-list reload for the ETF table's rules.
  const [etfSortState, setEtfSortState] = useState<{ activeId: number | null; rules: EtfSortRule[] }>({
    activeId: null,
    rules: DEFAULT_ETF_SORT_RULES,
  });
  if (activeId !== etfSortState.activeId) {
    setEtfSortState({ activeId, rules: activeId != null ? loadEtfSortRules(activeId) : DEFAULT_ETF_SORT_RULES });
  }
  const etfSortRules = etfSortState.rules;

  function handleEtfSortRulesChange(rules: EtfSortRule[]) {
    setEtfSortState({ activeId, rules });
    if (activeId == null) return;
    try {
      window.localStorage.setItem(`${ETF_SORT_STORAGE_KEY_PREFIX}${activeId}`, JSON.stringify(rules));
    } catch {
      // localStorage unavailable: the in-memory state still updates for this session.
    }
  }

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

  function handleExportTradingView() {
    if (!active || !exportRows) return;
    // Rows go in raw fetch order, not the on-screen sort. The sector grouping is shared with the multi-list export.
    const { content } = buildTradingViewText(exportRows);

    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slugify(active.name)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleExportThinkorswim() {
    if (!active) return;
    // Not routed through lib/api/client.ts's apiFetch -- that helper always
    // parses the response as JSON, but this is a CSV file download.
    const res = await fetch(`/api/watchlists/${active.id}/export/thinkorswim`);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slugify(active.name)}_thinkorswim.csv`;
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
    <PageContainer className="space-y-6 pb-12">
      <PageHeader
        title="Watchlists"
        actions={
          <ExportMenu
            disabled={!exportRows || exportRows.length === 0}
            onExportTradingView={handleExportTradingView}
            onExportThinkorswim={handleExportThinkorswim}
          />
        }
      />

      {/* A user can create an unbounded number of watchlists (no cap on
          count, only WATCHLIST_CAPACITY on tickers-per-list), so this is
          Tabs (unlimited items, horizontal overflow scroll) rather than
          SegmentedControl (documented for a small 2-6-option fixed set,
          e.g. a universe/period toggle) -- see the design-system session
          5d report for the full reasoning. */}
      <Tabs
        value={String(active.id)}
        onValueChange={(v) => setManualActiveId(Number(v))}
        items={watchlists.map((w) => ({ value: String(w.id), label: w.name }))}
      />

      {/* Each key is prefixed (not bare active.id) since these are two
          sibling elements -- React requires unique keys per sibling
          regardless of component type, and a shared key across both
          caused a real duplicate-key reconciliation bug (stale editors
          from previously-active tabs piling up instead of being
          replaced). The remount itself still drops any in-progress
          edit/delete confirmation on tab switch, rather than an editor
          mid-rename silently re-targeting a different watchlist
          underneath the user. */}
      <div className="flex items-center gap-2">
        <WatchlistNameEditor key={`name-${active.id}`} watchlist={active} />
        {/* The "ETF" list is permanent (the backend refuses to delete it). */}
        {active.name !== ETF_WATCHLIST_NAME && (
          <WatchlistDeleteButton key={`delete-${active.id}`} watchlist={active} onDeleted={() => setManualActiveId(null)} />
        )}
      </div>

      {isEtfList ? (
        <EtfWatchlistTable
          watchlist={active}
          rows={etfRows}
          error={etfRowsError}
          sortRules={etfSortRules}
          onSortRulesChange={handleEtfSortRulesChange}
        />
      ) : (
        <WatchlistTable
          watchlist={active}
          rows={stockRows}
          error={stockRowsError}
          sortRules={sortRules}
          onSortRulesChange={handleSortRulesChange}
        />
      )}
    </PageContainer>
  );
}
