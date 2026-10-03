import { beforeEach, describe, expect, it, vi } from "vitest";

const mutate = vi.fn();
vi.mock("swr", () => ({ default: vi.fn(), mutate: (...a: unknown[]) => mutate(...a) }));
const apiPost = vi.fn();
const apiDelete = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiFetch: vi.fn(),
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiDelete: (...a: unknown[]) => apiDelete(...a),
}));

import { addToUniverse, isUniverseAffectedKey, removeFromUniverse } from "@/lib/hooks/useUniverse";

// The predicate the helpers hand to SWR's mutate.
function swept(ticker: string, keys: string[]): string[] {
  return keys.filter((k) => isUniverseAffectedKey(ticker, k));
}

const ALL_KEYS = [
  "/tickers/ABC/universe",
  "/tickers/ABC/score",
  "/tickers/ABC/summary",
  "/tickers/OTHER/universe",
  "/tickers/OTHER/score",
  "/screener?universe=all",
  "/screener?universe=sp500",
  "/screener/meta?universe=all",
  "/screener/filters",
  "/etf-screener",
  "/etf-screener/meta",
  "/etf-screener/filters",
  "/watchlists",
  "/watchlists/3/rows",
  "/watchlists/12/rows",
  "/moat/config",
];

describe("isUniverseAffectedKey", () => {
  it("matches exactly: this ticker's status and score, the screener sweep, the two ETF keys, the watchlist keys", () => {
    expect(swept("ABC", ALL_KEYS)).toEqual([
      "/tickers/ABC/universe",
      "/tickers/ABC/score",
      "/screener?universe=all",
      "/screener?universe=sp500",
      "/screener/meta?universe=all",
      "/screener/filters",
      "/etf-screener",
      "/etf-screener/meta",
      "/watchlists",
      "/watchlists/3/rows",
      "/watchlists/12/rows",
    ]);
  });

  it("keeps the ETF keys outside the /screener prefix, and leaves the ETF saved views and other tickers alone", () => {
    expect("/etf-screener".startsWith("/screener")).toBe(false);
    expect("/etf-screener/meta".startsWith("/screener")).toBe(false);
    expect(isUniverseAffectedKey("ABC", "/etf-screener/filters")).toBe(false);
    expect(isUniverseAffectedKey("ABC", "/tickers/OTHER/universe")).toBe(false);
    expect(isUniverseAffectedKey("ABC", "/tickers/ABC/summary")).toBe(false);
  });

  it("ignores non-string keys (SWR also has array keys)", () => {
    expect(isUniverseAffectedKey("ABC", ["/screener", 1])).toBe(false);
    expect(isUniverseAffectedKey("ABC", null)).toBe(false);
  });
});

describe("addToUniverse / removeFromUniverse", () => {
  beforeEach(() => {
    mutate.mockReset().mockResolvedValue(undefined);
    apiPost.mockReset();
    apiDelete.mockReset();
  });

  function sweptByLastMutate(): string[] {
    const predicate = mutate.mock.calls.at(-1)![0] as (k: unknown) => boolean;
    return ALL_KEYS.filter((k) => predicate(k));
  }

  it("Add POSTs, then sweeps the affected keys in one mutate", async () => {
    apiPost.mockResolvedValue({ changed: true, message: "ok" });
    const out = await addToUniverse("ABC");
    expect(apiPost).toHaveBeenCalledWith("/tickers/ABC/universe");
    expect(out).toEqual({ changed: true, message: "ok" });
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(sweptByLastMutate()).toEqual(swept("ABC", ALL_KEYS));
  });

  it("Remove DELETEs, then sweeps the same keys", async () => {
    apiDelete.mockResolvedValue({ changed: true, message: "ok" });
    await removeFromUniverse("ABC");
    expect(apiDelete).toHaveBeenCalledWith("/tickers/ABC/universe");
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(sweptByLastMutate()).toEqual(swept("ABC", ALL_KEYS));
  });

  it("a failed Add mutates nothing (the status is left unchanged)", async () => {
    apiPost.mockRejectedValue(new Error("POST failed: 400 - non-US"));
    await expect(addToUniverse("ABC")).rejects.toThrow(/400/);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("a failed Remove (409) revalidates only the status key, then rethrows", async () => {
    apiDelete.mockRejectedValue(new Error("DELETE failed: 409 - cannot be removed"));
    await expect(removeFromUniverse("ABC")).rejects.toThrow(/409/);
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate).toHaveBeenCalledWith("/tickers/ABC/universe");
  });
});
