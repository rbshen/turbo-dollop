// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PriceTargetRecencyCard } from "@/components/analystRatings/PriceTargetRecencyCard";
import type { PriceTargetRecencyBucket } from "@/lib/api/types";

afterEach(cleanup);

const DATA: PriceTargetRecencyBucket[] = [
  { label: "Last Month", avg_price_target: 352.0, analyst_count: 2 },
  { label: "Last Quarter", avg_price_target: 327.18, analyst_count: 15 },
  { label: "Last Year", avg_price_target: 312.65, analyst_count: 67 },
  { label: "All Time", avg_price_target: 232.59, analyst_count: 260 },
];

describe("PriceTargetRecencyCard", () => {
  it("renders all four bucket labels, averages, and analyst counts", () => {
    render(<PriceTargetRecencyCard data={DATA} />);

    expect(screen.getByText("Last Month")).toBeInTheDocument();
    expect(screen.getByText("$352.00")).toBeInTheDocument();
    expect(screen.getByText("2 analysts")).toBeInTheDocument();

    expect(screen.getByText("All Time")).toBeInTheDocument();
    expect(screen.getByText("$232.59")).toBeInTheDocument();
    expect(screen.getByText("260 analysts")).toBeInTheDocument();
  });

  it("singularizes the analyst count label for exactly 1", () => {
    render(<PriceTargetRecencyCard data={[{ label: "Last Month", avg_price_target: 100, analyst_count: 1 }]} />);
    expect(screen.getByText("1 analyst")).toBeInTheDocument();
  });

  it("shows a dash and uses the given currency when an average is missing", () => {
    render(<PriceTargetRecencyCard data={[{ label: "Last Month", avg_price_target: null, analyst_count: 0 }]} currency="HKD" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("0 analysts")).toBeInTheDocument();
  });

  it("uses the given currency for a real average", () => {
    render(<PriceTargetRecencyCard data={[{ label: "All Time", avg_price_target: 232.59, analyst_count: 260 }]} currency="HKD" />);
    expect(screen.getByText("HK$232.59")).toBeInTheDocument();
  });
});
