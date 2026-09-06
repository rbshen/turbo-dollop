import { describe, expect, it } from "vitest";

import { formatWeinsteinSince, weinsteinUnavailableReason } from "@/lib/weinsteinStage";

const fmtDate = (iso: string) => iso; // identity, so assertions stay simple/exact

describe("formatWeinsteinSince", () => {
  it("reads as a precise date when the transition is known", () => {
    expect(formatWeinsteinSince("2024-03-04", false, fmtDate)).toBe("Since 2024-03-04");
  });

  it("reads as a lower bound when the true start predates the fetch window", () => {
    expect(formatWeinsteinSince("2024-03-04", true, fmtDate)).toBe("Since at least 2024-03-04");
  });
});

describe("weinsteinUnavailableReason", () => {
  it("reads as not_yet_computed when weeks_available itself is null -- a legacy/never-reprocessed row", () => {
    expect(weinsteinUnavailableReason(null)).toBe("not_yet_computed");
  });

  it("reads as insufficient_history when a real (sub-40) week count was found", () => {
    expect(weinsteinUnavailableReason(18)).toBe("insufficient_history");
  });

  it("reads as insufficient_history even for a count of exactly 0 -- 0 is a real, meaningful count, not a missing value", () => {
    expect(weinsteinUnavailableReason(0)).toBe("insufficient_history");
  });
});
