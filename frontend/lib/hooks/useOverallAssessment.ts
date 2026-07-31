import type { MoatScoreConfigOut } from "@/lib/api/types";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";
import { useStep1 } from "@/lib/hooks/useStep1";
import { useStep2 } from "@/lib/hooks/useStep2";
import { useStep4 } from "@/lib/hooks/useStep4";
import { useStep5 } from "@/lib/hooks/useStep5";
import { useTickerMoat } from "@/lib/hooks/useTickerMoat";
import { computeOverallAssessment, type MoatSnapshot, type OverallAssessment, type StepSnapshot } from "@/lib/overallScore";

const STEP_LABELS = {
  step1: "Financials",
  step2: "Growth Rate",
  step4: "Profitability",
  step5: "Debt",
} as const;

const MOAT_SCORE_FIELD: Record<"no_moat" | "narrow_moat" | "wide_moat", (config: MoatScoreConfigOut) => number> = {
  no_moat: (config) => config.no_moat_score,
  narrow_moat: (config) => config.narrow_moat_score,
  wide_moat: (config) => config.wide_moat_score,
};

// Shared by OverallAssessmentCard (Analysis tab) and the sticky ticker
// header's "Assessment" chip -- both need the exact same weighted
// Steps-1/2/4/5-plus-Moat blend, previously duplicated inline in
// OverallAssessmentCard. SWR dedupes the underlying fetches by key, so
// two call sites don't mean two network round trips.
export function useOverallAssessment(ticker: string): OverallAssessment {
  const step1 = useStep1(ticker);
  const step2 = useStep2(ticker);
  const step4 = useStep4(ticker);
  const step5 = useStep5(ticker);
  const tickerMoat = useTickerMoat(ticker);
  const moatConfig = useMoatConfig();

  const snapshots: StepSnapshot[] = [
    { key: "step1", label: STEP_LABELS.step1, hasError: !!step1.error, data: step1.data ? { score: step1.data.score, verdict: step1.data.verdict } : undefined },
    { key: "step2", label: STEP_LABELS.step2, hasError: !!step2.error, data: step2.data ? { score: step2.data.score, verdict: step2.data.verdict } : undefined },
    { key: "step5", label: STEP_LABELS.step5, hasError: !!step5.error, data: step5.data ? { score: step5.data.score, verdict: step5.data.verdict } : undefined },
    { key: "step4", label: STEP_LABELS.step4, hasError: !!step4.error, data: step4.data ? { score: step4.data.score, verdict: step4.data.verdict } : undefined },
  ];

  // tickerMoat.data.moat === null means confirmed "not set" -- no moat
  // config lookup needed in that case, so moatLoading only waits on
  // moatConfig when a moat is actually set.
  const moatLoading = !tickerMoat.data || (tickerMoat.data.moat !== null && !moatConfig.data);
  const moat: MoatSnapshot | null =
    tickerMoat.data?.moat && moatConfig.data
      ? { moat: tickerMoat.data.moat, score: MOAT_SCORE_FIELD[tickerMoat.data.moat](moatConfig.data) }
      : null;

  return computeOverallAssessment(snapshots, moat, moatLoading);
}
