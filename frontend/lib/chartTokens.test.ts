import { describe, expect, it } from "vitest";
import { readChartColors } from "@/lib/chartTokens";

// Default (node) test environment, matching every other lib/*.test.ts in this project -- `document` is
// undefined here, so this exercises readChartColors' fallback path, the same path a server render hits.
// Protects against accidental color drift: these are the exact legacy hex values every chart element already
// rendered with before this session's migration onto named tokens.
const EXPECTED_LEGACY_PALETTE: Record<string, string> = {
  chartUp: "#10B981",
  chartDown: "#EF4444",
  chartEma21: "#3179F5",
  chartSma50: "#4CAF50",
  chartSma200: "#F23645",
  chartStochK: "#F23645",
  chartBand: "#808080",
  chartRefline: "#52525B",
  chartZoneBrokenSupport: "#FF9800",
  chartZoneBrokenResistance: "#E040FB",
  chartWarrenYellow: "#F59E0B",
  chartWarrenGray: "#A1A1AA",
  chartEventEarnings: "#22D3EE",
  chartEventDividend: "#A78BFA",
  stageBase: "#8FD99F",
  stageAdvance: "#1B9E3E",
  stageTop: "#E8A020",
  stageDecline: "#E03A3A",
};

describe("readChartColors", () => {
  it("returns the fallback map when document is unavailable", () => {
    expect(typeof document).toBe("undefined");
    const colors = readChartColors();
    for (const key of Object.keys(EXPECTED_LEGACY_PALETTE)) {
      expect(colors[key as keyof typeof colors]).toBeTruthy();
    }
  });

  it("fallback values equal the exact legacy chart/stage palette, case-insensitively", () => {
    const colors = readChartColors();
    for (const [key, expected] of Object.entries(EXPECTED_LEGACY_PALETTE)) {
      expect(colors[key as keyof typeof colors].toLowerCase()).toBe(expected.toLowerCase());
    }
  });

  it("includes every expected key", () => {
    const colors = readChartColors();
    const expectedKeys = [
      ...Object.keys(EXPECTED_LEGACY_PALETTE),
      "page",
      "textSecondary",
      "borderCard",
      "borderSubtle",
    ];
    for (const key of expectedKeys) {
      expect(colors).toHaveProperty(key);
      expect(colors[key as keyof typeof colors]).toBeTruthy();
    }
  });
});
