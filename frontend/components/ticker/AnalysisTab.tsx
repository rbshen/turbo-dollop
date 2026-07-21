import { OverallAssessmentCard } from "@/components/overall/OverallAssessmentCard";
import { Step1Card } from "@/components/step1/Step1Card";
import { Step2Card } from "@/components/step2/Step2Card";
import { Step4Card } from "@/components/step4/Step4Card";
import { Step5Card } from "@/components/step5/Step5Card";

interface Props {
  ticker: string;
}

// Exact relocation of the ticker page's prior full-page content -- no
// logic or presentation changes, just moved under the Analysis tab.
export function AnalysisTab({ ticker }: Props) {
  return (
    <div className="space-y-6 py-6">
      <OverallAssessmentCard ticker={ticker} />
      <Step1Card ticker={ticker} />
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Step2Card ticker={ticker} />
        <Step5Card ticker={ticker} />
      </div>
      <Step4Card ticker={ticker} />
    </div>
  );
}
