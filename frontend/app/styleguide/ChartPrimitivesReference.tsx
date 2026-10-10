"use client";

// Every state of the Dashboard chart primitives (components/charts/), on mock data, for review in the browser. Nothing here calls the API.
// docs/design-system-charts.md, "Dashboard primitives".
import type { ReactNode } from "react";

import { DivergingBar } from "@/components/charts/DivergingBar";
import { PriceRangeBar } from "@/components/charts/PriceRangeBar";
import { Sparkline } from "@/components/charts/Sparkline";
import { StageTimeline } from "@/components/charts/StageTimeline";
import { ThresholdGauge } from "@/components/charts/ThresholdGauge";
import { VisualRow } from "@/components/charts/VisualRow";
import { Status } from "@/components/ui/status";
import { divergingScale } from "@/lib/chartGeometry";
import { fmtMoney } from "@/lib/format";

function Group({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-medium text-text-primary">{title}</h3>
      {note ? <p className="mb-3 mt-1 max-w-3xl text-xs text-text-tertiary">{note}</p> : <div className="mb-3" />}
      {children}
    </div>
  );
}

function Case({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs text-text-tertiary">{label}</span>
      {children}
    </div>
  );
}

const x = (n: number) => `${n.toFixed(1)}x`;
const pct = (n: number) => `${n.toFixed(n >= 100 ? 0 : 1)}%`;

// --- Stage timeline mock data --------------------------------------------------------------------------------------------------------

function mondays(count: number, endIso = "2026-10-05"): string[] {
  const end = new Date(`${endIso}T00:00:00Z`).getTime();
  return Array.from({ length: count }, (_, i) => new Date(end - (count - 1 - i) * 7 * 86400000).toISOString().slice(0, 10));
}

function weeksFrom(stages: Array<[string | null, number]>) {
  const total = stages.reduce((sum, [, n]) => sum + n, 0);
  const dates = mondays(total);
  const out: Array<{ week: string; stage: string | null }> = [];
  let i = 0;
  for (const [stage, n] of stages) for (let k = 0; k < n; k++) out.push({ week: dates[i++], stage });
  return out;
}

const SWITCHED = weeksFrom([["advance", 30], ["top", 8], ["decline", 14]]);
const SWITCHED_SINCE = SWITCHED[38].week;
const ADVANCE_ONLY = weeksFrom([["advance", 52]]);
const BASE_ONLY = weeksFrom([["base", 52]]);
const ALL_FOUR = weeksFrom([["base", 10], ["advance", 18], ["top", 9], ["decline", 15]]);
const SPARK = Array.from({ length: 260 }, (_, i) => 100 + i * 0.35 + Math.sin(i / 9) * 14 + (i > 180 ? (i - 180) * 0.4 : 0));

const SCALE = divergingScale([8.3, -9.1, 1.4, 31.2], 2);

export function ChartPrimitivesReference() {
  return (
    <div className="space-y-10">
      <Group
        title="ThresholdGauge"
        note="One ratio on a track with its pass line and hard limit (two ticks), the value at the right and the lines written out underneath. Neutral fill; amber only once the value is past the pass line. The tinted band between the two lines is the monitor zone: a breach a tiebreaker can still rescue."
      >
        <div className="grid max-w-3xl gap-5">
          <Case label="Ceiling, in range (Debt / EBITDA 2.1x, passes at 3.0x or lower)">
            <ThresholdGauge value={2.1} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />
          </Case>
          <Case label="Ceiling, in the monitor zone (3.5x)">
            <ThresholdGauge value={3.5} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />
          </Case>
          <Case label="Ceiling, breach (5.2x, past the hard limit)">
            <ThresholdGauge value={5.2} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />
          </Case>
          <Case label="Ceiling, extreme value (84.6x, clamped with a ›)">
            <ThresholdGauge value={84.6} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />
          </Case>
          <Case label="Ceiling in percent (debt servicing 26%, passes at 30% or lower, hard limit 40%)">
            <ThresholdGauge value={26} passLine={30} hardLimit={40} direction="ceiling" format={pct} label="Debt servicing" />
          </Case>
          <Case label="Floor, in range (current ratio 1.8x, passes at 1.0x or higher)">
            <ThresholdGauge value={1.8} passLine={1} hardLimit={0.7} direction="floor" format={x} label="Current ratio" />
          </Case>
          <Case label="Floor, in the monitor zone (0.85x)">
            <ThresholdGauge value={0.85} passLine={1} hardLimit={0.7} direction="floor" format={x} label="Current ratio" />
          </Case>
          <Case label="Floor, breach (0.5x)">
            <ThresholdGauge value={0.5} passLine={1} hardLimit={0.7} direction="floor" format={x} label="Current ratio" />
          </Case>
          <Case label="One line only, ceiling (REIT gearing 38%, one tick, no zone)">
            <ThresholdGauge value={38} passLine={45} direction="ceiling" format={pct} label="Gearing" />
          </Case>
          <Case label="One line only, ceiling, breach (gearing 52%)">
            <ThresholdGauge value={52} passLine={45} direction="ceiling" format={pct} label="Gearing" />
          </Case>
          <Case label="One line only, floor (Bank CET1 13%, passes at 10% or higher)">
            <ThresholdGauge value={13} passLine={10} direction="floor" format={pct} label="CET1 ratio" />
          </Case>
          <Case label="One line only, floor, breach (CET1 8.5%)">
            <ThresholdGauge value={8.5} passLine={10} direction="floor" format={pct} label="CET1 ratio" />
          </Case>
          <Case label="Missing data">
            <ThresholdGauge value={null} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />
          </Case>
          <Case label="Not applicable">
            <ThresholdGauge value={null} passLine={3} direction="ceiling" format={x} notApplicable="Debt is not applied to insurers" />
          </Case>
        </div>
      </Group>

      <Group
        title="DivergingBar"
        note="A signed gap around a centre axis; the shaded band is 'in line' (default plus or minus 2 percentage points). Green ahead, red behind, neutral inside the band; the label is in %, with the stock's own and the benchmark's own return next to it so the gap is not read as a return. One shared scale for the stack."
      >
        <div className="grid max-w-3xl gap-4">
          <Case label="Ahead">
            <DivergingBar value={8.3} band={2} scale={SCALE} stockReturn={21.4} benchmarkReturn={13.1} benchmarkLabel="XLK" label="6 months vs XLK" />
          </Case>
          <Case label="Behind">
            <DivergingBar value={-9.1} band={2} scale={SCALE} stockReturn={-2.2} benchmarkReturn={6.9} benchmarkLabel="XLK" label="12 months vs XLK" />
          </Case>
          <Case label="Inside the band (in line)">
            <DivergingBar value={1.4} band={2} scale={SCALE} stockReturn={5.5} benchmarkReturn={4.1} benchmarkLabel="XLK" label="3 months vs XLK" />
          </Case>
          <Case label="Past the scale (clamped with a ›)">
            <DivergingBar value={31.2} band={2} scale={12} stockReturn={44} benchmarkReturn={12.8} benchmarkLabel="XLK" label="12 months vs XLK" />
          </Case>
          <Case label="Missing data (the cache does not reach back that far)">
            <DivergingBar value={null} band={2} scale={SCALE} label="1 month vs XLK" />
          </Case>
        </div>
      </Group>

      <Group
        title="StageTimeline"
        note="The last 12 months of Weinstein stage, a segment per run, in the tones of the stage pill (Advance green, Top amber, Decline red, Base neutral). A tick marks the switch date; the date is also written underneath."
      >
        <div className="grid max-w-3xl gap-5">
          <Case label="A switch inside the year (Advance, Top, then Decline)">
            <StageTimeline weeks={SWITCHED} since={SWITCHED_SINCE} />
          </Case>
          <Case label="All four stages">
            <StageTimeline weeks={ALL_FOUR} since={ALL_FOUR[ALL_FOUR.length - 15].week} />
          </Case>
          <Case label="One stage all year, since date only a lower bound">
            <StageTimeline weeks={ADVANCE_ONLY} since={ADVANCE_ONLY[0].week} sinceIsLowerBound />
          </Case>
          <Case label="Base (neutral)">
            <StageTimeline weeks={BASE_ONLY} since="2025-08-04" />
          </Case>
          <Case label="Unavailable (too little history)">
            <StageTimeline weeks={[]} unavailableReason="Fewer than 40 weeks of cached history" />
          </Case>
        </div>
      </Group>

      <Group
        title="PriceRangeBar"
        note="The price against the fair-value band (0.9x to 1.1x, read from the backend). Everything is neutral: the Valuation pill carries the verdict, this places the price in words."
      >
        <div className="grid max-w-3xl gap-5">
          <Case label="Below the band (undervalued)">
            <PriceRangeBar price={78} fairValue={100} />
          </Case>
          <Case label="Inside the band (fair)">
            <PriceRangeBar price={103} fairValue={100} />
          </Case>
          <Case label="Above the band (overvalued)">
            <PriceRangeBar price={131} fairValue={100} />
          </Case>
          <Case label="No fair value: no valuation method applies">
            <PriceRangeBar price={42.5} fairValue={null} unavailableReason="no valuation method applies" />
          </Case>
          <Case label="No fair value: insufficient data">
            <PriceRangeBar price={42.5} fairValue={null} unavailableReason="too little history to value" />
          </Case>
          <Case label="Fair value but no price">
            <PriceRangeBar price={null} fairValue={100} />
          </Case>
        </div>
      </Group>

      <Group title="Sparkline" note="A plain line in the one-series colour, no axes and no hover; the dot is the last point and the captions give the span.">
        <div className="grid max-w-3xl gap-5">
          <Case label="5-year price (weekly closes)">
            <Sparkline values={SPARK} startLabel="Oct 2021" endLabel="Oct 2026" format={(n) => fmtMoney(n)} />
          </Case>
          <Case label="Flat series">
            <Sparkline values={[50, 50, 50, 50]} startLabel="Oct 2021" endLabel="Oct 2026" />
          </Case>
          <Case label="No history">
            <Sparkline values={[]} />
          </Case>
        </div>
      </Group>

      <Group
        title="VisualRow and narrow width"
        note="Label and pill on the left, the visual on the right. Below 36rem of the row's own width (the sm breakpoint of a full-width card) the pill and label stack above the visual. The same row is shown at full width and at 320px."
      >
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <Case label="Full width">
            <VisualRow label="Debt / EBITDA" pill={<Status tone="positive">Pass</Status>}>
              <ThresholdGauge value={2.1} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />
            </VisualRow>
          </Case>
          <Case label="320px (stacked)">
            <div className="w-[320px] max-w-full">
              <VisualRow label="Debt / EBITDA" pill={<Status tone="positive">Pass</Status>}>
                <ThresholdGauge value={2.1} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />
              </VisualRow>
            </div>
          </Case>
          <Case label="Full width, the other visuals">
            <div className="grid gap-5">
              <VisualRow label="Relative strength, 6 months" pill={<Status tone="neutral">Context</Status>}>
                <DivergingBar value={8.3} band={2} scale={SCALE} stockReturn={21.4} benchmarkReturn={13.1} benchmarkLabel="XLK" />
              </VisualRow>
              <VisualRow label="Weinstein stage" pill={<Status tone="negative">Stage 4 · Decline</Status>}>
                <StageTimeline weeks={SWITCHED} since={SWITCHED_SINCE} />
              </VisualRow>
            </div>
          </Case>
          <Case label="320px, the other visuals (stacked)">
            <div className="grid w-[320px] max-w-full gap-5">
              <VisualRow label="Relative strength, 6 months" pill={<Status tone="neutral">Context</Status>}>
                <DivergingBar value={8.3} band={2} scale={SCALE} stockReturn={21.4} benchmarkReturn={13.1} benchmarkLabel="XLK" />
              </VisualRow>
              <VisualRow label="Weinstein stage" pill={<Status tone="negative">Stage 4 · Decline</Status>}>
                <StageTimeline weeks={SWITCHED} since={SWITCHED_SINCE} />
              </VisualRow>
              <PriceRangeBar price={78} fairValue={100} />
            </div>
          </Case>
        </div>
      </Group>

      <Group
        title="Scored and context-not-scored, kept apart"
        note="A scored step carries its score and verdict pill beside the visual. The Why might it be stuck? visuals sit in their own section headed 'Context, not scored', with no pill and no verdict tone; their only colour is the diverging green or red on a gap, which says ahead or behind a benchmark, never pass or fail."
      >
        <div className="grid max-w-3xl gap-8 lg:grid-cols-2">
          <div>
            <h4 className="mb-3 text-xs font-medium text-text-secondary">Debt, scored</h4>
            <VisualRow label={<span className="font-medium">Current ratio</span>} pill={<Status tone="caution">Pass, ratio in breach</Status>}>
              <ThresholdGauge value={0.85} passLine={1} hardLimit={0.7} direction="floor" format={x} label="Current ratio" />
            </VisualRow>
          </div>
          <div>
            <h4 className="mb-1 text-xs font-medium text-text-secondary">Why might it be stuck?</h4>
            <p className="mb-3 text-xs text-text-tertiary">Context, not scored</p>
            <VisualRow label="Relative strength, 12 months">
              <DivergingBar value={-9.1} band={2} scale={SCALE} stockReturn={-2.2} benchmarkReturn={6.9} benchmarkLabel="XLK" />
            </VisualRow>
          </div>
        </div>
      </Group>
    </div>
  );
}
