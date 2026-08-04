"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { NewsSentimentOut } from "@/lib/api/types";

export function useNewsSentiment(ticker: string) {
  return useApiResource<NewsSentimentOut>(`/tickers/${ticker}/news-sentiment`);
}
