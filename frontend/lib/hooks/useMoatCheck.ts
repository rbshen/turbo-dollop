"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { MoatCheckOut } from "@/lib/api/types";

/** The newest advisory Moat check, or JSON `null` when the ticker was never checked. SWR hands `null` back as `data`, so a caller
 * must tell "loading" (`data === undefined`, no error) from "never checked" (`data === null`): `!data` conflates them. */
export function useMoatCheck(ticker: string) {
  return useApiResource<MoatCheckOut | null>(`/tickers/${ticker}/moat-check`);
}
