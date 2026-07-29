"use client";

import { PageContainer } from "@/components/layout/PageContainer";
import { WatchlistSection } from "@/components/watchlist/WatchlistSection";
import { useWatchlists } from "@/lib/hooks/useWatchlists";

export default function WatchlistPage() {
  const { data, error, isLoading } = useWatchlists();

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center py-20">
        <p className="text-sm text-red-400">Couldn&apos;t load watchlists — {error.message}</p>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="flex flex-1 items-center justify-center py-20">
        <p className="text-sm text-zinc-600 animate-pulse">Loading…</p>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center py-20">
        <p className="text-sm text-zinc-500">No watchlists yet — add a ticker from its page to create one.</p>
      </div>
    );
  }

  return (
    <PageContainer className="space-y-8 pb-12">
      <h1 className="pt-6 text-2xl font-semibold tracking-tight text-zinc-100">Watchlist</h1>
      {data.map((watchlist) => (
        <WatchlistSection key={watchlist.id} watchlist={watchlist} />
      ))}
    </PageContainer>
  );
}
