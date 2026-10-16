// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WarrenWatchSection } from "@/components/technical-ideas/WarrenWatchSection";
import type { WarrenWatchOut, WarrenWatchRowOut } from "@/lib/api/types";
import { TestAuth } from "@/lib/auth/testAuth";

afterEach(cleanup);

const ROW: WarrenWatchRowOut = {
  ticker: "AAA", profile: "any", latest_arrow_color: "yellow", latest_arrow_direction: "up", latest_arrow_at: "2026-10-15T13:30:00",
  instruction_type: 3, instruction_text: "YELLOW UP - Buy.", entry_kind: "yellow", entry_price: 100, stop_price: 90, stop_basis: "10%",
  status: "active", breached_at: null, last_signal_at: "2026-10-15T13:30:00", last_updated_at: "2026-10-16T01:25:00", age_bars: 5,
  last_signal_age_bars: 5,
};

function draw(state: { data?: WarrenWatchOut; error?: Error }) {
  return render(
    <TestAuth role="viewer">
      <WarrenWatchSection useData={() => state} />
    </TestAuth>,
  );
}

describe("WarrenWatchSection", () => {
  it("titles the section with a 2h tag and shows the ET as-of stamp once loaded", () => {
    draw({ data: { as_of: "2026-10-15T15:30:00", rows: [ROW] } });
    const region = screen.getByRole("region", { name: /RSI WVF ADX by Warren/ });
    expect(region).toHaveTextContent("2h");
    expect(screen.getByText("As of Oct 15, 15:30 ET")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AAA" })).toBeInTheDocument();
  });

  it("shows a skeleton and no as-of while loading", () => {
    const { container } = draw({});
    expect(container.querySelectorAll("tr.animate-pulse").length).toBeGreaterThan(0);
    expect(screen.queryByText(/^As of/)).toBeNull();
  });

  it("says so when the table is empty", () => {
    draw({ data: { as_of: null, rows: [] } });
    expect(screen.getByText(/No tickers on the watch table yet/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows an error line when the request fails", () => {
    draw({ error: new Error("x") });
    expect(screen.getByText("Failed to load the Warren watch table.")).toBeInTheDocument();
  });
});
