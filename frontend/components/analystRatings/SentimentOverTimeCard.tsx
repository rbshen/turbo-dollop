"use client";

import { useState } from "react";

import { CurrentDistributionList } from "@/components/analystRatings/CurrentDistributionList";
import { RatingDistributionTrendChart } from "@/components/analystRatings/RatingDistributionTrendChart";
import { RecommendationDetailsTable } from "@/components/analystRatings/RecommendationDetailsTable";
import { SegmentedControl } from "@/components/shared/SegmentedControl";
import type { RatingHistoryPoint, RecommendationDetailsColumn } from "@/lib/api/types";
import { fmtNumber } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
  columns: RecommendationDetailsColumn[];
  currency?: string;
  /** ISO timestamp of the cached grades_consensus row Current Distribution
   * is built from -- see analyst_ratings_data.py's own comment on why this
   * is a live, independently-refreshed FMP snapshot, not expected to
   * reconcile with Recommendation Trend's grades_historical-sourced bars. */
  currentAsOf?: string | null;
}

type SentimentView = "summary" | "details";

// Mirrors ValuationGauge.tsx's own inline toLocaleDateString convention
// (this app has no shared fmtDate helper).
function fmtAsOfDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// One-line takeaway built from real data: the current mean/consensus, plus
// whether consensus has held steady or shifted over the past year (Current
// vs. the "1Y Ago" column -- always columns[3] per
// analyst_ratings_data.py's fixed Current/2M/6M/1Y column order). Omits the
// second clause entirely if either side's consensus is unavailable, rather
// than guessing.
function buildSummarySentence(columns: RecommendationDetailsColumn[]): string {
  const current = columns[0];
  if (!current) return "No recommendation data available.";

  const parts: string[] = [];
  if (current.mean != null && current.consensus) {
    parts.push(`Mean rating ${fmtNumber(current.mean, 2)} (${current.consensus}).`);
  } else if (current.consensus) {
    parts.push(`Current consensus: ${current.consensus}.`);
  }

  const yearAgo = columns[3];
  if (current.consensus && yearAgo?.consensus) {
    parts.push(
      current.consensus === yearAgo.consensus
        ? `Consensus has held "${current.consensus}" for at least the past year.`
        : `Consensus has shifted from "${yearAgo.consensus}" to "${current.consensus}" over the past year.`
    );
  }

  return parts.length > 0 ? parts.join(" ") : "No recommendation data available.";
}

// Merges the old separate Analyst Distribution, Recommendation Trend, and
// Recommendation Details cards into one. Left: the recommendation-trend
// chart. Right: the current distribution as label/value rows, plus a
// toggle between a one-line summary and the full details table.
export function SentimentOverTimeCard({ history, columns, currency = "USD", currentAsOf }: Props) {
  const [view, setView] = useState<SentimentView>("summary");
  const currentColumn = columns[0];

  return (
    <div className="rounded-lg border border-border-card bg-surface p-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-3">
          <h2 className="font-heading text-sm font-semibold text-text-primary">Recommendation Trend</h2>
          <RatingDistributionTrendChart history={history} />
        </div>

        <div className="space-y-3 lg:col-span-2">
          <h2 className="font-heading text-sm font-semibold text-text-primary">Current Distribution</h2>
          {currentColumn ? (
            <>
              <CurrentDistributionList column={currentColumn} />
              <p className="text-xs text-text-tertiary">
                Live consensus{currentAsOf ? `, as of ${fmtAsOfDate(currentAsOf)}` : ""} — independently refreshed
                from the Recommendation Trend chart, so totals may not match.
              </p>

              <SegmentedControl
                value={view}
                onChange={setView}
                options={[
                  { value: "summary", label: "Summary" },
                  { value: "details", label: "vs 2M · 6M · 1Y ago" },
                ]}
              />

              {view === "summary" ? (
                <p className="text-xs leading-relaxed text-text-tertiary">{buildSummarySentence(columns)}</p>
              ) : (
                <RecommendationDetailsTable columns={columns} currency={currency} />
              )}
            </>
          ) : (
            <p className="text-sm text-text-tertiary">No current distribution available.</p>
          )}
        </div>
      </div>
    </div>
  );
}
