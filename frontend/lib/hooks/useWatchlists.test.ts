import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  addTickerToEtfWatchlist,
  addTickerToWatchlist,
  bulkAddTickersToWatchlist,
  createWatchlist,
  deleteWatchlist,
  removeTickerFromWatchlist,
  updateWatchlist,
} from "@/lib/hooks/useWatchlists";

const h = vi.hoisted(() => ({ post: vi.fn(), put: vi.fn(), del: vi.fn(), mutate: vi.fn() }));

vi.mock("@/lib/api/client", () => ({
  apiPost: (...args: unknown[]) => h.post(...args),
  apiPut: (...args: unknown[]) => h.put(...args),
  apiDelete: (...args: unknown[]) => h.del(...args),
}));
vi.mock("swr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("swr")>();
  return { ...actual, mutate: (key: string) => h.mutate(key) };
});
vi.mock("@/lib/hooks/useApiResource", () => ({ useApiResource: vi.fn() }));

const keys = () => h.mutate.mock.calls.map(([key]) => key).sort();

beforeEach(() => {
  h.post.mockReset().mockResolvedValue({ id: 1, watchlist_id: 3, added: 1, already_present: 0 });
  h.put.mockReset().mockResolvedValue({ id: 1 });
  h.del.mockReset().mockResolvedValue(undefined);
  h.mutate.mockReset().mockResolvedValue(undefined);
});

describe("watchlist mutations refresh both row views of the list", () => {
  const BOTH = ["/watchlists", "/watchlists/7/etf-rows", "/watchlists/7/rows"];

  it("add", async () => {
    await addTickerToWatchlist(7, "SPY");
    expect(keys()).toEqual(BOTH);
  });

  it("remove", async () => {
    await removeTickerFromWatchlist(7, "SPY");
    expect(keys()).toEqual(BOTH);
  });

  it("bulk add", async () => {
    await bulkAddTickersToWatchlist(7, ["SPY", "QQQ"]);
    expect(keys()).toEqual(BOTH);
  });

  it("the ETF page's add, for the list the backend answered with", async () => {
    await addTickerToEtfWatchlist("SPY");
    expect(keys()).toEqual(["/watchlists", "/watchlists/3/etf-rows", "/watchlists/3/rows"]);
  });
});

describe("watchlist-level mutations touch only the list of lists", () => {
  it("create, rename and delete", async () => {
    await createWatchlist("X");
    await updateWatchlist(7, { name: "Y" });
    await deleteWatchlist(7);
    expect(new Set(keys())).toEqual(new Set(["/watchlists"]));
  });
});
