"use client";

import { mutate } from "swr";

import { apiDelete, apiPost } from "@/lib/api/client";
import { ETF_SCREENER_KEY, ETF_SCREENER_META_KEY } from "@/lib/hooks/useEtfScreener";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { UniverseAddOut, UniverseRemoveOut, UniverseStatusOut } from "@/lib/api/types";

export function universeStatusKey(ticker: string) {
  return `/tickers/${ticker}/universe`;
}

/** GET /tickers/{t}/universe: cache-only on the backend (no FMP call, no TickerView touch), so it is safe to read on
 * every ticker page. Revalidates like every other ticker hook (SWR defaults, no options). */
export function useUniverseStatus(ticker: string) {
  return useApiResource<UniverseStatusOut>(universeStatusKey(ticker));
}

/** Every SWR key an Add or a Remove can make stale, as one predicate for `mutate`:
 *  - this ticker's status and score;
 *  - the Stocks Screener: every key under "/screener" (the same sweep RecomputeButton makes);
 *  - the ETFs screener and its /meta, listed by exact key because they deliberately live OUTSIDE the "/screener" prefix
 *    (see useEtfScreener.ts);
 *  - the watchlist keys that list tickers: "/watchlists" and each "/watchlists/{id}/rows". */
export function isUniverseAffectedKey(ticker: string, key: unknown): boolean {
  if (typeof key !== "string") return false;
  return (
    key === universeStatusKey(ticker) ||
    key === `/tickers/${ticker}/score` ||
    key.startsWith("/screener") ||
    key === ETF_SCREENER_KEY ||
    key === ETF_SCREENER_META_KEY ||
    key === "/watchlists" ||
    (key.startsWith("/watchlists/") && key.endsWith("/rows"))
  );
}

function refreshUniverseKeys(ticker: string) {
  return mutate((key: unknown) => isUniverseAffectedKey(ticker, key));
}

/** Add to the universe. A stock runs a live score compute (3-10 s), an ETF writes its screener card (1-3 s). Rejections
 * (400 non-US, 404 empty profile, 409 delisted, 503 profile group off) throw; read the message with errorDetail. */
export async function addToUniverse(ticker: string): Promise<UniverseAddOut> {
  const result = await apiPost<UniverseAddOut>(`/tickers/${encodeURIComponent(ticker)}/universe`);
  await refreshUniverseKeys(ticker);
  return result;
}

/** Remove from the universe. A 409 (a protection appeared since the page loaded) throws; the status is revalidated
 * either way so the control redraws from the truth. */
export async function removeFromUniverse(ticker: string): Promise<UniverseRemoveOut> {
  try {
    const result = await apiDelete<UniverseRemoveOut>(`/tickers/${encodeURIComponent(ticker)}/universe`);
    await refreshUniverseKeys(ticker);
    return result;
  } catch (e) {
    await mutate(universeStatusKey(ticker));
    throw e;
  }
}
