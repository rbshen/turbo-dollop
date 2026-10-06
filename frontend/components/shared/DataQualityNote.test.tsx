// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FmpRatiosNote, NotLandedLine, PartialBalanceSheetNote } from "@/components/shared/DataQualityNote";
import type { DataQualityFlag } from "@/lib/api/types";

afterEach(cleanup);

const partial: DataQualityFlag = {
  rule: "partial_balance_sheet",
  statement: "balance_sheet",
  period: "quarterly",
  period_end: "2026-06-30",
  evidence: "total debt 9,045 -> 190 (-98%) while total liabilities moved 11,921 -> 11,929",
  detail: { reason: "debt_remap", used_quarter_date: "2026-03-31", in_ttm_window: true },
};
const landed: DataQualityFlag = {
  rule: "not_landed",
  statement: "income",
  period: "quarterly",
  period_end: "2026-03-31",
  evidence: "",
  detail: { reported_on: "2026-08-04" },
};

describe("PartialBalanceSheetNote", () => {
  it("draws the warn box with the sentence naming the date used and the gate's evidence", () => {
    const { container } = render(<PartialBalanceSheetNote flags={[partial]} />);

    expect(screen.getByText("Newest balance sheet looks incomplete; the Analysis tab uses 2026-03-31.")).toBeInTheDocument();
    expect(screen.getByText(partial.evidence)).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("border-warn/40", "bg-warn/10");
  });

  it("renders nothing without a partial-balance-sheet flag", () => {
    const { container } = render(<PartialBalanceSheetNote flags={[landed]} />);

    expect(container).toBeEmptyDOMElement();
    expect(render(<PartialBalanceSheetNote flags={undefined} />).container).toBeEmptyDOMElement();
  });
});

describe("NotLandedLine", () => {
  it("is a muted line with the earnings date", () => {
    render(<NotLandedLine flags={[landed]} />);

    expect(screen.getByText("Latest earnings (2026-08-04) are not in the statements yet.")).toHaveClass("text-text-tertiary");
  });

  it("renders nothing for other flags", () => {
    expect(render(<NotLandedLine flags={[partial]} />).container).toBeEmptyDOMElement();
  });
});

describe("FmpRatiosNote", () => {
  it("shows the FMP-computed note when the gate fired", () => {
    render(<FmpRatiosNote flags={[partial]} />);

    expect(
      screen.getByText("These ratios are computed by FMP and may be built from an incomplete newest quarter."),
    ).toBeInTheDocument();
  });

  it("is not shown for not_landed alone", () => {
    expect(render(<FmpRatiosNote flags={[landed]} />).container).toBeEmptyDOMElement();
  });
});
