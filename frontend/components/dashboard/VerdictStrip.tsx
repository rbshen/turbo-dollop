"use client";

import type { ReactNode } from "react";

import { SectionHeading } from "@/components/dashboard/SectionHeading";
import { AssessmentChipView } from "@/components/ticker/TickerHeader";
import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import { FairValuePill } from "@/components/ticker/FairValuePill";
import { PerfVsSpyPill } from "@/components/ticker/PerfVsSpyPill";
import { WeinsteinStagePill } from "@/components/ticker/WeinsteinStagePill";
import { Skeleton } from "@/components/dashboard/Skeleton";
import { Status } from "@/components/ui/status";
import { Section } from "@/components/ui/section";
import { useTickerScore } from "@/lib/hooks/useTickerScore";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";
import { useTrendAnalysis } from "@/lib/hooks/useTrendAnalysis";
import { formatWeinsteinSince, WEINSTEIN_LOWER_BOUND_CAVEAT } from "@/lib/weinsteinStage";

function Cell({ label, children, note }: { label: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-xs text-text-tertiary">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
      {note && <div className="text-xs text-text-tertiary">{note}</div>}
    </div>
  );
}

const NotShown = ({ children }: { children: string }) => <Status tone="neutral">{children}</Status>;

/** Section A. The header's own hooks and components, so every value here is the header's value: no data source of its own. */
export function VerdictStrip({ ticker }: { ticker: string }) {
  const { data: score, isLoading: scoreLoading } = useTickerScore(ticker);
  const { data: summary } = useTickerSummary(ticker);
  const { data: trend, isLoading: trendLoading } = useTrendAnalysis(ticker);

  const hasOverall = !!score && score.overall_score != null && score.overall_verdict != null;
  const hasValuation = !!summary && !!summary.fair_value_verdict && summary.fair_value_price != null;
  const hasStage = !!trend?.weinstein_stage;
  const hasSpy = !!summary?.perf_5y_vs_spy_status && summary.perf_5y_vs_spy_status !== "no_data";
  const sinceDate = trend?.weinstein_stage_since_date ?? null;
  const lowerBound = trend?.weinstein_stage_since_is_lower_bound ?? false;

  return (
    <Section title={<SectionHeading title="Verdicts" tag="As in the header" />} data-testid="dashboard-verdicts">
      <div className="grid grid-cols-1 gap-x-6 gap-y-5 min-[480px]:grid-cols-2 lg:grid-cols-4">
        <Cell label="Overall">
          {scoreLoading ? <Skeleton className="h-6 w-28" /> : hasOverall ? <AssessmentChipView data={score} /> : <NotShown>Not scored</NotShown>}
        </Cell>
        <Cell label="Valuation">
          {!summary ? (
            <Skeleton className="h-6 w-32" />
          ) : hasValuation ? (
            <FairValuePill
              verdict={summary.fair_value_verdict}
              price={summary.fair_value_price}
              currency={summary.quote_currency}
              method={summary.fair_value_method}
              source={summary.valuation_source}
              reportedCurrency={summary.fair_value_reported_currency}
            />
          ) : (
            <NotShown>No fair value</NotShown>
          )}
        </Cell>
        <Cell
          label="Weinstein stage"
          note={
            hasStage && sinceDate ? (
              <>
                {formatWeinsteinSince(sinceDate, lowerBound, fmtSwingDate)}
                {lowerBound && <span> — {WEINSTEIN_LOWER_BOUND_CAVEAT}</span>}
              </>
            ) : null
          }
        >
          {trendLoading ? <Skeleton className="h-6 w-32" /> : hasStage ? <WeinsteinStagePill data={trend} /> : <NotShown>No stage yet</NotShown>}
        </Cell>
        <Cell label="5 years vs SPY">
          {!summary ? (
            <Skeleton className="h-6 w-24" />
          ) : hasSpy ? (
            <PerfVsSpyPill status={summary.perf_5y_vs_spy_status} insufficientHistory={summary.perf_5y_insufficient_history} />
          ) : (
            <NotShown>No data</NotShown>
          )}
        </Cell>
      </div>
    </Section>
  );
}
