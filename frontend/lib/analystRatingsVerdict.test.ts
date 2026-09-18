import { describe, expect, it } from "vitest";

import { buildVerdict } from "@/lib/analystRatingsVerdict";
import type { PriceTargetSummary, RecommendationDetailsColumn } from "@/lib/api/types";

// Fixtures below are real cache-only values pulled from the tracked universe
// (backend/data/analyst_ratings_data.py::get_analyst_ratings_data,
// cache_only=True, zero live FMP calls) at design/implementation time --
// see CLAUDE.md's Analyst Ratings verdict-sentence entry. `consensus` is
// left as whatever the backend actually returned (FMP's raw live label for
// "Current", this app's own banded label for the historical columns) since
// buildVerdict never reads `.consensus` -- it always re-derives every
// period's label from `.mean` itself.
function col(label: string, mean: number | null, target: number | null, consensus: string | null = null): RecommendationDetailsColumn {
  return { label, buy: 0, outperform: 0, hold: 0, underperform: 0, sell: 0, mean, consensus, target };
}

function pt(low: number | null, high: number | null, consensus: number | null): PriceTargetSummary {
  return { current_price: null, target_consensus: consensus, target_high: high, target_low: low, target_median: null, upside_pct: null };
}

describe("buildVerdict -- design-round worked examples", () => {
  it("INTC: meaningful+steady strengthening, confirmed, wide spread caveat", () => {
    const columns = [
      col("Current", 3.2941176470588234, 110.3),
      col("2M Ago", 3.25, 85.92682926829268),
      col("6M Ago", 3.074074074074074, 41.0),
      col("1Y Ago", 2.8043478260869565, 33.05555555555556),
    ];
    const priceTarget = pt(60.0, 200.0, 110.3);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst sentiment has steadily strengthened over the past year — the weighted mean rating moved from 2.80 (Hold) to 3.29 (Hold) — price targets confirm the move, risen sharply over the same period ($33.06 → $110.30). (Analyst targets range widely, $60.00–$200.00.)"
    );
  });

  it("ZTS: meaningful+steady softening, confirmed, wide spread caveat", () => {
    const columns = [
      col("Current", 3.5, 101.5),
      col("2M Ago", 3.7, 145.3),
      col("6M Ago", 3.772727272727273, 171.6),
      col("1Y Ago", 4.0, 217.375),
    ];
    const priceTarget = pt(85.0, 160.0, 101.5);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst sentiment has steadily softened over the past year — the weighted mean rating moved from 4.00 (Outperform) to 3.50 (Outperform) — price targets confirm the move, fallen sharply over the same period ($217.38 → $101.50). (Analyst targets range widely, $85.00–$160.00.)"
    );
  });

  it("ADI: stable mean, but price targets moved sharply -- secondary signal surfaced despite flat primary", () => {
    const columns = [
      col("Current", 3.7962962962962963, 454.76),
      col("2M Ago", 4.0, 388.3333333333333),
      col("6M Ago", 3.9444444444444446, 323.5357142857143),
      col("1Y Ago", 3.8, 226.26923076923077),
    ];
    const priceTarget = pt(360.0, 550.0, 454.76);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst rating conviction has been roughly stable over the past year — the weighted mean rating moved from 3.80 (Outperform) to 3.80 (Outperform) — price targets, however, have risen sharply over the same period ($226.27 → $454.76), even as the rating mix itself has barely moved."
    );
  });

  it("SCHW: meaningful+recent softening, but price targets kept climbing -- disagreement", () => {
    const columns = [
      col("Current", 3.5098039215686274, 124.78),
      col("2M Ago", 4.045454545454546, 110.02631578947368),
      col("6M Ago", 4.136363636363637, 108.02941176470588),
      col("1Y Ago", 4.086956521739131, 89.09375),
    ];
    const priceTarget = pt(105.0, 145.0, 124.78);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst sentiment has recently, sharply softened over the past year — the weighted mean rating moved from 4.09 (Outperform) to 3.51 (Outperform) — yet price targets have risen over the same period ($89.09 → $124.78) — a tension worth noting."
    );
  });
});

describe("buildVerdict -- additional real-data spot checks", () => {
  it("MO: choppy (mid-window dip) but net meaningful strengthening, confirmed", () => {
    const columns = [
      col("Current", 3.576923076923077, 72.33),
      col("2M Ago", 3.0714285714285716, 60.76923076923077),
      col("6M Ago", 3.142857142857143, 54.84615384615385),
      col("1Y Ago", 3.066666666666667, 52.53846153846154),
    ];
    const priceTarget = pt(64.0, 79.0, 72.33);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst sentiment has unevenly strengthened over the past year — the weighted mean rating moved from 3.07 (Hold) to 3.58 (Outperform) — price targets confirm the move, risen over the same period ($52.54 → $72.33)."
    );
  });

  it("TSM: choppy meaningful softening while price targets rose sharply -- disagreement, same band both ends", () => {
    const columns = [
      col("Current", 3.72, 596.0),
      col("2M Ago", 4.2631578947368425, 454.375),
      col("6M Ago", 4.2, 337.85714285714283),
      col("1Y Ago", 4.222222222222222, 225.0),
    ];
    const priceTarget = pt(500.0, 700.0, 596.0);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst sentiment has unevenly softened over the past year — the weighted mean rating moved from 4.22 (Outperform) to 3.72 (Outperform) — yet price targets have risen sharply over the same period ($225.00 → $596.00) — a tension worth noting."
    );
  });

  it("PLTR: choppy meaningful strengthening, confirmed sharply, AND a wide-spread caveat fires", () => {
    const columns = [
      col("Current", 3.3846153846153846, 180.5),
      col("2M Ago", 3.5757575757575757, 145.9),
      col("6M Ago", 3.5483870967741935, 141.47916666666666),
      col("1Y Ago", 2.96, 91.575),
    ];
    const priceTarget = pt(80.0, 250.0, 180.5);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst sentiment has unevenly strengthened over the past year — the weighted mean rating moved from 2.96 (Hold) to 3.38 (Hold) — price targets confirm the move, risen sharply over the same period ($91.58 → $180.50). (Analyst targets range widely, $80.00–$250.00.)"
    );
  });

  it("CB: modest+recent strengthening (a tier none of the 4 original worked examples hit), confirmed", () => {
    const columns = [
      col("Current", 3.511627906976744, 356.13),
      col("2M Ago", 3.2222222222222223, 318.72),
      col("6M Ago", 3.24, 300.0),
      col("1Y Ago", 3.25, 269.3333333333333),
    ];
    const priceTarget = pt(301.0, 387.0, 356.13);
    expect(buildVerdict(columns, priceTarget)).toBe(
      "Analyst sentiment has recently strengthened over the past year — the weighted mean rating moved from 3.25 (Hold) to 3.51 (Outperform) — price targets confirm the move, risen over the same period ($269.33 → $356.13)."
    );
  });
});

describe("buildVerdict -- edge cases", () => {
  it("falls back gracefully when Current has no mean at all", () => {
    const columns = [col("Current", null, null)];
    expect(buildVerdict(columns, pt(null, null, null))).toBe("No recommendation data available.");
  });

  it("falls back to 2M Ago as the baseline when 1Y/6M Ago are both missing", () => {
    const columns = [col("Current", 4.0, 100), col("2M Ago", 3.9, 95)];
    // delta = 0.1, which is NOT < MEAN_STABLE_BAND (0.1 is not < 0.1) -> "modest" tier, not "stable".
    expect(buildVerdict(columns, pt(90, 110, 100))).toBe(
      "Analyst sentiment has steadily strengthened over the past year — the weighted mean rating moved from 3.90 (Outperform) to 4.00 (Outperform)."
    );
  });

  it("reports insufficient history when no historical column has a mean at all", () => {
    const columns = [col("Current", 4.0, 100)];
    expect(buildVerdict(columns, pt(90, 110, 100))).toBe(
      "Current consensus: Outperform (mean 4.00). Not enough rating history to establish a trend."
    );
  });
});
