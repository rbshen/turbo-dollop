"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { apiFetch, errorDetail } from "@/lib/api/client";
import type { WatchlistExportListOut, WatchlistOut } from "@/lib/api/types";
import {
  buildMultiExport,
  EXPORT_FORMAT_OPTIONS,
  exportResultParts,
  multiExportFilename,
  type ExportFormat,
} from "@/lib/watchlistExport";

const naturalNames = new Intl.Collator("en", { numeric: true });

type ResultParts = ReturnType<typeof exportResultParts>;

/** GET /api/watchlists/export-data for `ids`: stored data only, one profile read per ticker, no FMP call. */
export function loadExportLists(ids: number[]): Promise<WatchlistExportListOut[]> {
  return apiFetch<WatchlistExportListOut[]>(`/watchlists/export-data?${ids.map((id) => `ids=${id}`).join("&")}`);
}

/** Hands `content` to the browser as a file download (an anchor on a Blob URL, like the single-list export). */
export function downloadTextFile(filename: string, content: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

interface Props {
  watchlists: WatchlistOut[];
  onClose: () => void;
  // Styleguide seams (the page passes none): `loadLists` and `download` swap the request and the file hand-off so a mock
  // can never reach the backend; the default* props start the panel in a given state so each can be drawn at once.
  loadLists?: (ids: number[]) => Promise<WatchlistExportListOut[]>;
  download?: (filename: string, content: string, mime: string) => void;
  defaultSelected?: number[];
  defaultFormat?: ExportFormat;
  defaultResult?: ResultParts;
  defaultError?: string;
}

/** The "Export multiple lists" panel (docs/specs/watchlist-export.md): tick lists, pick ONE format, get ONE file. The page
 * renders it inline under its header when the Export menu's third item is chosen. */
export function MultiExportPanel({
  watchlists,
  onClose,
  loadLists = loadExportLists,
  download = downloadTextFile,
  defaultSelected = [],
  defaultFormat = "tradingview",
  defaultResult,
  defaultError,
}: Props) {
  const [selected, setSelected] = useState<Set<number>>(() => new Set(defaultSelected));
  const [format, setFormat] = useState<ExportFormat>(defaultFormat);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ResultParts | null>(defaultResult ?? null);
  const [error, setError] = useState<string | null>(defaultError ?? null);

  const ordered = [...watchlists].sort((a, b) => naturalNames.compare(a.name, b.name));

  function toggle(id: number, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
    setResult(null);
    setError(null);
  }

  function setAll(on: boolean) {
    setSelected(on ? new Set(ordered.map((w) => w.id)) : new Set());
    setResult(null);
    setError(null);
  }

  async function runExport() {
    // The natural name order, not tick order, so the file is the same however the boxes were ticked.
    const ids = ordered.filter((w) => selected.has(w.id)).map((w) => w.id);
    if (ids.length === 0) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const lists = await loadLists(ids);
      const built = buildMultiExport(lists, format);
      if (built.symbolCount > 0) {
        const mime = format === "tradingview" ? "text/plain" : "text/csv";
        download(multiExportFilename(ids.length, format), built.content, mime);
      }
      setResult(exportResultParts(built, ids.length));
    } catch (e) {
      setError(errorDetail(e) ?? (e instanceof Error ? e.message : "Export failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Export multiple lists" className="space-y-4 rounded-md border border-border-input bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-text-primary">Export multiple lists</h2>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setAll(true)} disabled={busy || selected.size === ordered.length}>
            Select all
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAll(false)} disabled={busy || selected.size === 0}>
            Clear
          </Button>
        </div>
      </div>

      <div role="group" aria-label="Lists to export" className="grid max-h-64 gap-x-6 gap-y-2 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
        {ordered.map((w) => (
          <Checkbox
            key={w.id}
            checked={selected.has(w.id)}
            disabled={busy}
            onChange={(e) => toggle(w.id, e.target.checked)}
            label={
              <>
                {w.name} <span className="text-text-tertiary">({w.tickers.length})</span>
              </>
            }
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SegmentedControl aria-label="Export format" value={format} onValueChange={(v) => setFormat(v as ExportFormat)} options={EXPORT_FORMAT_OPTIONS} />
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
          <Button variant="primary" size="sm" onClick={runExport} disabled={selected.size === 0 || busy}>
            {busy ? "Exporting…" : "Export"}
          </Button>
        </div>
      </div>

      <div role="status" aria-live="polite" className="min-h-4 text-xs text-text-secondary">
        {result && (
          <p>
            {result.summary}
            {result.notes.map((note) => ` · ${note}`).join("")}
            {result.skippedNote && <span className="text-caution">{` · ${result.skippedNote}`}</span>}
          </p>
        )}
        {error && <p className="text-negative">{`Couldn't export — ${error}`}</p>}
      </div>
    </section>
  );
}
