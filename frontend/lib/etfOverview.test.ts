import { describe, expect, it } from "vitest";

import type { EtfOverviewOut, EtfTradingDataOut } from "@/lib/api/types";
import { fundDataAsOf, fundFacts, tradingDataCaption, tradingDataRows, unavailableMessage } from "@/lib/etfOverview";

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
  trading_data: null,
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

const TRADING: EtfTradingDataOut = {
  perf_1m: 4.21,
  perf_ytd: -3.4,
  perf_1y: 20.05,
  perf_as_of: "2026-10-01",
  week52_low: 555.6,
  week52_high: 748.65,
  avg_volume_30d: 41_200_000,
  avg_dollar_volume_20d: 29_800_000_000,
  distribution_ttm_per_share: 3.09182,
  distribution_ttm_yield_pct: 0.42,
  beta: 1.23,
};
const NONE: EtfTradingDataOut = {
  perf_1m: null, perf_ytd: null, perf_1y: null, perf_as_of: null, week52_low: null, week52_high: null,
  avg_volume_30d: null, avg_dollar_volume_20d: null, distribution_ttm_per_share: null,
  distribution_ttm_yield_pct: null, beta: null,
};

describe("tradingDataRows", () => {
  it("lists every row in order, signed returns coloured, mono-ready values", () => {
    expect(tradingDataRows(TRADING)).toEqual([
      { label: "1M performance", value: "+4.21%", tone: "positive" },
      { label: "YTD performance", value: "-3.40%", tone: "negative" },
      { label: "1Y performance", value: "+20.05%", tone: "positive" },
      { label: "52-week range", value: "$555.60 – $748.65" },
      { label: "Average volume (30d)", value: "41.20M" },
      { label: "Average dollar volume (20d)", value: "$29.80B" },
      { label: "Distribution yield (TTM)", value: "0.42% ($3.09/sh)" },
      { label: "Beta", value: "1.23" },
    ]);
  });

  it("omits a bond or commodity fund's beta and a fund with no distribution, keeping the rest", () => {
    const rows = tradingDataRows({ ...TRADING, beta: null, distribution_ttm_per_share: null, distribution_ttm_yield_pct: null });
    expect(rows.map((r) => r.label)).not.toContain("Beta");
    expect(rows.map((r) => r.label)).not.toContain("Distribution yield (TTM)");
    expect(rows).toHaveLength(6);
  });

  it("omits performance rows whose bars were missing", () => {
    const labels = tradingDataRows({ ...TRADING, perf_1m: null, perf_ytd: null, perf_1y: null, perf_as_of: null }).map((r) => r.label);
    expect(labels).toEqual(["52-week range", "Average volume (30d)", "Average dollar volume (20d)", "Distribution yield (TTM)", "Beta"]);
  });

  it("treats zero like missing: never a 0 row, and a half-known 52-week range is dropped", () => {
    const rows = tradingDataRows({
      ...TRADING, perf_1m: 0, beta: 0, distribution_ttm_yield_pct: 0, week52_high: 0, avg_volume_30d: 0,
    });
    expect(rows.map((r) => r.label)).toEqual(["YTD performance", "1Y performance", "Average dollar volume (20d)"]);
  });

  it("shows the yield alone when the per-share figure is unavailable", () => {
    const row = tradingDataRows({ ...NONE, distribution_ttm_yield_pct: 5.0 })[0];
    expect(row).toEqual({ label: "Distribution yield (TTM)", value: "5.00%" });
  });

  it("is empty for a null block and for a block where every value is unavailable", () => {
    expect(tradingDataRows(null)).toEqual([]);
    expect(tradingDataRows(NONE)).toEqual([]);
  });
});

describe("tradingDataCaption", () => {
  it("names the as-of date and the yield basis, only for rows that are shown", () => {
    const caption = tradingDataCaption(TRADING, tradingDataRows(TRADING));
    expect(caption).toContain("through 2026-10-01");
    expect(caption).toContain("dividends are not included");
    expect(caption).toContain("not an SEC yield");
  });

  it("drops the notes for rows that are not shown, and is null with no rows", () => {
    const t = { ...TRADING, perf_1m: null, perf_ytd: null, perf_1y: null, distribution_ttm_yield_pct: null };
    expect(tradingDataCaption(t, tradingDataRows(t))).toBeNull();
    expect(tradingDataCaption(NONE, [])).toBeNull();
    expect(tradingDataCaption(null, [])).toBeNull();
  });
});
