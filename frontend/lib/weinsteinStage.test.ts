import { describe, expect, it } from "vitest";

import { formatWeinsteinSince } from "@/lib/weinsteinStage";

const fmtDate = (iso: string) => iso; // identity, so assertions stay simple/exact

describe("formatWeinsteinSince", () => {
  it("reads as a precise date when the transition is known", () => {
    expect(formatWeinsteinSince("2024-03-04", false, fmtDate)).toBe("Since 2024-03-04");
  });

  it("reads as a lower bound when the true start predates the fetch window", () => {
    expect(formatWeinsteinSince("2024-03-04", true, fmtDate)).toBe("Since at least 2024-03-04");
  });
});
