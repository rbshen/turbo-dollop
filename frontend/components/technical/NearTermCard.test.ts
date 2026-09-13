import { describe, expect, it } from "vitest";

import { trendStartedLabel } from "@/components/technical/NearTermCard";

describe("trendStartedLabel", () => {
  it("reads 'Trend started' when the flip date is precisely known", () => {
    expect(trendStartedLabel(false)).toBe("Trend started");
  });

  it("reads 'Trending since at least' when the current trend has never actually flipped -- the true start may predate the cached history", () => {
    expect(trendStartedLabel(true)).toBe("Trending since at least");
  });
});
