import { describe, expect, it } from "vitest";

import type { InsiderTransaction } from "@/lib/api/types";
import {
  filterInsiderTransactions,
  fmtInsiderRole,
  fmtInsiderValue,
  fmtIsoDate,
  insiderViewState,
  quarterLabel,
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
    expect(insiderViewState({ has_data: true, as_of: "2026-09-19T00:00:00" })).toBe("content");
    expect(insiderViewState({ has_data: true, as_of: null })).toBe("content");
  });

  it("is a genuine empty (cached, nothing there) when as_of is set", () => {
    expect(insiderViewState({ has_data: false, as_of: "2026-09-19T00:00:00" })).toBe("empty");
  });

  it("is not_cached -- distinct from empty -- when as_of is null", () => {
    expect(insiderViewState({ has_data: false, as_of: null })).toBe("not_cached");
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

  it("returns null for a missing or empty role", () => {
    expect(fmtInsiderRole(null)).toBeNull();
    expect(fmtInsiderRole("officer: ")).toBeNull();
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
