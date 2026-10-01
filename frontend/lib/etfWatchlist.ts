import type { WatchlistOut } from "@/lib/api/types";

const naturalNames = new Intl.Collator("en", { numeric: true });

/** The monitored watchlists (WatchlistOut.monitored, decided by the backend) that hold `ticker`, in natural
 * name order -- E2 before E10, "ETF" after the E<number> lists. */
export function monitoredListsHolding(watchlists: WatchlistOut[] | undefined, ticker: string): string[] {
  const symbol = ticker.toUpperCase();
  return (watchlists ?? [])
    .filter((w) => w.monitored && w.tickers.some((t) => t.ticker === symbol))
    .map((w) => w.name)
    .sort(naturalNames.compare);
}

/** "On watchlist E3", or "On watchlist E3 +2" when it is on several monitored lists. */
export function onWatchlistLabel(names: string[]): string {
  return `On watchlist ${names[0]}${names.length > 1 ? ` +${names.length - 1}` : ""}`;
}
