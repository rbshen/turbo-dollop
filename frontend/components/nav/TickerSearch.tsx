"use client";

import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TickerSearchResult } from "@/lib/api/types";

const DEBOUNCE_MS = 300;

export function TickerSearch() {
  const [value, setValue] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value.trim()), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [value]);

  // Keying the SWR request on the debounced query string itself (rather
  // than tracking a separate "latest request id") sidesteps the classic
  // out-of-order-response race for free: SWR caches per key, so a slow
  // response for an earlier keystroke's query can only ever update that
  // stale key's own cache entry, never the currently-rendered one.
  const query = debounced.length > 0 ? debounced : null;
  const { data: results, error, isLoading } = useApiResource<TickerSearchResult[]>(
    query ? `/tickers/search?q=${encodeURIComponent(query)}` : null
  );

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  // Reset the highlighted index whenever the result set changes, adjusted
  // during render (React's recommended pattern for derived state) rather
  // than in an effect -- avoids an extra cascading render on every keystroke.
  const [prevResults, setPrevResults] = useState(results);
  if (results !== prevResults) {
    setPrevResults(results);
    setHighlighted(-1);
  }

  function selectResult(result: TickerSearchResult) {
    // New tab, not a client-side route push -- the search box's own
    // page/tab stays put (per the ticker-search UX decision).
    window.open(`/tickers/${result.symbol}`, "_blank", "noopener,noreferrer");
    setValue("");
    setDebounced("");
    setOpen(false);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!results || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      selectResult(results[highlighted >= 0 ? highlighted : 0]);
    }
  }

  const showDropdown = open && query !== null;

  return (
    <div ref={containerRef} className="relative">
      <input
        type="text"
        value={value}
        onChange={(e) => {
          setValue(e.target.value.toUpperCase());
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder="Search ticker…"
        role="combobox"
        aria-expanded={showDropdown}
        aria-autocomplete="list"
        aria-controls="ticker-search-listbox"
        className="h-8 w-40 rounded-md border border-border-input bg-surface px-3 text-xs text-text-primary placeholder:text-text-tertiary outline-none focus:border-brand sm:w-56"
      />

      {showDropdown && (
        <div
          id="ticker-search-listbox"
          role="listbox"
          aria-label="Ticker search results"
          className="absolute right-0 z-20 mt-1 max-h-80 w-80 overflow-y-auto rounded-md border border-border-input bg-surface p-1 shadow-lg"
        >
          {isLoading && !results ? (
            <p className="px-2 py-1.5 text-xs text-text-tertiary">Searching…</p>
          ) : error ? (
            <p className="px-2 py-1.5 text-xs text-negative">Search failed — try again</p>
          ) : !results || results.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-text-tertiary">No matches for &ldquo;{debounced}&rdquo;</p>
          ) : (
            results.map((r, i) => (
              <button
                key={r.symbol}
                type="button"
                role="option"
                aria-selected={i === highlighted}
                onMouseEnter={() => setHighlighted(i)}
                onClick={() => selectResult(r)}
                className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs ${
                  i === highlighted ? "bg-surface-2" : ""
                }`}
              >
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="shrink-0 font-mono font-semibold text-text-primary">{r.symbol}</span>
                  {r.name && <span className="truncate text-text-secondary">{r.name}</span>}
                </span>
                {r.exchange && <span className="shrink-0 text-text-tertiary">{r.exchange}</span>}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
