import type { PriceTargetSummary, RecommendationDetailsColumn } from "@/lib/api/types";
import { fmtMoney, fmtNumber } from "@/lib/format";

// Ports analyst_ratings_data.py's own CONSENSUS_BANDS (backend/data/
// analyst_ratings_data.py:27) so this sentence can re-band ALL FOUR periods'
// mean uniformly, including "Current" -- RecommendationDetailsColumn.consensus
// deliberately mixes FMP's raw live label for "Current" with this app's own
// banded label for the 3 historical columns (see that field's own comment in
// lib/api/types.ts), which makes a direct label-to-label trend comparison
// misleading. This sentence never reads .consensus off the column directly;
// it always re-derives every period's label from .mean via this same table,
// so "Current" is on the same footing as "1Y Ago". Does not affect
// ConsensusBanner or RecommendationDetailsTable, which still show FMP's raw
// Current label as designed.
const CONSENSUS_BANDS: [number, string][] = [
  [4.5, "Buy"],
  [3.5, "Outperform"],
  [2.5, "Hold"],
  [1.5, "Underperform"],
];

function bandConsensus(mean: number): string {
  for (const [threshold, label] of CONSENSUS_BANDS) {
    if (mean >= threshold) return label;
  }
  return "Sell";
}

// A step below this magnitude (on the 1-5 mean scale) doesn't count as real
// movement -- see MagnitudeTier below for how these bands were chosen.
const STEP_NOISE_FLOOR = 0.05;

// Mean-trend magnitude bands, calibrated against a real full-universe scan
// (98 tracked tickers with valid Current + 1Y Ago mean data, cache-only):
// |delta| distribution was median 0.153, mean 0.189 on the 1-5 scale. These
// bands split that population roughly 33% stable / 49% modest / 18%
// meaningful -- not guessed.
const MEAN_STABLE_BAND = 0.1;
const MEAN_MODEST_BAND = 0.3;

type MagnitudeTier = "stable" | "modest" | "meaningful";

function magnitudeTier(absDelta: number): MagnitudeTier {
  if (absDelta < MEAN_STABLE_BAND) return "stable";
  if (absDelta < MEAN_MODEST_BAND) return "modest";
  return "meaningful";
}

type TrendShape = "steady" | "recent" | "choppy";

// Direction+CONSISTENCY across all 4 points, not just the Current-vs-1Y
// endpoint delta -- per the design brief's own weighting requirement.
// "steady": every non-flat step points the same way as the overall move.
// "recent": everything before the latest step was flat, and the latest
// step alone accounts for most of the move (a sharp, fresh change on top of
// a stable base, not a year-long grind).
// "choppy": the series reversed direction along the way -- the endpoint
// delta is still real, but it wasn't a clean move.
function trendShape(y1Mean: number, m6Mean: number, m2Mean: number, curMean: number, overallDelta: number): TrendShape {
  const steps = [m6Mean - y1Mean, m2Mean - m6Mean, curMean - m2Mean];
  const nonFlat = steps.filter((s) => Math.abs(s) >= STEP_NOISE_FLOOR);
  if (nonFlat.length === 0) return "steady";
  const sameSign = nonFlat.every((s) => (s > 0) === (overallDelta > 0));
  if (!sameSign) return "choppy";
  const latestStep = steps[2];
  const earlierStepsFlat = Math.abs(steps[0]) < STEP_NOISE_FLOOR;
  if (earlierStepsFlat && Math.abs(latestStep) >= 0.6 * Math.abs(overallDelta)) return "recent";
  return "steady";
}

const SHAPE_ADVERB: Record<TrendShape, string> = {
  steady: "steadily",
  recent: "recently",
  choppy: "unevenly",
};

// Price-target trend magnitude, calibrated against a real full-universe scan
// of period-aligned Current-vs-1Y-Ago `.target` %change (97 tickers, median
// 38.8%, mean 84.8% -- price targets move far more than the rating mean
// does in a normal year, so this needs its own, much wider bands rather than
// reusing the mean's thresholds).
const PT_FLAT_PCT = 15;
const PT_SHARP_PCT = 50;

// Analyst-target range width worth flagging as a caveat, calibrated against
// a real full-universe scan of (high-low)/consensus (98 tickers, median
// 32%) -- 60% sits around the 80th percentile, a genuinely wide spread
// rather than ordinary analyst disagreement.
const SPREAD_WIDE_PCT = 60;

function ptMagnitudeWord(absPct: number): string {
  return absPct >= PT_SHARP_PCT ? " sharply" : "";
}

function fmtMean(mean: number): string {
  return `${fmtNumber(mean, 2)} (${bandConsensus(mean)})`;
}

function secondaryClause(
  tier: MagnitudeTier,
  meanDelta: number,
  baselineTarget: number,
  curTarget: number,
  currency: string
): string | null {
  const ptPctDelta = ((curTarget - baselineTarget) / baselineTarget) * 100;
  const absPtPct = Math.abs(ptPctDelta);
  // Below this, the price-target side hasn't moved enough to either confirm
  // or contradict the mean's own move -- nothing worth adding either way.
  if (absPtPct < PT_FLAT_PCT) return null;

  const ptDir = ptPctDelta > 0 ? "risen" : "fallen";
  const ptMove = `${ptDir}${ptMagnitudeWord(absPtPct)} over the same period (${fmtMoney(baselineTarget, currency)} → ${fmtMoney(curTarget, currency)})`;

  if (tier === "stable") {
    return `price targets, however, have ${ptMove}, even as the rating mix itself has barely moved`;
  }

  const agrees = (ptPctDelta > 0) === (meanDelta > 0);
  return agrees
    ? `price targets confirm the move, ${ptMove}`
    : `yet price targets have ${ptMove} — a tension worth noting`;
}

function spreadCaveat(priceTarget: PriceTargetSummary): string | null {
  const { target_high, target_low, target_consensus } = priceTarget;
  if (target_high == null || target_low == null || !target_consensus) return null;
  const spreadPct = ((target_high - target_low) / target_consensus) * 100;
  if (spreadPct < SPREAD_WIDE_PCT) return null;
  return `analyst targets range widely, ${fmtMoney(target_low)}–${fmtMoney(target_high)}`;
}

function primaryClause(tier: MagnitudeTier, shape: TrendShape, meanDelta: number, baselineMean: number, curMean: number): string {
  const baselineLabel = fmtMean(baselineMean);
  const curLabel = fmtMean(curMean);
  if (tier === "stable") {
    return `Analyst rating conviction has been roughly stable over the past year — the weighted mean rating moved from ${baselineLabel} to ${curLabel}`;
  }
  const direction = meanDelta > 0 ? "strengthened" : "softened";
  const adverb = SHAPE_ADVERB[shape];
  const intensity = tier === "meaningful" ? (shape === "recent" ? `${adverb}, sharply` : adverb) : adverb;
  return `Analyst sentiment has ${intensity} ${direction} over the past year — the weighted mean rating moved from ${baselineLabel} to ${curLabel}`;
}

/**
 * One-sentence verdict synthesizing Recommendation Trend's Mean
 * direction+consistency (primary), Price Targets Over Time's period-aligned
 * `.target` trend (secondary -- confirms or contradicts), and Price Target
 * Range's low/high spread (tertiary caveat, only alongside a secondary
 * clause). See CLAUDE.md's Analyst Ratings design-round entry for the full
 * derivation of every threshold below.
 */
export function buildVerdict(columns: RecommendationDetailsColumn[], priceTarget: PriceTargetSummary, currency = "USD"): string {
  const byLabel = Object.fromEntries(columns.map((c) => [c.label, c]));
  const current = byLabel["Current"];
  if (!current || current.mean == null) return "No recommendation data available.";

  const baselineColumn =
    byLabel["1Y Ago"]?.mean != null ? byLabel["1Y Ago"] : byLabel["6M Ago"]?.mean != null ? byLabel["6M Ago"] : byLabel["2M Ago"];
  if (!baselineColumn || baselineColumn.mean == null) {
    return `Current consensus: ${bandConsensus(current.mean)} (mean ${fmtNumber(current.mean, 2)}). Not enough rating history to establish a trend.`;
  }

  const meanDelta = current.mean - baselineColumn.mean;
  const tier = magnitudeTier(Math.abs(meanDelta));

  const y1 = byLabel["1Y Ago"];
  const m6 = byLabel["6M Ago"];
  const m2 = byLabel["2M Ago"];
  const shape =
    y1?.mean != null && m6?.mean != null && m2?.mean != null
      ? trendShape(y1.mean, m6.mean, m2.mean, current.mean, meanDelta)
      : "steady";

  const primary = primaryClause(tier, shape, meanDelta, baselineColumn.mean, current.mean);

  const secondary =
    current.target != null && baselineColumn.target != null
      ? secondaryClause(tier, meanDelta, baselineColumn.target, current.target, currency)
      : null;

  const caveat = secondary ? spreadCaveat(priceTarget) : null;

  let sentence = secondary ? `${primary} — ${secondary}.` : `${primary}.`;
  if (caveat) sentence += ` (${caveat[0].toUpperCase()}${caveat.slice(1)}.)`;
  return sentence;
}
