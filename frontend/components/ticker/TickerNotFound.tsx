import Link from "next/link";

interface Props {
  ticker: string;
}

// Full-page replacement (like a 404 page), not an inline banner within the
// normal tab layout -- shown only when the backend has confirmed the
// ticker doesn't exist (a 404 from GET /summary), never for a transient
// FMP outage, which stays on the existing inline error treatment.
export function TickerNotFound({ ticker }: Props) {
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
          Go to Screener
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
