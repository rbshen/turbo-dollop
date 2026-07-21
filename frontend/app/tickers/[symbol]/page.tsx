import { PageContainer } from "@/components/layout/PageContainer";
import { TickerHeader } from "@/components/ticker/TickerHeader";
import { TickerTabsContainer } from "@/components/ticker/TickerTabsContainer";

interface Props {
  params: Promise<{ symbol: string }>;
}

export default async function TickerPage({ params }: Props) {
  const { symbol } = await params;
  const ticker = symbol.toUpperCase();

  return (
    <PageContainer className="space-y-2 pb-12">
      <TickerHeader symbol={ticker} />
      <TickerTabsContainer ticker={ticker} />
    </PageContainer>
  );
}
