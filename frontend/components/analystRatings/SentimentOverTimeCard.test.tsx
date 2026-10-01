// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SentimentOverTimeCard } from "@/components/analystRatings/SentimentOverTimeCard";
import type { PriceTargetSummary, RecommendationDetailsColumn } from "@/lib/api/types";

vi.mock("@/components/analystRatings/RatingDistributionTrendChart", () => ({ RatingDistributionTrendChart: () => <div /> }));
vi.mock("@/components/analystRatings/CurrentDistributionList", () => ({ CurrentDistributionList: () => <div /> }));
vi.mock("@/components/analystRatings/RecommendationDetailsTable", () => ({
  RecommendationDetailsTable: () => <div data-testid="details-table" />,
}));
vi.mock("@/lib/analystRatingsVerdict", () => ({ buildVerdict: () => "The verdict sentence." }));

afterEach(cleanup);

const columns = [{ label: "Current" }] as unknown as RecommendationDetailsColumn[];
const priceTarget = {} as PriceTargetSummary;

function card() {
  return render(<SentimentOverTimeCard history={[]} columns={columns} priceTarget={priceTarget} />);
}

function isOn(el: HTMLElement): boolean {
  return el.getAttribute("aria-pressed") === "true";
}

describe("SentimentOverTimeCard: the details switch", () => {
  it("is a named group with a neutral selected state, not brand blue", () => {
    card();
    expect(screen.getByRole("group", { name: "Recommendation details view" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Summary" }).className).not.toMatch(/bg-brand/);
  });

  it("offers Summary and 'vs 2M · 6M · 1Y ago', starting on Summary", () => {
    card();
    expect(isOn(screen.getByRole("button", { name: "Summary" }))).toBe(true);
    expect(isOn(screen.getByRole("button", { name: "vs 2M · 6M · 1Y ago" }))).toBe(false);
    expect(screen.getByText("The verdict sentence.")).toBeInTheDocument();
    expect(screen.queryByTestId("details-table")).not.toBeInTheDocument();
  });

  it("switches to the details table and back", () => {
    card();
    fireEvent.click(screen.getByRole("button", { name: "vs 2M · 6M · 1Y ago" }));
    expect(screen.getByTestId("details-table")).toBeInTheDocument();
    expect(screen.queryByText("The verdict sentence.")).not.toBeInTheDocument();
    expect(isOn(screen.getByRole("button", { name: "vs 2M · 6M · 1Y ago" }))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Summary" }));
    expect(screen.getByText("The verdict sentence.")).toBeInTheDocument();
  });

  it("clicking the selected view again changes nothing", () => {
    card();
    fireEvent.click(screen.getByRole("button", { name: "Summary" }));
    expect(screen.getByText("The verdict sentence.")).toBeInTheDocument();
  });

  it("has no switch when there is no current column", () => {
    render(<SentimentOverTimeCard history={[]} columns={[]} priceTarget={priceTarget} />);
    expect(screen.queryByRole("button", { name: "Summary" })).not.toBeInTheDocument();
  });
});
