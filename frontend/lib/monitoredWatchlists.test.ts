import { describe, expect, it } from "vitest";

import { ETF_WATCHLIST_NAME, MONITORED_WATCHLISTS_PHRASE, notTrackedMessage } from "@/lib/monitoredWatchlists";

describe("notTrackedMessage", () => {
  it("keeps the stock wording unchanged", () => {
    expect(notTrackedMessage("BB+RSI entry signal")).toBe(
      `No BB+RSI entry signal tracked for this ticker -- this check only runs nightly for tickers on ${MONITORED_WATCHLISTS_PHRASE}.`,
    );
  });

  it("points an ETF at the ETF list, built from the shared constants", () => {
    const message = notTrackedMessage("Liquidity Zone data", true);
    expect(ETF_WATCHLIST_NAME).toBe("ETF");
    expect(message).toContain("this ETF");
    expect(message).toContain(`"${ETF_WATCHLIST_NAME}" watchlist`);
    expect(message).toContain(MONITORED_WATCHLISTS_PHRASE);
  });
});
