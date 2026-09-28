"use client";

import { useState } from "react";
import { Bar, BarChart, Cell, XAxis, YAxis } from "recharts";
import { Plus } from "@phosphor-icons/react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  DefinitionRow,
  MetricTile,
  Section,
  SectionGrid,
  Tile,
} from "@/components/ui/section";
import { SideNav } from "@/components/ui/side-nav";
import { SortHeader } from "@/components/ui/sort-header";
import { Status, Verdict, type StatusTone } from "@/components/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";

// Internal reference page for the direction-B design-system primitives.
// Not linked from any navigation -- visit /styleguide directly.
export default function StyleguidePage() {
  return (
    <PageContainer className="space-y-2 pb-16 pt-8">
      <h1 className="font-heading text-xl font-semibold text-text-primary">Styleguide</h1>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Save changes</Button>
          <Button variant="primary" size="sm">
            Save changes
          </Button>
          <Button variant="ghost">Cancel</Button>
          <Button variant="ghost" size="sm">
            Cancel
          </Button>
          <Button variant="danger">Delete watchlist</Button>
          <Button variant="danger" size="sm">
            Delete watchlist
          </Button>
          <Button variant="primary">
            <Plus size={16} />
            Add ticker
          </Button>
          <Button variant="primary" disabled>
            Save changes
          </Button>
          <Button variant="ghost" disabled>
            Cancel
          </Button>
        </div>
      </Section>

      <Section title="Status">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-5">
            <Status tone="strong">Strong pass</Status>
            <Status tone="positive">Pass</Status>
            <Status tone="warn">Needs review</Status>
            <Status tone="caution">Pass with caution</Status>
            <Status tone="negative">Fail</Status>
            <Status tone="speculative">Speculative growth</Status>
            <Status tone="neutral">Not scored</Status>
          </div>
          <div className="flex flex-wrap items-center gap-5">
            <Status tone="positive" direction="up">
              +3.66%
            </Status>
            <Status tone="negative" direction="down">
              -1.20%
            </Status>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-text-primary">92</span>
            <Verdict tone="strong">Strong pass</Verdict>
          </div>
        </div>
      </Section>

      <Section title="Badges">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone="strong">Strong pass</Badge>
          <Badge tone="positive">Pass</Badge>
          <Badge tone="warn">Caution</Badge>
          <Badge tone="negative">Fail</Badge>
          <Badge tone="neutral">Not scored</Badge>
          <Badge missing />
        </div>
      </Section>

      <Section title="Section family">
        <SectionGrid>
          <div>
            <Tile href="/tickers/AAPL">
              <span className="font-mono text-sm font-semibold text-text-primary">AAPL</span>
              <span className="text-xs text-text-tertiary">Apple Inc.</span>
            </Tile>
            <Tile>
              <span className="font-mono text-sm font-semibold text-text-primary">MSFT</span>
              <span className="text-xs text-text-tertiary">Microsoft Corporation (not a link)</span>
            </Tile>
            <DefinitionRow label="Price" value="$516.17" />
            <DefinitionRow label="5Y vs. SPY" value="+3.66%" tone="positive" />
            <DefinitionRow label="Debt / EBITDA" value="-1.20x" tone="negative" />
          </div>
          <div className="flex flex-col gap-6">
            <MetricTile label="Overall score" value="92" note="Strong pass" />
            <MetricTile label="Fair value" value="$516.17" />
          </div>
        </SectionGrid>

        <p className="mt-8 mb-2 text-xs text-text-tertiary">
          A page of grouped metrics (e.g. the ticker page&apos;s MetricsGrid) -- multiple titled Sections stacked per
          column, laid out with SectionGrid instead of a boxed card per group
        </p>
        <SectionGrid>
          <div>
            <Section title="Classification">
              <DefinitionRow label="Sector" value="Technology" />
              <DefinitionRow label="Industry" value="Consumer Electronics" />
            </Section>
            <Section title="Size &amp; Valuation">
              <DefinitionRow label="Market Cap" value="$3.85T" />
              <DefinitionRow label="P/E Ratio" value="34.2x" />
            </Section>
          </div>
          <div>
            <Section title="Liquidity">
              <DefinitionRow label="Avg Volume (20d)" value="48.6M" />
              <DefinitionRow label="52W Range" value="$168.99 — $260.10" />
            </Section>
            <Section title="Performance">
              <DefinitionRow label="5Y vs. SPY" value="+3.66%" tone="positive" />
              <DefinitionRow label="52W Change" value="-4.20%" tone="negative" />
            </Section>
          </div>
        </SectionGrid>
      </Section>

      <Section title="Table">
        <div className="flex flex-col gap-8">
          <div>
            <p className="mb-2 text-xs text-text-tertiary">Clickable rows</p>
            <TableClickableRowsDemo />
          </div>
          <div>
            <p className="mb-2 text-xs text-text-tertiary">Sort header -- inactive, active ascending, active descending (priority 2)</p>
            <TableSortHeaderDemo />
          </div>
          <div>
            <p className="mb-2 text-xs text-text-tertiary">Read-only reference table (no hover)</p>
            <TableReadOnlyDemo />
          </div>
          <div>
            <p className="mb-2 text-xs text-text-tertiary">
              Dense statement table -- sticky header + sticky first column, collapsible group, missing value
            </p>
            <TableDenseReferenceDemo />
          </div>
          <div className="flex flex-col gap-4">
            <div>
              <p className="mb-2 text-xs text-text-tertiary">Empty</p>
              <TableEmptyDemo />
            </div>
            <div>
              <p className="mb-2 text-xs text-text-tertiary">Loading</p>
              <TableLoadingDemo />
            </div>
            <div>
              <p className="mb-2 text-xs text-text-tertiary">Error</p>
              <TableErrorDemo />
            </div>
          </div>
        </div>
      </Section>

      <Section title="Inputs">
        <div className="flex flex-wrap items-start gap-6">
          <Field label="Ticker" htmlFor="sg-ticker">
            <Input id="sg-ticker" placeholder="AAPL" />
          </Field>
          <Field label="Shares" htmlFor="sg-shares">
            <Input id="sg-shares" type="number" defaultValue={100} />
          </Field>
          <Field label="Search" htmlFor="sg-search">
            <Input id="sg-search" variant="boxed" placeholder="Search tickers…" />
          </Field>
          <Field label="Min score" htmlFor="sg-applied" applied>
            <Input id="sg-applied" type="number" defaultValue={70} />
          </Field>
          <Field label="Disabled" htmlFor="sg-disabled">
            <Input id="sg-disabled" placeholder="AAPL" disabled />
          </Field>
        </div>
      </Section>

      <Section title="Checkboxes">
        <div className="flex flex-wrap items-center gap-6">
          <Checkbox id="sg-cb-unchecked" label="Exclude ETFs" />
          <Checkbox id="sg-cb-checked" label="Exclude ETFs" defaultChecked />
          <Checkbox id="sg-cb-disabled" label="Exclude ETFs" disabled />
          <Checkbox id="sg-cb-disabled-checked" label="Exclude ETFs" disabled defaultChecked />
        </div>
      </Section>

      <Section title="Card">
        <Card className="max-w-sm">
          <p className="text-sm text-text-secondary">Not the default; reach for Section first. Never nested.</p>
        </Card>
      </Section>

      <Section title="Tabs">
        <TabsDemo />
      </Section>

      <Section title="Segmented control">
        <div className="flex flex-col gap-4">
          <UniverseSegmentedControlDemo />
          <RangeSegmentedControlDemo />
        </div>
      </Section>

      <Section title="Tooltip">
        <div className="flex items-center gap-2">
          <Tooltip content="Trailing twelve months -- the sum of the most recent 4 reported quarters.">
            <span className="border-b border-dashed border-border-control text-sm text-text-primary">TTM</span>
          </Tooltip>
          <span className="text-sm text-text-tertiary">(hover or tab to it)</span>
        </div>
      </Section>

      <Section title="Side nav">
        <SideNavDemo />
      </Section>

      <Section title="Page header">
        <div className="border border-border-subtle">
          <PageContainer>
            <PageHeaderDemo />
          </PageContainer>
        </div>
      </Section>

      <Section title="Chart">
        <SampleBarChart />
      </Section>
    </PageContainer>
  );
}

const TAB_ITEMS = [
  { value: "summary", label: "Summary" },
  { value: "financials", label: "Financials" },
  { value: "ratios", label: "Ratios" },
  { value: "analysis", label: "Analysis", count: 4 },
  { value: "valuation", label: "Valuation" },
];

function TabsDemo() {
  const [value, setValue] = useState("financials");
  return <Tabs value={value} onValueChange={setValue} items={TAB_ITEMS} />;
}

const UNIVERSE_OPTIONS = [
  { value: "sp500", label: "S&P 500" },
  { value: "nasdaq", label: "Nasdaq" },
  { value: "dow", label: "Dow 30" },
  { value: "all", label: "All" },
];

function UniverseSegmentedControlDemo() {
  const [value, setValue] = useState("sp500");
  return <SegmentedControl value={value} onValueChange={setValue} options={UNIVERSE_OPTIONS} />;
}

const RANGE_OPTIONS = [
  { value: "d6m", label: "D · 6M" },
  { value: "d1y", label: "D · 1Y" },
  { value: "d2y", label: "D · 2Y" },
  { value: "w4y", label: "W · 4Y" },
];

function RangeSegmentedControlDemo() {
  const [value, setValue] = useState("d1y");
  return <SegmentedControl value={value} onValueChange={setValue} options={RANGE_OPTIONS} />;
}

interface TableDemoRow {
  ticker: string;
  company: string;
  sector: string;
  score: number;
  scoreTone: BadgeProps["tone"];
  rating: string;
  ratingTone: StatusTone;
  peRatio: number;
  chgPct: number;
}

// Realistic Fathom sample tickers -- one of each score/rating tier, and one
// negative Chg % value, per the styleguide brief.
const TABLE_DEMO_ROWS: TableDemoRow[] = [
  { ticker: "AAPL", company: "Apple Inc.", sector: "Technology", score: 92, scoreTone: "strong", rating: "Buy", ratingTone: "positive", peRatio: 31.4, chgPct: 1.24 },
  { ticker: "MSFT", company: "Microsoft Corporation", sector: "Technology", score: 88, scoreTone: "positive", rating: "Buy", ratingTone: "positive", peRatio: 34.8, chgPct: 0.62 },
  { ticker: "JPM", company: "JPMorgan Chase & Co.", sector: "Financial Services", score: 74, scoreTone: "warn", rating: "Hold", ratingTone: "warn", peRatio: 12.1, chgPct: -0.85 },
  { ticker: "XOM", company: "Exxon Mobil Corporation", sector: "Energy", score: 61, scoreTone: "negative", rating: "Sell", ratingTone: "negative", peRatio: 14.6, chgPct: -2.13 },
];

function TableClickableRowsDemo() {
  return (
    <Table>
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className="w-[220px]">Ticker</TableHead>
          <TableHead>Sector</TableHead>
          <TableHead className="text-center">Score</TableHead>
          <TableHead>Rating</TableHead>
          <TableHead className="text-right">P/E</TableHead>
          <TableHead className="text-right">Chg %</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {TABLE_DEMO_ROWS.map((row) => (
          <TableRow key={row.ticker} interactive>
            <TableCell className="w-[220px] max-w-[220px] overflow-hidden">
              <p className="font-mono text-sm font-semibold text-text-primary">{row.ticker}</p>
              <p className="truncate text-xs text-text-secondary">{row.company}</p>
            </TableCell>
            <TableCell className="text-text-secondary">{row.sector}</TableCell>
            <TableCell className="text-center">
              <Badge tone={row.scoreTone}>{row.score}</Badge>
            </TableCell>
            <TableCell>
              <Status tone={row.ratingTone}>{row.rating}</Status>
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums text-text-primary">{row.peRatio.toFixed(1)}</TableCell>
            <TableCell className={`text-right font-mono tabular-nums ${row.chgPct >= 0 ? "text-positive" : "text-negative"}`}>
              {row.chgPct >= 0 ? "+" : ""}
              {row.chgPct.toFixed(2)}%
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TableSortHeaderDemo() {
  return (
    <Table className="max-w-lg">
      <TableHeader>
        <TableRow className="h-9">
          <TableHead sort="none">
            <SortHeader label="Ticker" active={false} onClick={() => {}} />
          </TableHead>
          <TableHead className="text-right" sort="ascending">
            <SortHeader label="Score" active direction="asc" align="right" onClick={() => {}} />
          </TableHead>
          <TableHead className="text-right" sort="descending">
            <SortHeader label="Beta" active direction="desc" priority={2} align="right" onClick={() => {}} />
          </TableHead>
        </TableRow>
      </TableHeader>
    </Table>
  );
}

const TABLE_REFERENCE_ROWS = [
  { metric: "Current Ratio", value: "1.42x" },
  { metric: "Debt / EBITDA", value: "2.10x" },
  { metric: "Debt Servicing Ratio", value: "18.4%" },
  { metric: "Interest Coverage", value: "9.6x" },
];

function TableReadOnlyDemo() {
  return (
    <Table className="max-w-sm">
      <TableHeader>
        <TableRow className="h-9">
          <TableHead>Metric</TableHead>
          <TableHead className="text-right">Value</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {TABLE_REFERENCE_ROWS.map((row) => (
          <TableRow key={row.metric}>
            <TableCell className="text-text-secondary">{row.metric}</TableCell>
            <TableCell className="text-right font-mono tabular-nums text-text-primary">{row.value}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

const DENSE_REFERENCE_PERIODS = ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025", "TTM"];

interface DenseReferenceRow {
  label: string;
  values: (number | null)[];
  emphasis?: boolean;
}

// One group header ("Income Statement") over 7 statement rows -- matches
// FinancialsStatementTable/RatiosTable's real sticky-header/sticky-first-
// column shape at the dense (h-9) row height. "Net income" is the
// emphasised subtotal; its FY2024 column is deliberately null to exercise
// the "—" missing-value convention.
const DENSE_REFERENCE_ROWS: DenseReferenceRow[] = [
  { label: "Revenue", values: [274.5, 297.4, 365.8, 391.0, 416.2, 421.6] },
  { label: "Cost of revenue", values: [169.6, 177.0, 214.1, 223.5, 233.7, 236.2] },
  { label: "Gross profit", values: [104.9, 120.4, 151.7, 167.5, 182.5, 185.4] },
  { label: "Operating expenses", values: [43.9, 47.1, 51.3, 54.8, 57.5, 58.2] },
  { label: "Operating income", values: [61.0, 73.3, 100.4, 112.7, 125.0, 127.2] },
  { label: "Net income", values: [57.4, 61.3, 77.6, null, 88.1, 90.7], emphasis: true },
  { label: "Diluted EPS", values: [3.29, 3.77, 4.9, 5.66, 5.75, 5.92] },
];

function TableDenseReferenceDemo() {
  return (
    <Table containerClassName="max-h-[200px] max-w-md overflow-auto" className="border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className="sticky left-0 top-0 z-30 whitespace-nowrap border-b border-border-subtle bg-page pr-8">
            Metric
          </TableHead>
          {DENSE_REFERENCE_PERIODS.map((period) => (
            <TableHead
              key={period}
              className="sticky top-0 z-20 whitespace-nowrap border-b border-border-subtle bg-page text-right"
            >
              {period}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow dense>
          <TableCell className="sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-page pr-8 pt-4 pb-1 text-sm font-medium text-text-primary">
            Income statement
          </TableCell>
          <TableCell colSpan={DENSE_REFERENCE_PERIODS.length} className="border-b border-border-subtle pt-4 pb-1" />
        </TableRow>
        {DENSE_REFERENCE_ROWS.map((row) => (
          <TableRow key={row.label} dense>
            <TableCell
              className={`sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-page pl-4 pr-8 ${
                row.emphasis ? "font-medium text-text-primary" : "text-text-secondary"
              }`}
            >
              {row.label}
            </TableCell>
            {row.values.map((value, i) => (
              <TableCell
                key={i}
                className={`border-b border-border-subtle text-right font-mono tabular-nums ${
                  row.emphasis ? "font-medium text-text-primary" : "text-text-secondary"
                }`}
              >
                {value != null ? value.toFixed(2) : "—"}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TableEmptyDemo() {
  return <p className="text-xs text-text-tertiary">No tickers in this watchlist yet — add one from its ticker page.</p>;
}

function TableLoadingDemo() {
  return (
    <Table className="max-w-sm">
      <TableBody>
        {Array.from({ length: 3 }, (_, i) => (
          <TableRow key={i} className="animate-pulse bg-surface-2">
            <TableCell colSpan={2} />
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TableErrorDemo() {
  return <p className="text-sm text-negative">Couldn&apos;t load this watchlist — request failed.</p>;
}

const SIDE_NAV_ITEMS = [
  { href: "#status", label: "Status" },
  { href: "#discount-rate", label: "Discount Rate" },
  { href: "#liquidity-zones", label: "Liquidity Zones", current: true },
  { href: "#weinstein", label: "Weinstein" },
  { href: "#data-groups", label: "Data Groups" },
  { href: "#scheduled-jobs", label: "Scheduled Jobs" },
  { href: "#watchlists", label: "Watchlists" },
];

function SideNavDemo() {
  return <SideNav items={SIDE_NAV_ITEMS} />;
}

function PageHeaderDemo() {
  const [range, setRange] = useState("sp500");
  return (
    <PageHeader
      title="Screener"
      subtitle="584 of 584 tickers"
      actions={
        <>
          <SegmentedControl value={range} onValueChange={setRange} options={UNIVERSE_OPTIONS} />
          <Button variant="ghost">Reset filters</Button>
          <Button variant="primary">Recompute scores</Button>
        </>
      }
    />
  );
}

const SAMPLE_CHART_DATA = [
  { period: "Q1", value: 12.4 },
  { period: "Q2", value: 18.1 },
  { period: "Q3", value: 9.3 },
  { period: "Q4", value: -6.8 },
  { period: "Q5", value: 15.2 },
  { period: "Q6", value: 21.6 },
];

const SAMPLE_CHART_CONFIG: ChartConfig = { value: { label: "Revenue growth" } };

function SampleBarChart() {
  return (
    <ChartContainer
      config={SAMPLE_CHART_CONFIG}
      className="aspect-auto w-full"
      style={{ height: 216 }}
      role="img"
      aria-label="Sample quarterly revenue growth chart"
    >
      <BarChart data={SAMPLE_CHART_DATA}>
        <XAxis dataKey="period" tickLine={false} axisLine={false} tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }} />
        <YAxis hide />
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              formatter={(value) => (
                <span className="font-mono font-medium tabular-nums text-text-primary">
                  {Number(value) >= 0 ? "+" : ""}
                  {Number(value).toFixed(2)}%
                </span>
              )}
            />
          }
        />
        <Bar dataKey="value" radius={2} isAnimationActive={false}>
          {SAMPLE_CHART_DATA.map((row) => (
            <Cell key={row.period} fill={row.value >= 0 ? "var(--color-series-1)" : "var(--color-negative)"} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
