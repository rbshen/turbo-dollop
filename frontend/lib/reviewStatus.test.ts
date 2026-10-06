import { describe, expect, it } from "vitest";

import type { ReviewReason, ReviewStatus } from "@/lib/api/types";
import { displayedReview, REVIEW_STATUS_LABEL, REVIEW_STATUS_TONE, reviewTooltip } from "@/lib/reviewStatus";

const STEP5: ReviewReason = {
  step: "step5",
  score: 43,
  verdict: "Fail",
  hint: "unclear",
  raw_hint: "unclear",
  guarded: false,
  rule: "not_covered",
  evidence: "Debt/EBITDA 3.59x (borderline_fail): outside +/-20%",
};

describe("label and tone", () => {
  it("maps the four statuses to the specified labels", () => {
    expect(REVIEW_STATUS_LABEL).toEqual({
      review_structural: "Review (structural)",
      data_uncertain: "Data uncertain",
      review_unclear: "Review (unclear)",
      review_by_design: "Review (by design)",
    });
  });

  it("uses a caution tone, structural the stronger one, and never the Fail tone", () => {
    expect(REVIEW_STATUS_TONE.review_structural).toBe("caution");
    for (const status of ["data_uncertain", "review_unclear", "review_by_design"] as ReviewStatus[]) {
      expect(REVIEW_STATUS_TONE[status]).toBe("warn");
    }
    expect(Object.values(REVIEW_STATUS_TONE)).not.toContain("negative");
  });
});

describe("reviewTooltip", () => {
  it("reads Overall, the step, the evidence and the conviction", () => {
    expect(reviewTooltip(78, "Pass", [STEP5], "medium")).toBe(
      "Overall 78 would read Pass. Debt scored 43 (Fail). Debt/EBITDA 3.59x (borderline_fail): outside +/-20%. Conviction: medium.",
    );
  });

  it("names the Financials step and does not double a trailing period", () => {
    const step1: ReviewReason = { ...STEP5, step: "step1", score: 45, evidence: "weak components: cfo declining 11." };
    expect(reviewTooltip(79, "Pass", [step1], "high")).toBe(
      "Overall 79 would read Pass. Financials scored 45 (Fail). weak components: cfo declining 11. Conviction: high.",
    );
  });

  it("adds what a guarded step would read once the data is confirmed", () => {
    const guarded: ReviewReason = { ...STEP5, hint: "data_uncertain", raw_hint: "structural", guarded: true, evidence: "Debt servicing ratio 89.9%" };
    expect(reviewTooltip(81, "Pass", [guarded], "high")).toBe(
      "Overall 81 would read Pass. Debt scored 43 (Fail). Debt servicing ratio 89.9%. If the data is confirmed this would read Review (structural). Conviction: high.",
    );
  });

  it("names the step on each guarded sentence when two are guarded", () => {
    const a: ReviewReason = { ...STEP5, step: "step1", hint: "data_uncertain", raw_hint: "unclear", guarded: true };
    const b: ReviewReason = { ...STEP5, hint: "data_uncertain", raw_hint: "structural", guarded: true };
    const text = reviewTooltip(70, "Pass with caution", [a, b], null);
    expect(text).toContain("this would read Review (unclear) (Financials).");
    expect(text).toContain("this would read Review (structural) (Debt).");
    expect(text).toContain("would read Pass with caution.");
    expect(text).not.toContain("Conviction");
  });
});

describe("displayedReview", () => {
  const stored = { overall_verdict: "Pass", review_status: "review_unclear" as const, review_reasons: [STEP5], conviction: "high" as const };

  it("returns nothing for a null status or no reasons", () => {
    expect(displayedReview({ ...stored, review_status: null })).toBeNull();
    expect(displayedReview({ ...stored, review_reasons: [] })).toBeNull();
    expect(displayedReview({ ...stored, review_reasons: null })).toBeNull();
    expect(displayedReview(null)).toBeNull();
    expect(displayedReview(undefined)).toBeNull();
    expect(displayedReview({ overall_verdict: "Pass" })).toBeNull();
  });

  it("returns the stored status, and suppresses it when the live verdict differs", () => {
    expect(displayedReview(stored)?.status).toBe("review_unclear");
    expect(displayedReview(stored, "Pass")?.conviction).toBe("high");
    expect(displayedReview(stored, "Fail")).toBeNull();
    expect(displayedReview(stored, "Pass with caution")).toBeNull();
    expect(displayedReview(stored, null)).toBeNull();
  });
});
