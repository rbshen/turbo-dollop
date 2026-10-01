import { describe, expect, it } from "vitest";

import type { EtfOverviewOut } from "@/lib/api/types";
import { fundDataAsOf, fundFacts, unavailableMessage } from "@/lib/etfOverview";

const BASE: EtfOverviewOut = {
  ticker: "SPY",
  status: "ok",
  reason: null,
  name: "SPDR S&P 500",
  issuer: "SPDR",
  asset_class: "Equity",
  expense_ratio: 0.09,
  assets_under_management: 811_183_220_000,
  holdings_count: 504,
  nav: 764.13,
  nav_currency: "USD",
  avg_volume: 48_631_468,
  inception_date: "1993-01-22",
  domicile: "US",
  description: "An ETF.",
  website: null,
  sector_weights: [],
  updated_at: "2026-10-01T00:50:10.019Z",
  fetched_at: null,
};

describe("fundFacts", () => {
  it("lists the nine facts in order with formatted values", () => {
    expect(fundFacts(BASE)).toEqual([
      { label: "Issuer", value: "SPDR" },
      { label: "Asset class", value: "Equity" },
      { label: "Expense ratio", value: "0.09%" },
      { label: "Assets under management", value: "$811.18B" },
      { label: "Holdings", value: "504" },
      { label: "NAV", value: "$764.13" },
      { label: "Average volume", value: "48.63M" },
      { label: "Inception date", value: "1993-01-22" },
      { label: "Domicile", value: "US" },
    ]);
  });

  it("omits every fact the endpoint did not return instead of leaving a blank", () => {
    const sparse = { ...BASE, issuer: null, holdings_count: null, nav: null, domicile: null, inception_date: null };
    expect(fundFacts(sparse).map((f) => f.label)).toEqual([
      "Asset class",
      "Expense ratio",
      "Assets under management",
      "Average volume",
    ]);
    expect(fundFacts({ ...BASE, issuer: "", asset_class: null }).map((f) => f.label)).not.toContain("Issuer");
  });

  it("keeps a genuine 0% expense ratio", () => {
    expect(fundFacts({ ...BASE, expense_ratio: 0 }).find((f) => f.label === "Expense ratio")?.value).toBe("0.00%");
  });
});

describe("fundDataAsOf / unavailableMessage", () => {
  it("reads the date off FMP's ISO updatedAt", () => {
    expect(fundDataAsOf(BASE)).toBe("2026-10-01");
    expect(fundDataAsOf({ ...BASE, updated_at: null })).toBeNull();
    expect(fundDataAsOf({ ...BASE, updated_at: "garbage" })).toBeNull();
  });

  it("explains each unavailable reason differently", () => {
    const off = unavailableMessage({ ...BASE, status: "unavailable", reason: "group_off" });
    const failed = unavailableMessage({ ...BASE, status: "unavailable", reason: "fetch_failed" });
    const none = unavailableMessage({ ...BASE, status: "no_data", reason: null });
    expect(off).toMatch(/data group is off/);
    expect(failed).toMatch(/Couldn't load/);
    expect(none).toMatch(/no fund details for SPY/);
  });
});
