import { describe, expect, it } from "vitest";

import type { UniverseStatusOut } from "@/lib/api/types";
import { universeDisplay, universeReasonLabel, universeReasonsText } from "@/lib/universe";

function status(over: Partial<UniverseStatusOut> = {}): UniverseStatusOut {
  return {
    ticker: "AAPL",
    kind: "stock",
    in_universe: false,
    classification: "browsed",
    state: "browsed",
    reasons: [],
    can_add: true,
    can_remove: false,
    added_at: null,
    added_source: null,
    delisted: false,
    ...over,
  };
}

describe("universeReasonLabel", () => {
  it.each([
    ["index:sp500", "S&P 500"],
    ["index:nasdaq", "Nasdaq-100"],
    ["index:dow", "Dow"],
    ["seed", "Seed ETF"],
    ["benchmark", "Benchmark"],
    ["rs_benchmark", "RS benchmark"],
    ["manual:moat", "Moat"],
    ["manual:custom_valuation", "Custom valuation"],
    ["manual:bank_capital", "Bank capital"],
    ["manual:growth_note", "Growth note"],
    ["delisted", "Delisted"],
  ])("%s -> %s", (code, label) => {
    expect(universeReasonLabel(code)).toBe(label);
  });

  it("reads a watchlist code as 'Watchlist <name>', keeping the name as typed", () => {
    expect(universeReasonLabel("watchlist:E3")).toBe("Watchlist E3");
    expect(universeReasonLabel("watchlist:My growth list")).toBe("Watchlist My growth list");
  });

  it("falls back to the raw code for anything unknown, including a bare 'watchlist:'", () => {
    expect(universeReasonLabel("index:russell")).toBe("index:russell");
    expect(universeReasonLabel("manual:something_new")).toBe("manual:something_new");
    expect(universeReasonLabel("watchlist:")).toBe("watchlist:");
    expect(universeReasonLabel("brand_new")).toBe("brand_new");
  });

  it("joins several with commas", () => {
    expect(universeReasonsText(["index:sp500", "watchlist:E3", "manual:moat"])).toBe("S&P 500, Watchlist E3, Moat");
  });
});

describe("universeDisplay", () => {
  it("browsed + can_add -> add", () => {
    expect(universeDisplay(status())).toEqual({ mode: "add" });
  });

  it("added + can_remove + in_universe -> remove", () => {
    expect(universeDisplay(status({ state: "added", can_add: false, can_remove: true, in_universe: true, classification: "added" }))).toEqual({ mode: "remove" });
  });

  it("protected + in_universe -> protected, carrying the reasons", () => {
    const s = status({ state: "protected", can_add: false, in_universe: true, classification: "index", reasons: ["index:sp500"] });
    expect(universeDisplay(s)).toEqual({ mode: "protected", reasons: ["index:sp500"] });
  });

  it("protected + added (both set) is still the protected label, never Remove", () => {
    const s = status({ state: "protected", can_add: false, can_remove: false, in_universe: true, reasons: ["watchlist:E1"], added_at: "2026-10-03T00:00:00Z" });
    expect(universeDisplay(s)?.mode).toBe("protected");
  });

  it("shows nothing for a protected ticker that is not in the universe (a Moat-only ticker with no profile)", () => {
    expect(universeDisplay(status({ state: "protected", can_add: false, in_universe: false, classification: null, reasons: ["manual:moat"] }))).toBeNull();
  });

  it("shows nothing for a delisted ticker in every state", () => {
    expect(universeDisplay(status({ delisted: true, can_add: false }))).toBeNull();
    expect(universeDisplay(status({ delisted: true, state: "protected", in_universe: false, can_add: false, reasons: ["index:sp500"] }))).toBeNull();
    expect(universeDisplay(status({ delisted: true, state: "added", can_add: false, can_remove: true, in_universe: false }))).toBeNull();
  });

  it("shows nothing for a browsed ticker that cannot be added (non-US)", () => {
    expect(universeDisplay(status({ can_add: false }))).toBeNull();
  });

  it("shows nothing when kind is null, whatever else says", () => {
    expect(universeDisplay(status({ kind: null }))).toBeNull();
  });

  it("shows nothing while loading or after a failed request", () => {
    expect(universeDisplay(undefined)).toBeNull();
    expect(universeDisplay(null)).toBeNull();
  });

  it("an 'added' state without in_universe or can_remove shows nothing", () => {
    expect(universeDisplay(status({ state: "added", can_add: false, can_remove: true, in_universe: false }))).toBeNull();
    expect(universeDisplay(status({ state: "added", can_add: false, can_remove: false, in_universe: true }))).toBeNull();
  });
});
