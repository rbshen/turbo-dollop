import { describe, expect, it } from "vitest";

import { buildStageColoredBars, WEINSTEIN_STAGE_CANDLE_COLORS } from "./chartWeinstein";

const bar = (time: string) => ({ time, open: 1, high: 2, low: 0.5, close: 1.5 });

describe("buildStageColoredBars", () => {
  it("colors each bar by its own week's stage and leaves unstaged bars untouched", () => {
    const out = buildStageColoredBars(
      [bar("2026-01-05"), bar("2026-01-12"), bar("2026-01-19")],
      [
        { time: "2026-01-12", stage: "top" },
        { time: "2026-01-19", stage: "decline" },
      ],
    );
    expect(out[0]).toEqual(bar("2026-01-05"));
    expect(out[1]).toMatchObject({ color: "#E8A020", wickColor: "#E8A020", borderColor: "#E8A020" });
    expect(out[2].color).toBe(WEINSTEIN_STAGE_CANDLE_COLORS.decline);
  });

  it("uses the specified stage palette", () => {
    expect(WEINSTEIN_STAGE_CANDLE_COLORS).toEqual({ base: "#8FD99F", advance: "#1B9E3E", top: "#E8A020", decline: "#E03A3A" });
  });
});
