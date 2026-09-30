"use client";

// Styleguide reference for the Screener sidebar (session 10): one 256px boxed
// sidebar built from the real primitives (RangeField, FormField compact, Select,
// Checkbox chip, Input, Button outline, Badge, the real MultiSelectDropdown)
// with local state and mock data only. It mirrors the live sidebar in
// components/screener/; the owner chose boxed over underline from the earlier
// side-by-side version of this mock, and the underline sidebar is deleted. See
// "Screener filter sidebar (session 10)" in docs/design-system.md.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { CaretDown } from "@phosphor-icons/react";

import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { RangeField, type RangeValue } from "@/components/ui/range-field";
import { Select } from "@/components/ui/Select";
import {
  DEFAULT_FILTER_STATE,
  FUNDAMENTAL_FILTER_KEYS,
  MARKET_CAP_SUFFIXES,
  TECHNICAL_FILTER_KEYS,
  countActiveFilters,
  type ScreenerFilterState,
} from "@/lib/screenerFilters";
import {
  ERROR_ROW,
  HINT_ROW,
  PAIR_WIDTH,
  SIDEBAR_CONTENT_WIDTH,
  SIDEBAR_WIDTH,
  fundamentalSectionHeight,
  rangeGridHeight,
} from "./screenerSidebarMetrics";

type RangeKey = "overallScore" | "step1Score" | "step2Score" | "step4Score" | "step5Score" | "quote" | "marketCap" | "peRatio" | "growthRate" | "beta";

interface RangeSpec {
  key: RangeKey;
  label: string;
  unit?: string;
  marketCap?: boolean;
}

// The live order in FundamentalFilters, labels in sentence case, units per the
// owner's decision: Quote and Mkt cap USD, P/E "x", Growth "%", scores none.
const FUNDAMENTAL_RANGES: RangeSpec[] = [
  { key: "overallScore", label: "Overall" },
  { key: "step1Score", label: "Financials" },
  { key: "step2Score", label: "Growth rate" },
  { key: "step4Score", label: "Profitability" },
  { key: "step5Score", label: "Debt" },
  { key: "quote", label: "Quote", unit: "USD" },
  { key: "marketCap", label: "Mkt cap", unit: "USD", marketCap: true },
  { key: "peRatio", label: "P/E", unit: "x" },
  { key: "growthRate", label: "Growth", unit: "%" },
];
const BETA_RANGE: RangeSpec = { key: "beta", label: "Beta" };

const SECTOR_OPTIONS = ["Technology", "Healthcare", "Financial Services", "Energy", "Utilities"].map((s) => ({ value: s, label: s }));
const TYPE_OPTIONS = ["Standard", "Bank", "Insurance", "REIT/Property Developer"].map((s) => ({ value: s, label: s }));
const MOAT_OPTIONS = [
  { value: "wide_moat", label: "Wide moat" },
  { value: "narrow_moat", label: "Narrow moat" },
  { value: "no_moat", label: "No moat" },
  { value: "not_set", label: "Not set" },
];
const VALUATION_OPTIONS = [
  { value: "undervalued", label: "Undervalued" },
  { value: "fair", label: "Fair" },
  { value: "overvalued", label: "Overvalued" },
];
const SPY_OPTIONS = [
  { value: "outperform", label: "Outperform" },
  { value: "underperform", label: "Underperform" },
];
const STAGE_OPTIONS = [1, 2, 3, 4].map((n) => ({ value: `stage_${n}`, label: `Stage ${n}` }));

const SORT_OPTIONS = ["Overall score", "Financials score", "Growth rate score", "Quote", "Market cap", "P/E", "Growth rate"];

// A view a user might have saved, for the "Load sample view" button. Every
// range is a NEW object, like a view loaded from the API.
function sampleView(): ScreenerFilterState {
  return {
    ...DEFAULT_FILTER_STATE,
    overallScore: { min: 70, max: null },
    marketCap: { min: 1e9, max: 5e12 },
    peRatio: { min: null, max: 25 },
    sectors: ["Technology"],
    speculativeGrowth: true,
  };
}

function Readout({ value }: { value: RangeValue }) {
  return (
    <p className="mt-0.5 font-mono text-[11px] text-text-tertiary" data-testid="readout">
      min: {String(value.min)}, max: {String(value.max)}
    </p>
  );
}

function MockSection({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border-card bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-text-primary">{title}</h4>
        <span className="flex items-center gap-2">
          {count > 0 && (
            <Badge tone="neutral" size="compact" title={`${count} applied`}>
              {count}
            </Badge>
          )}
          <CaretDown size={12} className="shrink-0 text-text-tertiary" />
        </span>
      </div>
      <div className="pt-4">{children}</div>
    </div>
  );
}

function RangeRow({ spec, value, onChange }: { spec: RangeSpec; value: RangeValue; onChange: (v: RangeValue) => void }) {
  return (
    <div>
      <RangeField
        label={spec.label}
        unit={spec.unit}
        value={value}
        onChange={onChange}
        suffixes={spec.marketCap ? MARKET_CAP_SUFFIXES : undefined}
        min={spec.marketCap ? 0 : undefined}
        hint={spec.marketCap ? "Type 500M or 2B." : undefined}
      />
      <Readout value={value} />
    </div>
  );
}

function Sidebar() {
  const [filters, setFilters] = useState<ScreenerFilterState>(DEFAULT_FILTER_STATE);
  const [watchlist, setWatchlist] = useState("");
  const [universeAll, setUniverseAll] = useState(true);
  const [sort, setSort] = useState(SORT_OPTIONS[0]);
  const [descending, setDescending] = useState(true);
  const [naming, setNaming] = useState(false);
  const [viewName, setViewName] = useState("");

  const patch = (partial: Partial<ScreenerFilterState>) => setFilters((f) => ({ ...f, ...partial }));
  const watchlistInEffect = universeAll && watchlist !== "";
  const idp = "sg-side";

  return (
    <aside className="w-64 shrink-0 space-y-4" data-testid="sidebar-boxed" aria-label="Screener sidebar">
      <h3 className="text-xs font-semibold text-text-secondary">
        Sidebar <span className="font-normal text-text-tertiary">({SIDEBAR_WIDTH}px)</span>
      </h3>

      <div className="space-y-2">
        <FormField label="Sort" htmlFor={`${idp}-sort`} density="compact">
          <Select size="full" id={`${idp}-sort`} value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORT_OPTIONS.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </Select>
        </FormField>
        <Button variant="outline" size="sm" className="w-full" onClick={() => setDescending((d) => !d)}>
          {descending ? "↓ Desc" : "↑ Asc"}
        </Button>
      </div>

      <MockSection title="Watchlist" count={countActiveFilters(DEFAULT_FILTER_STATE, watchlistInEffect, [])}>
        <div className="flex flex-col gap-2">
          <FormField
            label="Limit results to"
            htmlFor={`${idp}-watchlist`}
            density="compact"
            applied={watchlistInEffect}
            disabled={!universeAll}
            hint={
              universeAll
                ? "Scopes every Fundamental and Technical filter to this watchlist's tickers."
                : 'Only applies when the universe toggle above is set to "All."'
            }
          >
            <Select size="full" id={`${idp}-watchlist`} value={watchlist} onChange={(e) => setWatchlist(e.target.value)}>
              <option value="">None</option>
              <option value="W1">W1</option>
              <option value="W2">W2</option>
              <option value="n">N scores passed</option>
            </Select>
          </FormField>
          <Checkbox variant="neutral" label="Mock: universe is All" checked={universeAll} onChange={(e) => setUniverseAll(e.target.checked)} />
        </div>
      </MockSection>

      <MockSection title="Fundamental" count={countActiveFilters(filters, false, FUNDAMENTAL_FILTER_KEYS)}>
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-y-3">
            {FUNDAMENTAL_RANGES.map((spec) => (
              <RangeRow
                key={spec.key}
                spec={spec}
                value={filters[spec.key] as RangeValue}
                onChange={(v) => patch({ [spec.key]: v })}
              />
            ))}
          </div>
          <div className="flex flex-col items-stretch gap-2 border-t border-border-subtle pt-3">
            <MultiSelectDropdown label="Sector" options={SECTOR_OPTIONS} selected={filters.sectors} onChange={(s) => patch({ sectors: s })} />
            <MultiSelectDropdown label="Company type" options={TYPE_OPTIONS} selected={filters.companyTypes} onChange={(s) => patch({ companyTypes: s })} />
            <MultiSelectDropdown label="Moat" options={MOAT_OPTIONS} selected={filters.moat} onChange={(s) => patch({ moat: s })} />
            <MultiSelectDropdown label="Valuation" options={VALUATION_OPTIONS} selected={filters.valuationVerdict} onChange={(s) => patch({ valuationVerdict: s })} />
            <Checkbox
              variant="chip"
              label="Speculative growth"
              className="w-full"
              checked={filters.speculativeGrowth}
              onChange={(e) => patch({ speculativeGrowth: e.target.checked })}
            />
          </div>
        </div>
      </MockSection>

      <MockSection title="Technical" count={countActiveFilters(filters, false, TECHNICAL_FILTER_KEYS)}>
        <div className="space-y-4">
          <RangeRow spec={BETA_RANGE} value={filters.beta} onChange={(v) => patch({ beta: v })} />
          <div className="flex flex-col items-stretch gap-2 border-t border-border-subtle pt-3">
            <MultiSelectDropdown label="5Y vs SPY" options={SPY_OPTIONS} selected={filters.vsSpy} onChange={(s) => patch({ vsSpy: s })} />
            <MultiSelectDropdown label="Weinstein stage" options={STAGE_OPTIONS} selected={filters.weinsteinStages} onChange={(s) => patch({ weinsteinStages: s })} />
            <Checkbox
              variant="chip"
              label="BB + RSI entry (2h)"
              className="w-full"
              checked={filters.bbRsiEntrySignal}
              onChange={(e) => patch({ bbRsiEntrySignal: e.target.checked })}
            />
          </div>
        </div>
      </MockSection>

      <div className="flex flex-col items-stretch gap-2">
        <Button variant="outline" size="sm" className="w-full justify-between">
          Saved views (3) <span className="text-text-tertiary">▾</span>
        </Button>
        {naming ? (
          <div className="flex flex-col gap-2">
            <Input
              size="full"
              aria-label="View name"
              placeholder="View name"
              value={viewName}
              onChange={(e) => setViewName(e.target.value)}
            />
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                disabled={viewName.trim() === ""}
                onClick={() => {
                  setNaming(false);
                  setViewName("");
                }}
              >
                Save
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setNaming(false);
                  setViewName("");
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setNaming(true)}>
            Save current view
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => setFilters(DEFAULT_FILTER_STATE)}>
          Reset
        </Button>
        <Button variant="outline" size="sm" onClick={() => setFilters(sampleView())}>
          Load sample view (mock)
        </Button>
      </div>
    </aside>
  );
}

// --- pre-set states --------------------------------------------------------
// The invalid and incomplete states are text, which a numeric value cannot
// hold, so the mock types them into the real box once on mount (native value
// setter plus input/focusin/focusout events -- the same events a keyboard
// produces), which runs the real commit rule. Mock-only.
function useSeededText(ref: React.RefObject<HTMLDivElement | null>, seed?: { side: "Minimum" | "Maximum"; text: string; blur?: boolean }) {
  useEffect(() => {
    if (!seed) return;
    const box = ref.current?.querySelector<HTMLInputElement>(`input[aria-label="${seed.side}"]`);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    if (!box || !setter) return;
    box.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    setter.call(box, seed.text);
    box.dispatchEvent(new Event("input", { bubbles: true }));
    // The blur waits a tick so React has re-rendered with the typed text first.
    if (seed.blur) setTimeout(() => box.dispatchEvent(new FocusEvent("focusout", { bubbles: true })), 0);
    // Seeded once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

function PresetState({
  caption,
  spec,
  initial,
  seed,
}: {
  caption: string;
  spec: RangeSpec;
  initial: RangeValue;
  seed?: { side: "Minimum" | "Maximum"; text: string; blur?: boolean };
}) {
  const [value, setValue] = useState<RangeValue>(initial);
  const ref = useRef<HTMLDivElement>(null);
  useSeededText(ref, seed);
  return (
    <div ref={ref} data-testid={`preset-${caption}`}>
      <p className="mb-1 text-[11px] font-medium text-text-secondary">{caption}</p>
      <RangeRow spec={spec} value={value} onChange={setValue} />
    </div>
  );
}

function PresetColumn() {
  const cap = FUNDAMENTAL_RANGES.find((r) => r.marketCap) as RangeSpec;
  const byKey = (key: RangeKey) => FUNDAMENTAL_RANGES.find((r) => r.key === key) as RangeSpec;
  return (
    <div className="w-64 shrink-0" data-testid="presets-boxed">
      <h3 className="mb-3 text-xs font-semibold text-text-secondary">Range field states</h3>
      <div className="space-y-4 rounded-lg border border-border-card bg-surface p-4">
        <PresetState caption="Filled, applied (orange label)" spec={byKey("overallScore")} initial={{ min: 70, max: 90 }} />
        <PresetState caption="Invalid text, with error" spec={byKey("growthRate")} initial={{ min: null, max: null }} seed={{ side: "Minimum", text: "1x" }} />
        <PresetState caption="Incomplete prefix, held while focused" spec={byKey("quote")} initial={{ min: 50, max: null }} seed={{ side: "Minimum", text: "-" }} />
        <PresetState caption="Incomplete prefix, after blur" spec={byKey("peRatio")} initial={{ min: 10, max: null }} seed={{ side: "Minimum", text: ".", blur: true }} />
        <PresetState caption="Reversed range" spec={byKey("step5Score")} initial={{ min: 90, max: 10 }} />
        <PresetState caption="Mkt cap 1B" spec={cap} initial={{ min: 1e9, max: null }} />
        <PresetState caption="Mkt cap 5T" spec={cap} initial={{ min: null, max: 5e12 }} />
      </div>
    </div>
  );
}

// --- label density and the height note ------------------------------------
function LabelComparison() {
  const [a, setA] = useState("");
  return (
    <div className="grid max-w-3xl grid-cols-1 gap-8 sm:grid-cols-2">
      <div>
        <p className="mb-3 text-xs text-text-tertiary">Default FormField: text-sm primary label, hint under it, unit after the box</p>
        <FormField label="Quote" htmlFor="sg-density-default" hint="The last closing price." unit="USD">
          <Input id="sg-density-default" size="short" value={a} onChange={(e) => setA(e.target.value)} placeholder="Min" />
        </FormField>
      </div>
      <div className="w-64">
        <p className="mb-3 text-xs text-text-tertiary">Compact: text-xs secondary label, 2px gap, unit right-aligned in the label row</p>
        <FormField label="Quote" htmlFor="sg-density-compact" density="compact" unit="USD">
          <Input id="sg-density-compact" size="short" value={a} onChange={(e) => setA(e.target.value)} placeholder="Min" />
        </FormField>
      </div>
    </div>
  );
}

function HeightNote() {
  return (
    <div className="max-w-3xl text-xs text-text-secondary" data-testid="height-note">
      <p className="mb-2 text-text-tertiary">
        Computed from the class tokens at a 16px root, not measured in a browser. Sidebar {SIDEBAR_WIDTH}px, card content {SIDEBAR_CONTENT_WIDTH}px; a
        Min/Max pair is about {PAIR_WIDTH}px wide, so nothing overflows {SIDEBAR_CONTENT_WIDTH}px.
      </p>
      <table className="w-full text-left">
        <thead>
          <tr className="text-text-tertiary">
            <th className="py-1 pr-4 font-normal">Boxed</th>
            <th className="py-1 pr-4 font-normal">Nine-field grid</th>
            <th className="py-1 font-normal">Whole Fundamental card</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          <tr>
            <td className="py-0.5 pr-4 font-sans">Without the market-cap hint</td>
            <td className="py-0.5 pr-4">{rangeGridHeight()}px</td>
            <td className="py-0.5">{fundamentalSectionHeight()}px</td>
          </tr>
          <tr>
            <td className="py-0.5 pr-4 font-sans">With the hint (as built)</td>
            <td className="py-0.5 pr-4">{rangeGridHeight(true)}px</td>
            <td className="py-0.5">{fundamentalSectionHeight(true)}px</td>
          </tr>
        </tbody>
      </table>
      <p className="mt-2 text-text-tertiary">
        A pair&apos;s error or reversed-range line adds {ERROR_ROW}px while it shows (the rows below move down), and the hint line is {HINT_ROW}px. The live
        readouts in the mock add to these and are not counted.
      </p>
    </div>
  );
}

export function ScreenerSidebarMock() {
  return (
    <div className="space-y-10" data-testid="screener-sidebar-mock">
      <div className="max-w-3xl space-y-2 text-xs text-text-tertiary">
        <p>
          The Screener sidebar, boxed, built from the real primitives with local state and mock data; the live sidebar uses the same components. Type in
          any box: the readout under each pair shows the numbers the filter would receive. Try <span className="font-mono">-</span> (held, no error
          until you leave the box), <span className="font-mono">1x</span> (inactive at once, with an error), <span className="font-mono">12.</span> and{" "}
          <span className="font-mono">.5</span> (commit as you type), <span className="font-mono">5T</span> in Mkt cap, and a min above the max.
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-10">
        <Sidebar />
        <PresetColumn />
      </div>

      <div>
        <h3 className="mb-3 text-xs font-semibold text-text-secondary">Default and compact FormField</h3>
        <LabelComparison />
      </div>

      <div>
        <h3 className="mb-3 text-xs font-semibold text-text-secondary">Computed heights</h3>
        <HeightNote />
      </div>

      <div>
        <h3 className="mb-3 text-xs font-semibold text-text-secondary">Outline button</h3>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline">Outline</Button>
          <Button variant="outline" size="sm">
            Outline small
          </Button>
          <Button variant="outline" size="sm" disabled>
            Disabled
          </Button>
          <Button variant="ghost" size="sm">
            Ghost small
          </Button>
          <Button variant="primary" size="sm">
            Primary small
          </Button>
        </div>
      </div>
    </div>
  );
}
