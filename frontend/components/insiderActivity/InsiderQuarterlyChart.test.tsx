// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { InsiderQuarterlyChart } from "@/components/insiderActivity/InsiderQuarterlyChart";
import type { InsiderQuarterActivity } from "@/lib/api/types";

afterEach(cleanup);

// Only the no-bars states are exercised here: Recharts' ResponsiveContainer
// needs real layout, which jsdom doesn't have. What each view puts in the
// bars is covered by quarterlyBars' own tests.
describe("InsiderQuarterlyChart empty states", () => {
  it("says so when there is no quarterly activity at all", () => {
    render(<InsiderQuarterlyChart activity={[]} view="open_market" />);
    expect(screen.getByText("No quarterly activity available for this ticker.")).toBeInTheDocument();
  });

  it("points at 'All types' when the quarters have only non-open-market activity", () => {
    const onlyGrants: InsiderQuarterActivity[] = [
      { year: 2026, quarter: 3, open_market_acquired: 0, open_market_disposed: 0, all_acquired: 900, all_disposed: 400 },
    ];
    const { unmount } = render(<InsiderQuarterlyChart activity={onlyGrants} view="open_market" />);
    expect(screen.getByText(/No open-market buys or sales in these quarters/)).toBeInTheDocument();
    unmount();
  });
});
