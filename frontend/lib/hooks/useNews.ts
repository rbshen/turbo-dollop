"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { NewsOut } from "@/lib/api/types";

export function useNews(ticker: string) {
  return useApiResource<NewsOut>(`/tickers/${ticker}/news`);
}
