import { PageContainer } from "@/components/layout/PageContainer";
import { Step1Card } from "@/components/step1/Step1Card";
import { TickerHeader } from "@/components/ticker/TickerHeader";

interface Props {
  params: Promise<{ symbol: string }>;
}

export default async function TickerPage({ params }: Props) {
  const { symbol } = await params;
  const ticker = symbol.toUpperCase();

  return (
    <PageContainer className="space-y-6 pb-12">
      <TickerHeader symbol={ticker} />
      <Step1Card ticker={ticker} />
    </PageContainer>
  );
}
