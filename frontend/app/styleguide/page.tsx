"use client";

import { Plus } from "@phosphor-icons/react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, Input } from "@/components/ui/input";
import {
  DefinitionRow,
  MetricTile,
  Section,
  SectionGrid,
  Tile,
} from "@/components/ui/section";
import { Status, Verdict } from "@/components/ui/status";

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
        <div className="flex flex-wrap items-end gap-6">
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
          <p className="text-sm text-text-secondary">
            Not the default -- reach for Section first. Never nested.
          </p>
        </Card>
      </Section>
    </PageContainer>
  );
}
