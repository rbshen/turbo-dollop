"use client";

import { MetricsGrid } from "@/components/ticker/MetricsGrid";
import { SegmentationSection } from "@/components/ticker/SegmentationSection";
import { SegmentationSnapshotSection } from "@/components/ticker/SegmentationSnapshotSection";
import { useSegmentation } from "@/lib/hooks/useSegmentation";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";
import { METRIC_GROUPS } from "@/lib/metrics/config";
import { getLatestPeriod } from "@/lib/segmentation";

interface Props {
  ticker: string;
}

export function SummaryTab({ ticker }: Props) {
  const { data, error } = useTickerSummary(ticker);
  const { data: segmentation } = useSegmentation(ticker);

  const productLatest = segmentation
    ? getLatestPeriod(segmentation.product_years, segmentation.product_segments, segmentation.product_values)
    : { year: null, values: {} };
  const geographicLatest = segmentation
    ? getLatestPeriod(segmentation.geographic_years, segmentation.geographic_segments, segmentation.geographic_values)
    : { year: null, values: {} };
  const headerYear = [productLatest.year, geographicLatest.year].filter((y): y is string => y != null).sort().at(-1) ?? null;

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-red-400">Couldn&apos;t load {ticker} — {error.message}</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-zinc-600 animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      {data.description && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Description</h2>
          <p className="text-sm leading-relaxed text-zinc-300">{data.description}</p>
        </div>
      )}

      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Key Statistics</h2>
        <MetricsGrid groups={METRIC_GROUPS} values={data} outlierWarnings={data.outlier_warnings} />
      </div>

      {segmentation && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Historical Operating Revenue</h2>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <SegmentationSection
              title="By Business Segment"
              years={segmentation.product_years}
              segments={segmentation.product_segments}
              values={segmentation.product_values}
              notDisclosedNote={`${ticker} does not disclose a business-segment revenue breakdown.`}
            />
            <SegmentationSection
              title="By Geographic Region"
              years={segmentation.geographic_years}
              segments={segmentation.geographic_segments}
              values={segmentation.geographic_values}
              notDisclosedNote={`${ticker} does not disclose a geographic revenue breakdown.`}
            />
          </div>
        </div>
      )}

      {segmentation && headerYear && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">FY{headerYear} Operating Revenue</h2>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <SegmentationSnapshotSection
              title="By Business Segment"
              headerYear={headerYear}
              year={productLatest.year}
              segments={segmentation.product_segments}
              values={productLatest.values}
              notDisclosedNote={`${ticker} does not disclose a business-segment revenue breakdown.`}
            />
            <SegmentationSnapshotSection
              title="By Geographic Region"
              headerYear={headerYear}
              year={geographicLatest.year}
              segments={segmentation.geographic_segments}
              values={geographicLatest.values}
              notDisclosedNote={`${ticker} does not disclose a geographic revenue breakdown.`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
