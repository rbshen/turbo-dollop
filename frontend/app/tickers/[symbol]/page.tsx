import { PageContainer } from "@/components/layout/PageContainer";
import { TickerHeader } from "@/components/ticker/TickerHeader";

interface Props {
  params: Promise<{ symbol: string }>;
}

export default async function TickerPage({ params }: Props) {
  const { symbol } = await params;

  return (
    <PageContainer>
      <TickerHeader symbol={symbol.toUpperCase()} />
    </PageContainer>
  );
}
