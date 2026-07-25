"use client";

import { Cell, Customized, Pie, PieChart } from "recharts";

import { fmtMoney } from "@/lib/format";

interface Props {
  /** Fraction, e.g. -0.218 for -21.8%. Drives the needle position. */
  discountPremiumPct: number | null;
  intrinsicValuePerShare: number | null;
  lastClose: number | null;
}

// Fixed-size (non-responsive) chart -- a small embedded status widget, not
// a data-dense chart that needs to reflow with its container.
const WIDTH = 320;
const HEIGHT = 196;
const CX = WIDTH / 2;
const CY = HEIGHT - 38;
const INNER_RADIUS = 68;
const OUTER_RADIUS = 100;

// Clamped display domain -- real discount/premium values can run far wider
// (e.g. a heavily-levered mature company's DNI result), but the gauge's job
// is to show *which zone* the stock is in, not plot every possible value;
// off-scale values pin to the arc's end.
const DOMAIN_MIN = -0.5;
const DOMAIN_MAX = 0.5;

// 5 equal segments, left (most undervalued) -> right (most overvalued).
const SEGMENT_COLORS = ["#059669", "#34d399", "#facc15", "#fb923c", "#f87171"];
const SEGMENT_WIDTH = (DOMAIN_MAX - DOMAIN_MIN) / SEGMENT_COLORS.length;
const BANDS = SEGMENT_COLORS.map((color, i) => ({
  key: `seg-${i}`,
  from: DOMAIN_MIN + i * SEGMENT_WIDTH,
  to: DOMAIN_MIN + (i + 1) * SEGMENT_WIDTH,
  color,
}));

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

// Round 1/2 tried positioning the Stock Price callout "near the needle"
// (first overlaid on the arc, then on a pill meant to paint on top of it) --
// both still read as clipped/hidden under the arc in practice, since it
// shared geometry with the colored band regardless of paint order. Fixed
// here by giving both callouts a static position entirely outside the arc's
// radius (the clear strip above it, split left/right), the same strip
// "Intrinsic value" already occupied alone -- geometrically guaranteed to
// never sit under any arc color, no z-index/paint-order reasoning required.
function Callouts({ intrinsicValuePerShare, lastClose }: { intrinsicValuePerShare: number | null; lastClose: number | null }) {
  const leftX = CX - 72;
  const rightX = CX + 72;
  return (
    <>
      <text x={leftX} y={14} textAnchor="middle" className="fill-zinc-500" style={{ fontSize: 10, letterSpacing: "0.03em" }}>
        Intrinsic value
      </text>
      <text x={leftX} y={31} textAnchor="middle" className="fill-zinc-100" style={{ fontSize: 16, fontWeight: 700 }}>
        {intrinsicValuePerShare != null ? fmtMoney(intrinsicValuePerShare) : "—"}
      </text>
      <text x={rightX} y={14} textAnchor="middle" className="fill-zinc-500" style={{ fontSize: 10, letterSpacing: "0.03em" }}>
        Stock price
      </text>
      <text x={rightX} y={31} textAnchor="middle" className="fill-zinc-100" style={{ fontSize: 16, fontWeight: 700 }}>
        {lastClose != null ? fmtMoney(lastClose) : "—"}
      </text>
    </>
  );
}

export function ValuationGauge({ discountPremiumPct, intrinsicValuePerShare, lastClose }: Props) {
  const data = BANDS.map((b) => ({ ...b, value: b.to - b.from }));
  const needleAngle = discountPremiumPct != null ? valueToAngleDeg(discountPremiumPct) : null;
  const isOffScale = discountPremiumPct != null && (discountPremiumPct < DOMAIN_MIN || discountPremiumPct > DOMAIN_MAX);

  return (
    <div className="flex flex-col items-center" role="img" aria-label="Intrinsic value vs stock price gauge">
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
        <Customized component={() => <Callouts intrinsicValuePerShare={intrinsicValuePerShare} lastClose={lastClose} />} />
        <Customized
          component={() => (
            <>
              <text x={CX - OUTER_RADIUS} y={CY + 24} textAnchor="start" className="fill-zinc-500" style={{ fontSize: 11 }}>
                Undervalued
              </text>
              <text x={CX + OUTER_RADIUS} y={CY + 24} textAnchor="end" className="fill-zinc-500" style={{ fontSize: 11 }}>
                Overvalued
              </text>
            </>
          )}
        />
        {needleAngle != null && <Customized component={() => <Needle angleDeg={needleAngle} />} />}
      </PieChart>
      {discountPremiumPct == null ? (
        <p className="text-sm text-zinc-600">No discount/premium available</p>
      ) : (
        isOffScale && <p className="text-xs text-zinc-600">Off-scale, pinned to arc end</p>
      )}
    </div>
  );
}
