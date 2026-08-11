import type { Metadata } from "next";

import { TickerTabsContainer } from "@/components/ticker/TickerTabsContainer";

interface Props {
  params: Promise<{ symbol: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { symbol } = await params;
  return { title: symbol.toUpperCase() };
}

export default async function TickerPage({ params }: Props) {
  const { symbol } = await params;
  const ticker = symbol.toUpperCase();

  return <TickerTabsContainer ticker={ticker} />;
}
