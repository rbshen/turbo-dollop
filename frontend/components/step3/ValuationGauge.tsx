"use client";

import { Cell, Customized, Pie, PieChart } from "recharts";

import { fmtPct } from "@/lib/format";

interface Props {
  /** Fraction, e.g. -0.218 for -21.8%. */
  discountPremiumPct: number | null;
}

// Fixed-size (non-responsive) chart -- a small embedded status widget, not
// a data-dense chart that needs to reflow with its container.
const WIDTH = 280;
const HEIGHT = 168;
const CX = WIDTH / 2;
const CY = HEIGHT - 12;
const INNER_RADIUS = 68;
const OUTER_RADIUS = 100;

// Clamped display domain -- real discount/premium values can run far wider
// (e.g. a heavily-levered mature company's DNI result), but the gauge's job
// is to show *which zone* the stock is in, not plot every possible value;
// off-scale values pin to the arc's end and the exact % is still shown as
// text below.
const DOMAIN_MIN = -0.5;
const DOMAIN_MAX = 0.5;
const FAIR_BAND = 0.1;

// Same undervalued/fair/overvalued colors as FairValuePill and the rest of
// the app's status conventions (emerald/zinc/red), so the gauge reads as
// part of one consistent system rather than introducing a new palette.
const BANDS = [
  { key: "undervalued", from: DOMAIN_MIN, to: -FAIR_BAND, color: "#34d399" },
  { key: "fair", from: -FAIR_BAND, to: FAIR_BAND, color: "#71717a" },
  { key: "overvalued", from: FAIR_BAND, to: DOMAIN_MAX, color: "#f87171" },
];

const VERDICT_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fair value",
};

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

// Maps a domain value to a gauge angle: 180deg (arc's left end, most
// negative) sweeping down to 0deg (right end, most positive) -- matches the
// Pie's own startAngle=180/endAngle=0 below.
function valueToAngleDeg(v: number): number {
  const t = (clamp(v, DOMAIN_MIN, DOMAIN_MAX) - DOMAIN_MIN) / (DOMAIN_MAX - DOMAIN_MIN);
  return 180 - t * 180;
}

function Needle({ angleDeg }: { angleDeg: number }) {
  const rad = (angleDeg * Math.PI) / 180;
  const len = OUTER_RADIUS * 0.8;
  const x = CX + len * Math.cos(rad);
  const y = CY - len * Math.sin(rad);
  return (
    <g>
      <line x1={CX} y1={CY} x2={x} y2={y} stroke="#e4e4e7" strokeWidth={3} strokeLinecap="round" />
      <circle cx={CX} cy={CY} r={6} fill="#e4e4e7" />
    </g>
  );
}

export function ValuationGauge({ discountPremiumPct }: Props) {
  const data = BANDS.map((b) => ({ ...b, value: b.to - b.from }));
  const verdict = discountPremiumPct == null ? null : discountPremiumPct <= -FAIR_BAND ? "undervalued" : discountPremiumPct >= FAIR_BAND ? "overvalued" : "fair";
  const isOffScale = discountPremiumPct != null && (discountPremiumPct < DOMAIN_MIN || discountPremiumPct > DOMAIN_MAX);

  return (
    <div className="flex flex-col items-center gap-1" role="img" aria-label="Discount/premium to intrinsic value gauge">
      <PieChart width={WIDTH} height={HEIGHT}>
        <Pie
          data={data}
          dataKey="value"
          cx={CX}
          cy={CY}
          startAngle={180}
          endAngle={0}
          innerRadius={INNER_RADIUS}
          outerRadius={OUTER_RADIUS}
          stroke="none"
          isAnimationActive={false}
        >
          {data.map((entry) => (
            <Cell key={entry.key} fill={entry.color} />
          ))}
        </Pie>
        {discountPremiumPct != null && <Customized component={() => <Needle angleDeg={valueToAngleDeg(discountPremiumPct)} />} />}
      </PieChart>
      {discountPremiumPct != null && verdict ? (
        <p className="text-sm">
          <span className="font-mono font-semibold tabular-nums text-zinc-100">{fmtPct(discountPremiumPct * 100, 1)}</span>{" "}
          <span className="text-zinc-500">
            {VERDICT_LABELS[verdict]}
            {isOffScale && " (off-scale)"}
          </span>
        </p>
      ) : (
        <p className="text-sm text-zinc-600">No discount/premium available</p>
      )}
    </div>
  );
}
