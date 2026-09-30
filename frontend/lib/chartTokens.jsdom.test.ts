// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { readChartColors } from "@/lib/chartTokens";

// Separate from chartTokens.test.ts (default node environment, where `document` is undefined and readChartColors
// short-circuits before ever calling getComputedStyle) -- this file exercises the `document`-defined branch
// specifically: a bare jsdom document has none of globals.css's --fathom-* custom properties defined, so every
// chart-*/stage-* token must fall back to FALLBACK_COLORS exactly as the node-environment path does.
describe("readChartColors (jsdom, no globals.css loaded)", () => {
  it("falls back to the legacy chart/stage palette when a token isn't defined on the page", () => {
    expect(typeof document).not.toBe("undefined");
    const colors = readChartColors();
    expect(colors.chartUp).toBe("#10B981");
    expect(colors.stageBase).toBe("#8FD99F");
  });

  it("chrome tokens are the fixed literal regardless of what's on the page", () => {
    const colors = readChartColors();
    expect(colors.page).toBe("#080b11");
    expect(colors.textSecondary).toBe("#9499a0");
    expect(colors.borderCard).toBe("#292e36");
    expect(colors.borderSubtle).toBe("#20242b");
  });
});
