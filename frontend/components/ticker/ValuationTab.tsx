import { Step3Card } from "@/components/step3/Step3Card";

interface Props {
  ticker: string;
}

export function ValuationTab({ ticker }: Props) {
  return (
    <div className="space-y-6 py-6">
      <Step3Card ticker={ticker} />
    </div>
  );
}
