// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { readChartColors } from "@/lib/chartTokens";

// Separate from chartTokens.test.ts (default node environment, where `document` is undefined and readChartColors
// short-circuits before ever touching canvas) -- this file exercises the `document` branch specifically. jsdom
// has no real canvas 2D implementation (no `canvas` npm package installed in this project), so
// `canvas.getContext("2d")` returns null here, exactly like a browser that can't create a 2D context at all.
// Confirms readChartColors degrades gracefully in that case rather than throwing -- the one path the default
// test environment can't reach.
describe("readChartColors (jsdom, no real canvas)", () => {
  it("resolves without throwing when canvas 2D is unavailable, returning the raw values unchanged", () => {
    expect(typeof document).not.toBe("undefined");
    let colors: ReturnType<typeof readChartColors> | undefined;
    expect(() => {
      colors = readChartColors();
    }).not.toThrow();
    expect(colors?.chartUp).toBe("#10B981");
    // No --fathom-page etc. defined on this bare jsdom document, so the oklch fallback passes straight through
    // (normalizeColor's no-context branch), unchanged -- this is exactly the value that must never be handed to
    // lightweight-charts un-normalized in a real browser (see normalizeColor's own comment).
    expect(colors?.page).toBe("oklch(15% 0.014 260)");
  });
});
