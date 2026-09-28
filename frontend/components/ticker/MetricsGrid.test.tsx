// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MetricsGrid } from "@/components/ticker/MetricsGrid";
import type { MetricGroup } from "@/lib/metrics/config";
import type { TickerSummaryOut } from "@/lib/api/types";

afterEach(cleanup);

const GROUPS: MetricGroup[] = [
  {
    title: "Classification",
    column: "left",
    metrics: [{ key: "sector", label: "Sector", format: "text" }],
  },
  {
    title: "Performance",
    column: "right",
    metrics: [{ key: "market_cap", label: "Market Cap", format: "compactMoney" }],
  },
];

const VALUES = { sector: "Technology", market_cap: 3_000_000_000, quote_currency: "USD" } as unknown as TickerSummaryOut;

describe("MetricsGrid", () => {
  it("renders each group as a titled section with its metrics, no boxed card wrapper", () => {
    const { container } = render(<MetricsGrid groups={GROUPS} values={VALUES} />);
    expect(screen.getByText("Classification")).toBeInTheDocument();
    expect(screen.getByText("Performance")).toBeInTheDocument();
    expect(screen.getByText("Sector")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("Market Cap")).toBeInTheDocument();
    expect(container.querySelector(".rounded-lg.border-border-card")).toBeNull();
    expect(container.querySelector(".bg-surface")).toBeNull();
  });
});
