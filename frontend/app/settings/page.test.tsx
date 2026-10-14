// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";

// The component under test contains an admin control: render it as a signed-in admin (roles have their own tests).
vi.mock("@/lib/auth/AuthProvider", async () => (await import("@/lib/auth/adminAuthMock")).adminAuthModule());

const nav = vi.hoisted(() => ({ section: null as string | null }));
const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(nav.section ? { section: nav.section } : {}),
  useRouter: () => ({ replace }),
}));

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
  replace.mockReset();
});

describe("Settings tabs", () => {
  it("lists every section as a tab, in order, with sentence-case labels", () => {
    render(<SettingsPage />);
    expect(screen.queryAllByRole("button")).toHaveLength(0); // no side pane
    const labels = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(labels).toEqual([
      "FMP data groups",
      "Scheduled jobs",
      "Score weighting",
      "Economic moat",
      "Discount rate by country",
      "REIT",
      "Liquidity",
      "Weinstein",
    ]);
  });

  it("opens FMP data groups by default", () => {
    render(<SettingsPage />);
    expect(screen.getByRole("tab", { name: "FMP data groups" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("fmp content")).toBeInTheDocument();
  });

  it("switches the content and writes the section to the URL when a tab is clicked", () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Economic moat" }));
    expect(screen.getByText("moat content")).toBeInTheDocument();
    expect(screen.queryByText("fmp content")).toBeNull();
    expect(replace).toHaveBeenLastCalledWith("/settings?section=economic-moat", { scroll: false });
    fireEvent.click(screen.getByRole("tab", { name: "Discount rate by country" }));
    expect(screen.getByText("discount content")).toBeInTheDocument();
    expect(replace).toHaveBeenLastCalledWith("/settings?section=discount-rate", { scroll: false });
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
    expect(screen.queryByText("fmp content")).toBeNull();
    expect(screen.getByRole("tab", { name: "Economic moat" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens Scheduled jobs for ?section=scheduled-jobs", () => {
    nav.section = "scheduled-jobs";
    render(<SettingsPage />);
    expect(screen.getByText("scheduled jobs content")).toBeInTheDocument();
  });

  it("opens the first section for a missing or unknown value", () => {
    nav.section = "nonsense";
    render(<SettingsPage />);
    expect(screen.getByText("fmp content")).toBeInTheDocument();
  });
});
