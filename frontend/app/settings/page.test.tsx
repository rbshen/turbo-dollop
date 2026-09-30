// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";

// The sections fetch their own data; this test is about the nav only.
vi.mock("@/components/settings/StatusSection", () => ({ StatusSection: () => <p>scheduled jobs content</p> }));
vi.mock("@/components/settings/FmpDataGroupsSection", () => ({ FmpDataGroupsSection: () => <p>fmp content</p> }));
vi.mock("@/components/settings/DiscountRateSettingsForm", () => ({ DiscountRateSettingsForm: () => <p>discount content</p> }));
vi.mock("@/components/settings/MoatSettingsForm", () => ({ MoatSettingsForm: () => <p>moat content</p> }));
vi.mock("@/components/settings/ReitDividendYieldSettingsForm", () => ({ ReitDividendYieldSettingsForm: () => <p>reit content</p> }));
vi.mock("@/components/settings/LiquidityZoneSettingsForm", () => ({ LiquidityZoneSettingsForm: () => <p>liquidity content</p> }));
vi.mock("@/components/settings/WeinsteinSettingsForm", () => ({ WeinsteinSettingsForm: () => <p>weinstein content</p> }));

afterEach(cleanup);

describe("Settings nav", () => {
  it("lists every section, in order, with sentence-case labels", () => {
    render(<SettingsPage />);
    const labels = screen.getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual([
      "Scheduled jobs",
      "FMP data groups",
      "Discount rate by country",
      "Economic moat",
      "REIT",
      "Liquidity",
      "Weinstein",
    ]);
  });

  it("switches the section content when a label is clicked", () => {
    render(<SettingsPage />);
    expect(screen.getByText("scheduled jobs content")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Economic moat" }));
    expect(screen.getByText("moat content")).toBeInTheDocument();
    expect(screen.queryByText("scheduled jobs content")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Discount rate by country" }));
    expect(screen.getByText("discount content")).toBeInTheDocument();
  });
});
