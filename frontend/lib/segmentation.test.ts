import { describe, expect, it } from "vitest";

import { formatFiscalYears, likelyTotalMessages } from "@/lib/segmentation";

describe("formatFiscalYears", () => {
  it("collapses consecutive years to a range and keeps gaps apart", () => {
    expect(formatFiscalYears(["2025"])).toBe("FY2025");
    expect(formatFiscalYears(["2022", "2023"])).toBe("FY2022-2023");
    expect(formatFiscalYears(["2019", "2021", "2022", "2023"])).toBe("FY2019, FY2021-2023");
  });
});

describe("likelyTotalMessages", () => {
  it("words the MEDP case", () => {
    expect(likelyTotalMessages([{ segment: "Revenue Net", years: ["2022", "2023"] }], "bars")).toEqual([
      "Revenue Net looks like a total in FY2022-2023, so those bars may be overstated.",
    ]);
  });

  it("uses the singular for one year and one line per segment", () => {
    expect(
      likelyTotalMessages(
        [
          { segment: "Segment Total", years: ["2015"] },
          { segment: "Consolidated Entities", years: ["2016", "2017"] },
        ],
        "shares"
      )
    ).toEqual([
      "Segment Total looks like a total in FY2015, so that share may be overstated.",
      "Consolidated Entities looks like a total in FY2016-2017, so those shares may be overstated.",
    ]);
  });

  it("is empty when nothing is flagged", () => {
    expect(likelyTotalMessages([], "bars")).toEqual([]);
  });
});
