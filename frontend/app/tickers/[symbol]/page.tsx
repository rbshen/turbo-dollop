import { TickerTabsContainer } from "@/components/ticker/TickerTabsContainer";

interface Props {
  params: Promise<{ symbol: string }>;
}

export default async function TickerPage({ params }: Props) {
  const { symbol } = await params;
  const ticker = symbol.toUpperCase();

  return <TickerTabsContainer ticker={ticker} />;
}
