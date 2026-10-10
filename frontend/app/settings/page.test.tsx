// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";

const nav = vi.hoisted(() => ({ section: null as string | null }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(nav.section ? { section: nav.section } : {}) }));

// The sections fetch their own data; this test is about the nav only.
vi.mock("@/components/settings/StatusSection", () => ({ StatusSection: () => <p>scheduled jobs content</p> }));
vi.mock("@/components/settings/FmpDataGroupsSection", () => ({ FmpDataGroupsSection: () => <p>fmp content</p> }));
vi.mock("@/components/settings/DiscountRateSettingsForm", () => ({ DiscountRateSettingsForm: () => <p>discount content</p> }));
vi.mock("@/components/settings/ScoreWeightingForm", () => ({ ScoreWeightingForm: () => <p>weighting content</p> }));
vi.mock("@/components/settings/MoatSettingsForm", () => ({ MoatSettingsForm: () => <p>moat content</p> }));
vi.mock("@/components/settings/ReitDividendYieldSettingsForm", () => ({ ReitDividendYieldSettingsForm: () => <p>reit content</p> }));
vi.mock("@/components/settings/LiquidityZoneSettingsForm", () => ({ LiquidityZoneSettingsForm: () => <p>liquidity content</p> }));
vi.mock("@/components/settings/WeinsteinSettingsForm", () => ({ WeinsteinSettingsForm: () => <p>weinstein content</p> }));

afterEach(() => {
  cleanup();
  nav.section = null;
});

describe("Settings nav", () => {
  it("lists every section, in order, with sentence-case labels", () => {
    render(<SettingsPage />);
    const labels = screen.getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual([
      "Scheduled jobs",
      "FMP data groups",
      "Discount rate by country",
      "Score weighting",
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

describe("Settings deep link", () => {
  it("opens Score weighting for ?section=score-weighting (the link from the Overall card and the Moat tab)", () => {
    nav.section = "score-weighting";
    render(<SettingsPage />);
    expect(screen.getByText("weighting content")).toBeInTheDocument();
  });

  it("opens the section named by ?section=", () => {
    nav.section = "economic-moat";
    render(<SettingsPage />);
    expect(screen.getByText("moat content")).toBeInTheDocument();
    expect(screen.queryByText("scheduled jobs content")).toBeNull();
  });

  it("opens the first section for a missing or unknown value", () => {
    nav.section = "nonsense";
    render(<SettingsPage />);
    expect(screen.getByText("scheduled jobs content")).toBeInTheDocument();
  });
});
