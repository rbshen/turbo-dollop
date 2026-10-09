// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { MomentumSection } from "@/components/momentum/MomentumSection";

afterEach(cleanup);

// A date-only "YYYY-MM-DD" string must read as that calendar day in any timezone; `new Date("2026-08-31")` is
// UTC midnight, which is Aug 30 in US timezones. Pin a US zone so the test fails under the old parsing.
const ORIGINAL_TZ = process.env.TZ;
beforeAll(() => {
  process.env.TZ = "America/New_York";
});
afterAll(() => {
  if (ORIGINAL_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIGINAL_TZ;
});

describe("MomentumSection As of date", () => {
  it("shows the date-only as_of_date as the same calendar day in a US timezone", () => {
    render(
      <MomentumSection
        title="Stock"
        topN={1}
        useData={() => ({ data: { as_of_date: "2026-08-31", computed_at: null, rows: [] } })}
      />
    );
    expect(screen.getByText(/As of Aug 31, 2026/)).toBeInTheDocument();
  });
});
