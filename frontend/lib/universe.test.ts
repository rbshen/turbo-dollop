import { describe, expect, it } from "vitest";

import type { UniverseStatusOut } from "@/lib/api/types";
import { universeAction } from "@/lib/universe";

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

describe("universeAction", () => {
  it("browsed + can_add -> add", () => {
    expect(universeAction(status())).toBe("add");
  });

  it("added + can_remove + in_universe -> remove", () => {
    expect(universeAction(status({ state: "added", can_add: false, can_remove: true, in_universe: true, classification: "added" }))).toBe("remove");
  });

  it("protected shows nothing, with or without added_at (membership is the header chip's job)", () => {
    const s = status({ state: "protected", can_add: false, in_universe: true, classification: "index", reasons: ["index:sp500"] });
    expect(universeAction(s)).toBeNull();
    expect(universeAction({ ...s, added_at: "2026-10-03T00:00:00Z", added_source: "user" })).toBeNull();
  });

  it("shows nothing for a protected ticker that is not in the universe (a Moat-only ticker with no profile)", () => {
    expect(universeAction(status({ state: "protected", can_add: false, in_universe: false, classification: null, reasons: ["manual:moat"] }))).toBeNull();
  });

  it("shows nothing for a delisted ticker in every state", () => {
    expect(universeAction(status({ delisted: true, can_add: false }))).toBeNull();
    expect(universeAction(status({ delisted: true, state: "protected", in_universe: false, can_add: false, reasons: ["index:sp500"] }))).toBeNull();
    expect(universeAction(status({ delisted: true, state: "added", can_add: false, can_remove: true, in_universe: false }))).toBeNull();
  });

  it("shows nothing for a browsed ticker that cannot be added (non-US)", () => {
    expect(universeAction(status({ can_add: false }))).toBeNull();
  });

  it("shows nothing when kind is null, whatever else says", () => {
    expect(universeAction(status({ kind: null }))).toBeNull();
  });

  it("shows nothing while loading or after a failed request", () => {
    expect(universeAction(undefined)).toBeNull();
    expect(universeAction(null)).toBeNull();
  });

  it("an 'added' state without in_universe or can_remove shows nothing", () => {
    expect(universeAction(status({ state: "added", can_add: false, can_remove: true, in_universe: false }))).toBeNull();
    expect(universeAction(status({ state: "added", can_add: false, can_remove: false, in_universe: true }))).toBeNull();
  });
});
