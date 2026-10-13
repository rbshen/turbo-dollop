// Empty-state copy that depends on the role. An admin can add tickers, so the text points at how; a viewer cannot, so the same state reads
// as a plain fact (no instruction for an action the page does not offer them). The frontend hides, the backend refuses (docs/specs/auth.md).

/** A watchlist with no tickers. */
export function emptyWatchlistText(isAdmin: boolean): string {
  return isAdmin ? "No tickers in this watchlist yet — add one from its ticker page." : "No tickers in this watchlist.";
}

/** No watchlist exists at all (the Watchlists page). */
export function noWatchlistsText(isAdmin: boolean): string {
  return isAdmin ? "No watchlists yet — add a ticker from its page to create one." : "No watchlists.";
}

/** The Debt card's blurb for a bank whose CET1 / NPL are entered by hand. The form sits below the card for an admin only. */
export function bankCapitalBlurb(isAdmin: boolean, cet1Entered: boolean): string {
  if (!cet1Entered) {
    return isAdmin
      ? "CET1 ratio not yet entered — enter it below to complete this ticker's Debt verdict."
      : "CET1 ratio not yet entered — this ticker's Debt verdict is incomplete until an admin enters it.";
  }
  return isAdmin ? "Scored from manually-entered CET1 and NPL (see below)." : "Scored from manually-entered CET1 and NPL.";
}
