// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReviewMarker, ReviewPill } from "@/components/shared/ReviewMarkers";
import type { ReviewReason, ReviewStatus } from "@/lib/api/types";
import { REVIEW_STATUS_LABEL, REVIEW_STATUS_TONE, reviewTooltip } from "@/lib/reviewStatus";

afterEach(cleanup);

const REASON: ReviewReason = {
  step: "step5",
  score: 43,
  verdict: "Fail",
  hint: "unclear",
  raw_hint: "unclear",
  guarded: false,
  rule: "not_covered",
  evidence: "Current Ratio 0.78 (borderline_fail): below 1.0 in 1 of the last 5 fiscal years and 5 of the last 8 quarters",
};
const STATUSES = Object.keys(REVIEW_STATUS_LABEL) as ReviewStatus[];

function stored(status: ReviewStatus | null) {
  return {
    overall_verdict: "Pass",
    review_status: status,
    review_reasons: status ? [REASON] : null,
    conviction: status ? ("high" as const) : null,
  };
}

describe("ReviewPill", () => {
  it.each(STATUSES)("%s draws its label in its tone, with the shared tooltip", (status) => {
    render(<ReviewPill review={stored(status)} overallScore={71} />);
    const pill = screen.getByText(REVIEW_STATUS_LABEL[status]);
    expect(pill).toHaveAttribute("title", reviewTooltip(71, "Pass", [REASON], "high"));
    expect(pill).toHaveClass(REVIEW_STATUS_TONE[status] === "caution" ? "text-caution" : "text-warn");
    expect(pill.className).not.toContain("negative");
    expect(pill).toHaveClass("text-[11px]"); // the compact size
  });

  it("the tooltip carries the Overall score and verdict, the step, the evidence and the conviction", () => {
    render(<ReviewPill review={stored("review_unclear")} overallScore={71} />);
    expect(screen.getByText("Review (unclear)").getAttribute("title")).toBe(
      "Overall 71 would read Pass. Debt scored 43 (Fail). Current Ratio 0.78 (borderline_fail): below 1.0 in 1 of the last 5 fiscal years and 5 of the last 8 quarters. Conviction: high.",
    );
  });

  it("renders nothing without a status, with a status but no reasons, or without the review at all", () => {
    const { container, rerender } = render(<ReviewPill review={stored(null)} overallScore={71} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ReviewPill review={{ ...stored("review_unclear"), review_reasons: [] }} overallScore={71} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ReviewPill review={undefined} overallScore={71} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ReviewMarker", () => {
  it.each(STATUSES)("%s is an icon with the label as its accessible text and the shared tooltip", (status) => {
    render(<ReviewMarker review={stored(status)} overallScore={71} />);
    const marker = screen.getByTestId("review-marker");
    expect(marker).toHaveAttribute("title", reviewTooltip(71, "Pass", [REASON], "high"));
    expect(marker).toHaveClass(REVIEW_STATUS_TONE[status] === "caution" ? "text-caution" : "text-warn");
    expect(marker.querySelector("svg")).not.toBeNull();
    expect(marker).toHaveTextContent(REVIEW_STATUS_LABEL[status]); // sr-only
    expect(marker.querySelector(".sr-only")).not.toBeNull();
  });

  it("renders nothing without a status", () => {
    const { container } = render(<ReviewMarker review={stored(null)} overallScore={71} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("omits the Overall sentence when the row carries no verdict (the tooltip helper skips it)", () => {
    render(<ReviewMarker review={{ ...stored("review_unclear"), overall_verdict: undefined }} overallScore={71} />);
    expect(screen.getByTestId("review-marker").getAttribute("title")).toMatch(/^Debt scored 43 \(Fail\)\./);
  });
});
