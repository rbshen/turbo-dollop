import { describe, expect, it } from "vitest";

import { bankCapitalBlurb, emptyWatchlistText, noWatchlistsText } from "@/lib/emptyStates";

// A viewer cannot add, create or enter anything, so none of their empty states may tell them to.
describe("role-aware empty-state copy", () => {
  it("never instructs a viewer to act", () => {
    for (const text of [emptyWatchlistText(false), noWatchlistsText(false), bankCapitalBlurb(false, false), bankCapitalBlurb(false, true)]) {
      expect(text).not.toMatch(/\b(add one|add a ticker|enter it below|see below)\b/i);
    }
  });

  it("keeps the admin wording", () => {
    expect(emptyWatchlistText(true)).toBe("No tickers in this watchlist yet — add one from its ticker page.");
    expect(noWatchlistsText(true)).toBe("No watchlists yet — add a ticker from its page to create one.");
    expect(bankCapitalBlurb(true, false)).toContain("enter it below");
    expect(bankCapitalBlurb(true, true)).toContain("(see below)");
  });

  it("gives a viewer a neutral fact", () => {
    expect(emptyWatchlistText(false)).toBe("No tickers in this watchlist.");
    expect(noWatchlistsText(false)).toBe("No watchlists.");
  });
});
