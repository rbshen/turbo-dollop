import { describe, expect, it } from "vitest";

import { computeTooltipGeometry } from "@/lib/tooltipPosition";

describe("computeTooltipGeometry", () => {
  it("centers the panel under the icon when there's plenty of room", () => {
    const icon = { left: 400, right: 416, top: 200 };
    const geometry = computeTooltipGeometry(icon, 224, 80, 1200);
    // icon center = 408, panel width 224 -> centered left = 296
    expect(geometry.panelLeft).toBe(296);
    expect(geometry.panelTop).toBe(200 - 80 - 10);
    // arrow points at icon center relative to the panel's own left edge
    expect(geometry.arrowLeft).toBeCloseTo(408 - 296 - 4, 5);
  });

  it("clamps to the left viewport margin when the icon is near the left edge", () => {
    const icon = { left: 10, right: 26, top: 200 };
    const geometry = computeTooltipGeometry(icon, 224, 80, 1200);
    expect(geometry.panelLeft).toBe(8);
    // icon center (18) - panelLeft (8) - half arrow (4) = 6, but the arrow
    // is itself clamped to stay >=8px from the panel's own left edge.
    expect(geometry.arrowLeft).toBe(8);
  });

  it("clamps to the right viewport margin when the icon is near the right edge", () => {
    const icon = { left: 1180, right: 1196, top: 200 };
    const geometry = computeTooltipGeometry(icon, 224, 80, 1200);
    // max left = viewportWidth - panelWidth - margin = 1200 - 224 - 8 = 968
    expect(geometry.panelLeft).toBe(968);
    // 1188 - 968 - 4 = 216, but the arrow is clamped to stay >=8px from the
    // panel's own right edge: 224 - 8 - 8 (arrow size) = 208.
    expect(geometry.arrowLeft).toBe(208);
  });

  it("keeps the arrow within the panel's own bounds even at an extreme clamp", () => {
    // A very narrow viewport where the icon sits far outside the clamped panel.
    const icon = { left: 0, right: 16, top: 50 };
    const geometry = computeTooltipGeometry(icon, 224, 80, 100);
    expect(geometry.arrowLeft).toBeGreaterThanOrEqual(8);
    expect(geometry.arrowLeft).toBeLessThanOrEqual(224 - 8 - 8);
  });

  it("always opens above the icon, never below", () => {
    const icon = { left: 100, right: 116, top: 300 };
    const geometry = computeTooltipGeometry(icon, 224, 60, 1200);
    expect(geometry.panelTop).toBeLessThan(icon.top);
  });
});
