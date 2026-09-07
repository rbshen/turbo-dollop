import { describe, expect, it } from "vitest";

import { turnedOnLabel } from "@/components/technical/NearTermCard";

describe("turnedOnLabel", () => {
  it("reads 'Turned up on' for an uptrend", () => {
    expect(turnedOnLabel("uptrend")).toBe("Turned up on");
  });

  it("reads 'Turned down on' for a downtrend", () => {
    expect(turnedOnLabel("downtrend")).toBe("Turned down on");
  });
});
