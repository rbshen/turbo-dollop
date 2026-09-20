import { describe, expect, it } from "vitest";

import type { InsiderTransaction } from "@/lib/api/types";
import {
  filterInsiderTransactions,
  fmtInsiderRole,
  fmtInsiderValue,
  fmtIsoDate,
  insiderViewState,
  quarterLabel,
  quarterlyBars,
} from "@/lib/insiderActivity";

function tx(kind: InsiderTransaction["kind"], over: Partial<InsiderTransaction> = {}): InsiderTransaction {
  return {
    transaction_date: "2026-09-01",
    filing_date: "2026-09-03",
    insider_name: "Jane Doe",
    insider_cik: "1",
    insider_role: null,
    ownership: "direct",
    kind,
    direction: null,
    type_label: "x",
    shares: 100,
    price: 10,
    has_cash_value: true,
    dollar_value: 1000,
    sec_filing_url: null,
    ...over,
  };
}

describe("insiderViewState", () => {
  it("is content whenever there is data", () => {
    expect(insiderViewState({ enabled: true, has_data: true, as_of: "2026-09-19T00:00:00" })).toBe("content");
    expect(insiderViewState({ enabled: true, has_data: true, as_of: null })).toBe("content");
  });

  it("is a genuine empty (cached, nothing there) when as_of is set", () => {
    expect(insiderViewState({ enabled: true, has_data: false, as_of: "2026-09-19T00:00:00" })).toBe("empty");
  });

  it("is disabled -- ahead of every other state -- when the feature flag is off", () => {
    expect(insiderViewState({ enabled: false, has_data: false, as_of: null })).toBe("disabled");
    expect(insiderViewState({ enabled: false, has_data: true, as_of: "2026-09-19T00:00:00" })).toBe("disabled");
  });

  it("is not_cached -- distinct from empty -- when as_of is null", () => {
    expect(insiderViewState({ enabled: true, has_data: false, as_of: null })).toBe("not_cached");
  });
});

describe("filterInsiderTransactions", () => {
  const all = [tx("open_market_buy"), tx("open_market_sale"), tx("award"), tx("gift"), tx("option_exercise"), tx("other")];

  it("defaults to open-market buys and sales only", () => {
    expect(filterInsiderTransactions(all, false).map((t) => t.kind)).toEqual(["open_market_buy", "open_market_sale"]);
  });

  it("returns every type when asked", () => {
    expect(filterInsiderTransactions(all, true)).toHaveLength(6);
  });
});

describe("fmtInsiderValue", () => {
  it("shows a compact dollar figure when there is cash value", () => {
    expect(fmtInsiderValue({ has_cash_value: true, dollar_value: 1_500_000 })).toBe("$1.50M");
  });

  it("shows 'no cash value' instead of $0", () => {
    expect(fmtInsiderValue({ has_cash_value: false, dollar_value: null })).toBe("no cash value");
  });
});

describe("fmtInsiderRole", () => {
  it("strips FMP's 'officer:' prefix and sentence-cases", () => {
    expect(fmtInsiderRole("officer: Chief Executive Officer")).toBe("Chief Executive Officer");
    expect(fmtInsiderRole("director")).toBe("Director");
  });

  it("renders a bare or trailing-colon director as 'Director', never 'Director:'", () => {
    expect(fmtInsiderRole("director: ")).toBe("Director");
    expect(fmtInsiderRole("Director:")).toBe("Director");
    expect(fmtInsiderRole("director:")).toBe("Director");
  });

  it("keeps both the director flag and the officer title for a combined role", () => {
    expect(fmtInsiderRole("director, officer: Chief Executive Officer")).toBe("Director / Chief Executive Officer");
    expect(fmtInsiderRole("Director, officer: CEO")).toBe("Director / CEO");
    // Titles contain commas and ampersands of their own -- kept intact.
    expect(fmtInsiderRole("director, officer: VP, ENGINEERING & CTO")).toBe("Director / VP, ENGINEERING & CTO");
  });

  it("handles the 10 percent owner flag, with and without a title", () => {
    expect(fmtInsiderRole("director, 10 percent owner, officer: Chief Strategy Officer")).toBe(
      "Director / 10% owner / Chief Strategy Officer"
    );
    expect(fmtInsiderRole("director, 10 percent owner: ")).toBe("Director / 10% owner");
  });

  it("labels a title-less officer 'Officer' rather than dropping it", () => {
    expect(fmtInsiderRole("officer")).toBe("Officer");
    expect(fmtInsiderRole("officer: ")).toBe("Officer");
  });

  it("returns null for a missing or blank role", () => {
    expect(fmtInsiderRole(null)).toBeNull();
    expect(fmtInsiderRole("")).toBeNull();
    expect(fmtInsiderRole("   ")).toBeNull();
    expect(fmtInsiderRole(":")).toBeNull();
  });

  it("leaves free-text titles without a colon alone", () => {
    expect(fmtInsiderRole("VP, Engineering")).toBe("VP, Engineering");
    expect(fmtInsiderRole("chief executive officer")).toBe("Chief executive officer");
  });
});

describe("quarterlyBars", () => {
  const activity = [
    { year: 2026, quarter: 1, open_market_acquired: 10, open_market_disposed: 20, all_acquired: 110, all_disposed: 220 },
    { year: 2026, quarter: 2, open_market_acquired: 0, open_market_disposed: 5, all_acquired: 1, all_disposed: 500 },
  ];

  it("reads the open-market totals by default view", () => {
    expect(quarterlyBars(activity, "open_market")).toEqual([
      { category: "2026 Q1", acquired: 10, disposed: 20 },
      { category: "2026 Q2", acquired: 0, disposed: 5 },
    ]);
  });

  it("reads the all-types totals for the 'all' view, keeping the order", () => {
    expect(quarterlyBars(activity, "all")).toEqual([
      { category: "2026 Q1", acquired: 110, disposed: 220 },
      { category: "2026 Q2", acquired: 1, disposed: 500 },
    ]);
  });

  it("is empty for no activity", () => {
    expect(quarterlyBars([], "all")).toEqual([]);
  });
});

describe("date/quarter formatting", () => {
  it("formats an ISO date without a timezone shift", () => {
    expect(fmtIsoDate("2026-09-01")).toBe("Sep 1, 2026");
    expect(fmtIsoDate("2026-01-31")).toBe("Jan 31, 2026");
  });

  it("labels a quarter", () => {
    expect(quarterLabel(2026, 2)).toBe("2026 Q2");
  });
});
