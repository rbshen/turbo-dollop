"use client";

// Styleguide reference for the Screener results controls (session 10, part 3):
// the real Sort row, Pagination, saved-views bar and multi-select trigger, with
// local state and mock data only. The saved-views bar is the real
// SavedFiltersBarView with an in-memory list and fake save/delete, so nothing
// here can reach the live backend. See "Screener results controls" in
// docs/design-system.md.
import { useState, type ReactNode } from "react";

import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import { Pagination } from "@/components/screener/Pagination";
import { SortControls } from "@/components/screener/SortControls";
import type { SortDirection, SortField } from "@/lib/screenerFilters";
import { MockSavedViewsBar, type MockSavedViewsBarProps } from "./MockSavedViewsBar";
import {
  BUTTON_WIDTH,
  DIRECTION_BUTTON_WIDTH,
  LONGEST_SORT_LABEL,
  NAMING_BUTTON_ROW,
  OVERWRITE_BUTTON_ROW,
  SELECT_MEDIUM_WIDTH,
  SELECT_WIDE_WIDTH,
  overwriteMessageLines,
  selectTextRoom,
} from "./screenerResultsMetrics";
import { SIDEBAR_CONTENT_WIDTH, SIDEBAR_WIDTH } from "./screenerSidebarMetrics";

function Frame({ title, note, children, testId }: { title: string; note?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId}>
      <h3 className="mb-1 text-xs font-semibold text-text-secondary">{title}</h3>
      {note && <p className="mb-3 max-w-3xl text-xs text-text-tertiary">{note}</p>}
      {children}
    </div>
  );
}

// ---- Sort row ---------------------------------------------------------------

function SortDemo({ width }: { width?: number }) {
  const [field, setField] = useState<SortField>("overall_score");
  const [direction, setDirection] = useState<SortDirection>("desc");
  const row = (
    <SortControls
      sortField={field}
      sortDirection={direction}
      onChange={(f, d) => {
        setField(f);
        setDirection(d);
      }}
    />
  );
  return width ? (
    <div style={{ width }} className="box-content border-x border-dashed border-border-subtle">
      {row}
    </div>
  ) : (
    <div className="max-w-3xl">{row}</div>
  );
}

// ---- Pagination -------------------------------------------------------------

function PagerDemo({ start, total, caption }: { start: number; total: number; caption: string }) {
  const [page, setPage] = useState(start);
  return (
    <div data-testid={`pager-${start}-of-${total}`}>
      <p className="mb-1 text-xs text-text-tertiary">{caption}</p>
      <Pagination page={page} nPages={total} onPage={setPage} />
    </div>
  );
}

// ---- Saved-views bar --------------------------------------------------------

interface BarDemoProps extends MockSavedViewsBarProps {
  testId: string;
  caption: string;
  width: number;
  minHeight?: number;
}

function BarDemo({ testId, caption, width, minHeight, ...bar }: BarDemoProps) {
  return (
    <div data-testid={testId}>
      <p className="mb-1 text-xs text-text-tertiary">
        {caption} <span className="font-mono">({width}px)</span>
      </p>
      <div style={{ width, minHeight }} className="box-content border-x border-dashed border-border-subtle">
        <MockSavedViewsBar {...bar} />
      </div>
    </div>
  );
}

// ---- Multi-select trigger ---------------------------------------------------

const SECTORS = ["Energy", "Financials", "Healthcare", "Industrials", "Technology", "Utilities"].map((s) => ({ value: s, label: s }));

function MultiDemo({ initial, name }: { initial: string[]; name: string }) {
  const [selected, setSelected] = useState(initial);
  return (
    <div data-testid={`multi-${initial.length}`}>
      <p className="mb-1 text-xs text-text-tertiary">
        {initial.length === 0 ? "None selected" : initial.length === 1 ? "One selected" : "Several selected"}; accessible name{" "}
        <span className="font-mono">{name}</span>
      </p>
      <MultiSelectDropdown label="Sector" options={SECTORS} selected={selected} onChange={setSelected} />
    </div>
  );
}

// ---- Computed notes ---------------------------------------------------------

function ComputedNote() {
  return (
    <div className="max-w-3xl text-xs text-text-secondary" data-testid="results-metrics-note">
      <p className="mb-2 text-text-tertiary">
        Computed from the font&apos;s glyph advance widths and the class tokens, not measured in a browser. The saved-views bar sits outside the filter
        cards, so on the page it is {SIDEBAR_WIDTH}px wide; {SIDEBAR_CONTENT_WIDTH}px is the tighter case and is what the frames above use.
      </p>
      <table className="font-mono text-[11px]">
        <tbody>
          <tr>
            <td className="py-0.5 pr-4 font-sans">Sort select, medium ({SELECT_MEDIUM_WIDTH}px) text room</td>
            <td className="py-0.5">
              {selectTextRoom(SELECT_MEDIUM_WIDTH)}px, clips &ldquo;{LONGEST_SORT_LABEL.text}&rdquo; ({LONGEST_SORT_LABEL.width}px)
            </td>
          </tr>
          <tr>
            <td className="py-0.5 pr-4 font-sans">Sort select, wide ({SELECT_WIDE_WIDTH}px) text room</td>
            <td className="py-0.5">{selectTextRoom(SELECT_WIDE_WIDTH)}px, fits (chosen)</td>
          </tr>
          <tr>
            <td className="py-0.5 pr-4 font-sans">Direction button, Desc / Asc</td>
            <td className="py-0.5">
              {DIRECTION_BUTTON_WIDTH.desc.toFixed(0)}px / {DIRECTION_BUTTON_WIDTH.asc.toFixed(0)}px wide, 36px high
            </td>
          </tr>
          <tr>
            <td className="py-0.5 pr-4 font-sans">Naming: Input</td>
            <td className="py-0.5">{SIDEBAR_CONTENT_WIDTH}px (w-full), on its own row</td>
          </tr>
          <tr>
            <td className="py-0.5 pr-4 font-sans">Naming: Save + Cancel row, widest</td>
            <td className="py-0.5">
              {NAMING_BUTTON_ROW.toFixed(0)}px of {SIDEBAR_CONTENT_WIDTH}px (Save {BUTTON_WIDTH.save.toFixed(0)}, &ldquo;Save failed&rdquo;{" "}
              {BUTTON_WIDTH.saveFailed.toFixed(0)}, Cancel {BUTTON_WIDTH.cancel.toFixed(0)})
            </td>
          </tr>
          <tr>
            <td className="py-0.5 pr-4 font-sans">Overwrite: buttons row, widest</td>
            <td className="py-0.5">
              {OVERWRITE_BUTTON_ROW.toFixed(0)}px of {SIDEBAR_CONTENT_WIDTH}px; message wraps to {overwriteMessageLines(SIDEBAR_CONTENT_WIDTH)} lines
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function ScreenerResultsControlsMock() {
  return (
    <div className="space-y-10" data-testid="screener-results-controls-mock">
      <div className="max-w-3xl text-xs text-text-tertiary">
        <p>
          The real Sort row, Pagination, saved-views bar and multi-select trigger, with local state and mock data; the live Screener uses the same
          components. Saving and deleting here change only an in-memory list. Try Escape on the open popover, Tab and Enter through the rows, a name with a
          &ldquo;/&rdquo;, and a name that already exists.
        </p>
      </div>

      <Frame title="Sort row" testId="sort-section" note="Results header width. The field is a wide boxed Select under a real “Sort by” label; the direction is one outline toggle.">
        <SortDemo />
      </Frame>

      <Frame title="Sort row at a narrow width (320px)" note="Wraps rather than overflowing; the Select shrinks to the row.">
        <SortDemo width={320} />
      </Frame>

      <Frame title="Pagination" testId="pagination-section" note="The current page is neutral selected (surface-2 fill, primary text) with aria-current=page; Prev and Next are caret icons.">
        <div className="space-y-4">
          <PagerDemo start={1} total={10} caption="First page: Prev is disabled" />
          <PagerDemo start={5} total={10} caption="Middle page" />
          <PagerDemo start={10} total={10} caption="Last page: Next is disabled" />
        </div>
      </Frame>

      <Frame title="Saved-views bar" testId="saved-views-section" note="The bar is always one column. Each frame is the real component with its own in-memory list.">
        <div className="flex flex-wrap items-start gap-x-10 gap-y-8">
          <BarDemo testId="bar-idle" caption="Idle" width={SIDEBAR_CONTENT_WIDTH} />
          <BarDemo
            testId="bar-open"
            caption="Popover open, an active view"
            width={SIDEBAR_CONTENT_WIDTH}
            minHeight={300}
            defaultListOpen
            defaultActiveName="Quality compounders"
          />
          <BarDemo testId="bar-naming-222" caption="Naming step" width={SIDEBAR_CONTENT_WIDTH} defaultSaveStep="naming" defaultName="Stage 2 leaders" />
          <BarDemo testId="bar-naming-256" caption="Naming step" width={SIDEBAR_WIDTH} defaultSaveStep="naming" defaultName="Stage 2 leaders" />
          <BarDemo testId="bar-naming-slash" caption="Naming step, name with a slash" width={SIDEBAR_CONTENT_WIDTH} defaultSaveStep="naming" defaultName="growth/value" />
          <BarDemo
            testId="bar-overwrite"
            caption="Overwrite confirm"
            width={SIDEBAR_CONTENT_WIDTH}
            defaultSaveStep="confirmOverwrite"
            defaultName="Quality compounders"
          />
        </div>
      </Frame>

      <Frame title="Multi-select trigger" testId="multi-section" note="The accessible name is “<label>: <summary>”; the visible text and the caret (decorative) are unchanged in meaning.">
        <div className="flex flex-wrap items-start gap-x-10 gap-y-6">
          <MultiDemo initial={[]} name="Sector: none selected" />
          <MultiDemo initial={["Technology"]} name="Sector: Technology" />
          <MultiDemo initial={["Energy", "Healthcare", "Technology"]} name="Sector: 3 selected" />
        </div>
      </Frame>

      <Frame title="Computed sizes">
        <ComputedNote />
      </Frame>
    </div>
  );
}
