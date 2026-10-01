// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BbRsiEntrySignalCard } from "@/components/technical/BbRsiEntrySignalCard";
import { LiquidityZonesCard } from "@/components/technical/LiquidityZonesCard";
import { WarrenSignalCard } from "@/components/technical/WarrenSignalCard";
import { ETF_WATCHLIST_NAME, MONITORED_WATCHLISTS_PHRASE } from "@/lib/monitoredWatchlists";

vi.mock("@/lib/hooks/useLiquidityZoneConfig", () => ({ useLiquidityZoneConfig: () => ({ data: undefined }) }));

afterEach(cleanup);

// The three cards that only run nightly for monitored watchlists show their existing "Not tracked" state when
// there is no row; on the ETF page the copy points at the ETF list instead of the generic phrase.
const CARDS: [string, (isEtf?: boolean) => React.ReactElement][] = [
  ["BB+RSI", (isEtf) => <BbRsiEntrySignalCard data={null} isEtf={isEtf} />],
  ["Warren", (isEtf) => <WarrenSignalCard data={null} isEtf={isEtf} />],
  ["Liquidity Zones", (isEtf) => <LiquidityZonesCard data={null} isEtf={isEtf} />],
];

describe.each(CARDS)("%s card with no tracked row", (_name, card) => {
  it("keeps the stock wording on a stock page", () => {
    render(card(false));
    expect(screen.getByText(new RegExp(`for tickers on ${MONITORED_WATCHLISTS_PHRASE.replace(/[()]/g, "\\$&")}`))).toBeInTheDocument();
    expect(screen.queryByText(/this ETF/)).not.toBeInTheDocument();
  });

  it("points an ETF at the ETF list, using the shared constants", () => {
    render(card(true));
    const message = screen.getByText(/this ETF/);
    expect(message).toHaveTextContent(`"${ETF_WATCHLIST_NAME}" watchlist`);
    expect(message).toHaveTextContent(MONITORED_WATCHLISTS_PHRASE);
  });
});
