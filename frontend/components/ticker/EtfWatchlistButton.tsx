"use client";

import { Check, Plus } from "@phosphor-icons/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { errorDetail } from "@/lib/api/client";
import { monitoredListsHolding, onWatchlistLabel } from "@/lib/etfWatchlist";
import { addTickerToEtfWatchlist, useWatchlists } from "@/lib/hooks/useWatchlists";

interface Props {
  ticker: string;
}

type Status = "idle" | "saving" | "error";

/** The ETF page's one watchlist action. One click adds the ETF to the list named "ETF" (created if missing;
 * idempotent). Once it is on a monitored list (any E<number> list or "ETF") the button turns into a quiet
 * "On watchlist <name>" status -- removal stays on the Watchlists page. A full list shows the backend's
 * message (the 100-ticker cap) under the button. */
export function EtfWatchlistButton({ ticker }: Props) {
  const { data: watchlists } = useWatchlists();
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const holding = monitoredListsHolding(watchlists, ticker);

  if (holding.length > 0) {
    return (
      <Button
        variant="ghost"
        size="sm"
        disabled
        title={`On ${holding.join(", ")}. Remove it from the Watchlists page.`}
        className="disabled:opacity-100"
      >
        <Check size={12} weight="bold" aria-hidden="true" />
        {onWatchlistLabel(holding)}
      </Button>
    );
  }

  async function handleAdd() {
    setStatus("saving");
    setMessage(null);
    try {
      await addTickerToEtfWatchlist(ticker);
      setStatus("idle");
    } catch (e) {
      setStatus("error");
      setMessage(errorDetail(e) ?? "Couldn't add to the watchlist");
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="primary" size="sm" onClick={handleAdd} disabled={status === "saving"}>
        <Plus size={12} weight="bold" aria-hidden="true" />
        {status === "saving" ? "Adding…" : "Add to watchlist"}
      </Button>
      {message && (
        <p role="alert" className="max-w-xs text-right text-xs text-negative">
          {message}
        </p>
      )}
    </div>
  );
}
