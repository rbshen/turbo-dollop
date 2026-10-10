import { OverallAssessmentCard } from "@/components/overall/OverallAssessmentCard";
import { Step1Card } from "@/components/step1/Step1Card";
import { Step2Card } from "@/components/step2/Step2Card";
import { Step4Card } from "@/components/step4/Step4Card";
import { Step5Card } from "@/components/step5/Step5Card";

interface Props {
  ticker: string;
}

// Order matches the design handoff's card list: Financials, Growth Rate,
// Profitability, Debt -- stacked single-column now that each card is a
// compact badge+blurb+collapsible-reasoning shell rather than a full
// chart/table card, so a 2-column grid no longer earns its keep.
export function AnalysisTab({ ticker }: Props) {
  return (
    <div className="space-y-4 py-6">
      <OverallAssessmentCard ticker={ticker} />
      <Step1Card ticker={ticker} />
      <Step2Card ticker={ticker} />
      <Step4Card ticker={ticker} />
      <Step5Card ticker={ticker} />
    </div>
  );
}
