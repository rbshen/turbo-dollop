// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_ETF_FILTER_STATE } from "@/lib/etfScreenerFilters";
import { ETF_SCREENER_KEY, ETF_SCREENER_META_KEY, useEtfScreener, useEtfScreenerMeta } from "@/lib/hooks/useEtfScreener";
import { deleteEtfFilter, SAVED_ETF_FILTERS_KEY, saveEtfFilter, useSavedEtfFilters } from "@/lib/hooks/useSavedEtfFilters";
import { deleteScreenerFilter, saveScreenerFilter, useSavedFilters } from "@/lib/hooks/useSavedFilters";
import { DEFAULT_FILTER_STATE } from "@/lib/screenerFilters";

const h = vi.hoisted(() => ({
  fetch: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  mutate: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  apiFetch: (path: string) => h.fetch(path),
  apiPut: (path: string, body: unknown) => h.put(path, body),
  apiDelete: (path: string) => h.del(path),
}));
vi.mock("swr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("swr")>();
  return { ...actual, mutate: (key: string) => h.mutate(key) };
});

const wrapper = ({ children }: { children: ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>
);

beforeEach(() => {
  h.fetch.mockReset().mockResolvedValue([]);
  h.put.mockReset().mockResolvedValue({ id: 1 });
  h.del.mockReset().mockResolvedValue(undefined);
  h.mutate.mockReset().mockResolvedValue(undefined);
});

describe("ETF SWR keys", () => {
  // The Moat / Valuation / Bank-capital forms call mutate("/screener") and Recompute sweeps keys that start with
  // "/screener": none of the ETF keys may be caught by that.
  it("none starts with /screener", () => {
    for (const key of [ETF_SCREENER_KEY, ETF_SCREENER_META_KEY, SAVED_ETF_FILTERS_KEY]) {
      expect(key.startsWith("/screener")).toBe(false);
      expect(key.startsWith("/etf-screener")).toBe(true);
    }
  });

  it("the data hooks request the ETF endpoints", async () => {
    renderHook(() => useEtfScreener(), { wrapper });
    renderHook(() => useEtfScreenerMeta(), { wrapper });
    await waitFor(() => expect(h.fetch).toHaveBeenCalledTimes(2));
    expect(h.fetch.mock.calls.map((c) => c[0]).sort()).toEqual(["/etf-screener", "/etf-screener/meta"]);
  });
});

describe("saved ETF views (kind=etf)", () => {
  it("lists with ?kind=etf under a key of its own", async () => {
    renderHook(() => useSavedEtfFilters(), { wrapper });
    await waitFor(() => expect(h.fetch).toHaveBeenCalledWith("/screener/filters?kind=etf"));
    expect(SAVED_ETF_FILTERS_KEY).not.toBe("/screener/filters");
  });

  it("saves with PUT ?kind=etf and the whole view, then refreshes only the ETF key", async () => {
    const body = {
      universe: "all" as const,
      sort_field: "expense_ratio" as const,
      sort_direction: "asc" as const,
      filters: { ...DEFAULT_ETF_FILTER_STATE, assetClasses: ["Equity"], aum: { min: 1e9, max: null } },
      watchlist_id: 7,
    };
    await saveEtfFilter("Big & cheap/ok", body);
    expect(h.put).toHaveBeenCalledWith(`/screener/filters/${encodeURIComponent("Big & cheap/ok")}?kind=etf`, body);
    expect(h.mutate).toHaveBeenCalledTimes(1);
    expect(h.mutate).toHaveBeenCalledWith(SAVED_ETF_FILTERS_KEY);
  });

  it("deletes with DELETE ?kind=etf, then refreshes only the ETF key", async () => {
    await deleteEtfFilter("Old view");
    expect(h.del).toHaveBeenCalledWith("/screener/filters/Old%20view?kind=etf");
    expect(h.mutate).toHaveBeenCalledWith(SAVED_ETF_FILTERS_KEY);
    expect(h.mutate).toHaveBeenCalledTimes(1);
  });
});

describe("saved stock views are unchanged", () => {
  it("list, save and delete use the default kind (no ?kind=) and the /screener/filters key", async () => {
    renderHook(() => useSavedFilters(), { wrapper });
    await waitFor(() => expect(h.fetch).toHaveBeenCalledWith("/screener/filters"));

    const body = {
      universe: "all" as const,
      sort_field: "overall_score" as const,
      sort_direction: "desc" as const,
      filters: DEFAULT_FILTER_STATE,
      watchlist_id: null,
    };
    await saveScreenerFilter("A", body);
    expect(h.put).toHaveBeenCalledWith("/screener/filters/A", body);
    await deleteScreenerFilter("A");
    expect(h.del).toHaveBeenCalledWith("/screener/filters/A");
    expect(h.mutate.mock.calls).toEqual([["/screener/filters"], ["/screener/filters"]]);
  });
});
