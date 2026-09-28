"use client";

import { useState } from "react";
import { Bar, BarChart, Cell, XAxis, YAxis } from "recharts";
import { Plus } from "@phosphor-icons/react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Badge } from "@/components/ui/badge";
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
import { Status, Verdict } from "@/components/ui/status";
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
