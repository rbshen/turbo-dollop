import Link from "next/link";

import { useAuth } from "@/lib/auth/AuthProvider";

interface Props {
  ticker: string;
}

// Full-page replacement (like a 404 page), not an inline banner within the
// normal tab layout -- shown only when the backend has confirmed the
// ticker doesn't exist (a 404 from GET /summary), never for a transient
// FMP outage, which stays on the existing inline error treatment.
export function TickerNotFound({ ticker }: Props) {
  // A viewer's 404 means "not in the tracked universe" (the backend answers the same 404 for an unknown symbol and an untracked
  // one, on purpose), so it is worded as unavailable rather than as a misspelling.
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 py-32 text-center" data-testid="ticker-not-available">
        <p className="font-heading text-2xl font-bold tracking-tight text-text-primary">
          &ldquo;{ticker}&rdquo; isn&apos;t available
        </p>
        <p className="max-w-md text-sm text-text-tertiary">
          This ticker isn&apos;t tracked, so there is nothing to show for it. Search above lists only the tickers Fathom tracks.
        </p>
        <div className="mt-2 flex items-center gap-3">
          <Link
            href="/screener"
            className="rounded-md bg-brand/15 px-3 py-1.5 text-sm font-medium text-brand hover:bg-brand/25"
          >
            Go to Stocks Screener
          </Link>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-32 text-center">
      <p className="font-heading text-2xl font-bold tracking-tight text-text-primary">
        Ticker &ldquo;{ticker}&rdquo; not found
      </p>
      <p className="max-w-md text-sm text-text-tertiary">
        Double-check the spelling, or search for the company by name using the search box above.
      </p>
      <div className="mt-2 flex items-center gap-3">
        <Link
          href="/screener"
          className="rounded-md bg-brand/15 px-3 py-1.5 text-sm font-medium text-brand hover:bg-brand/25"
        >
          Go to Stocks Screener
        </Link>
        <Link
          href="/watchlist"
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-md px-3 py-1.5 text-sm font-medium text-text-secondary hover:bg-white/5 hover:text-text-primary"
        >
          Go to Watchlist
        </Link>
      </div>
    </div>
  );
}
