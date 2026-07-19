import { PageContainer } from "@/components/layout/PageContainer";
import { Step1Card } from "@/components/step1/Step1Card";
import { Step2Card } from "@/components/step2/Step2Card";
import { Step4Card } from "@/components/step4/Step4Card";
import { Step5Card } from "@/components/step5/Step5Card";
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
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Step2Card ticker={ticker} />
        <Step5Card ticker={ticker} />
      </div>
      <Step4Card ticker={ticker} />
    </PageContainer>
  );
}
