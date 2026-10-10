"use client";

import type { ReactNode } from "react";

import { DivergingBar } from "@/components/charts/DivergingBar";
import { MiniBarChart } from "@/components/charts/MiniBarChart";
import { ThresholdGauge } from "@/components/charts/ThresholdGauge";
import { RowSkeleton } from "@/components/dashboard/Skeleton";
import { SectionHeading } from "@/components/dashboard/SectionHeading";
import { GroupOffBadge } from "@/components/shared/GroupOffBadge";
import { Badge } from "@/components/ui/badge";
import { Section } from "@/components/ui/section";
import { Status } from "@/components/ui/status";
import type { StuckCheckOut, StuckGauge, StuckRow, StuckReturns } from "@/lib/api/types";
import { fmtPct1, fmtRatioX } from "@/lib/dashboard";
import { divergingScale } from "@/lib/chartGeometry";
import { useStuckCheck } from "@/lib/hooks/useStuckCheck";
import { collapseNotes, formatFigure, gaugeCaption, isShownRow, STATUS_LABEL } from "@/lib/stuckCheck";

// The relative-strength bars read cached daily bars; when that group is paused the section still shows what is cached.
const PRICE_GROUPS = ["daily_prices"] as const;

const Quiet = ({ children }: { children: ReactNode }) => <p className="text-xs text-text-tertiary">{children}</p>;

/** Flagged is the one amber; every other label is a quiet neutral one. No red, no verdict word, and "Not flagged" is not green. */
function StatusTag({ status }: { status: StuckRow["status"] }) {
  if (status == null) return null;
  if (status === "flagged") return <Status tone="warn">{STATUS_LABEL.flagged}</Status>;
  return <Badge tone="neutral">{STATUS_LABEL[status]}</Badge>;
}

const WINDOWS: { months: 1 | 3 | 6 | 12; label: string }[] = [
  { months: 1, label: "1 month" },
  { months: 3, label: "3 months" },
  { months: 6, label: "6 months" },
  { months: 12, label: "12 months" },
];

const gap = (a: number | null, b: number | null) => (a != null && b != null ? a - b : null);

// --- Relative strength ---------------------------------------------------------------------------------------------------------

function RelativeStrength({ row }: { row: StuckRow | undefined }) {
  if (!row) return null;
  const returns: StuckReturns | null | undefined = row.returns;
  return (
    <div data-testid="stuck-relative-strength">
      <h3 className="mb-1 text-xs font-semibold text-text-secondary">Relative strength</h3>
      {!returns ? (
        <Quiet>{row.reason ?? "Not available"}</Quiet>
      ) : (
        <RelativeStrengthBars returns={returns} notes={row.notes} />
      )}
    </div>
  );
}

function RelativeStrengthBars({ returns, notes }: { returns: StuckReturns; notes: string[] }) {
  const sectorGaps = returns.windows.map((w) => gap(w.stock_pct, w.sector_pct));
  const spyGaps = returns.windows.map((w) => gap(w.stock_pct, w.spy_pct));
  // One scale for all eight bars so they compare.
  const scale = divergingScale([...sectorGaps, ...spyGaps], returns.band_pp);
  const blocks = [
    { key: "sector", title: `Against ${returns.sector_etf}, the sector ETF`, name: returns.sector_etf, gaps: sectorGaps, pick: (w: StuckReturns["windows"][number]) => w.sector_pct },
    { key: "spy", title: `Against ${returns.benchmark}`, name: returns.benchmark, gaps: spyGaps, pick: (w: StuckReturns["windows"][number]) => w.spy_pct },
  ];
  return (
    <div className="space-y-4">
      <p className="text-xs text-text-tertiary">
        Price returns without dividends. The shaded band is &ldquo;in line&rdquo; (within {returns.band_pp}% either way). Column: ahead of / behind benchmark.
      </p>
      {blocks.map((block) => (
        <div key={block.key} data-testid={`stuck-rs-${block.key}`} className="space-y-2">
          <h4 className="text-xs font-medium text-text-secondary">{block.title}</h4>
          {WINDOWS.map(({ months, label }, i) => {
            const w = returns.windows.find((x) => x.months === months);
            if (!w) return null;
            return (
              <div key={months} className="@container">
                <div className="flex flex-col gap-1 @xl:flex-row @xl:items-start @xl:gap-6">
                  <span className="text-xs text-text-secondary @xl:w-24 @xl:shrink-0 @xl:pt-0.5">{label}</span>
                  <DivergingBar
                    className="min-w-0 flex-1"
                    value={block.gaps[i]}
                    band={returns.band_pp}
                    scale={scale}
                    stockReturn={w.stock_pct}
                    benchmarkReturn={block.pick(w)}
                    benchmarkLabel={block.name}
                    label={`${label} against ${block.name}`}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ))}
      {notes.map((n) => (
        <Quiet key={n}>{n}</Quiet>
      ))}
    </div>
  );
}

// --- Earnings quality and capital allocation -----------------------------------------------------------------------------------

const gaugeFormat = (g: StuckGauge) => (g.unit === "ratio" ? fmtRatioX : fmtPct1);
const captionOf = (g: StuckGauge) => gaugeCaption(g.direction, g.line, gaugeFormat(g));

function GaugeView({ gauge, showCaption }: { gauge: StuckGauge; showCaption: boolean }) {
  const format = gaugeFormat(gauge);
  return (
    <div className="min-w-0" data-testid={`stuck-gauge-${gauge.key}`}>
      <p className="mb-1 text-xs text-text-secondary">{gauge.label}</p>
      {gauge.value == null ? (
        <Quiet>{gauge.note ?? "No data"}</Quiet>
      ) : (
        <ThresholdGauge
          value={gauge.value}
          passLine={gauge.line}
          direction={gauge.direction === "ceiling" ? "ceiling" : "floor"}
          format={format}
          label={gauge.label}
          caption={showCaption ? captionOf(gauge) : false}
        />
      )}
    </div>
  );
}

function QualityRow({ row, currency }: { row: StuckRow; currency: string }) {
  // Gauges that share one line (the two cash-conversion windows) say it once, under the pair.
  const gauges = row.gauges ?? [];
  const sharedCaption = gauges.length > 1 && gauges.every((g) => captionOf(g) === captionOf(gauges[0])) ? captionOf(gauges[0]) : null;
  return (
    <li className="space-y-2 border-t border-border-subtle py-3 first:border-t-0" data-testid={`stuck-row-${row.key}`}>
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium text-text-primary">{row.title}</h4>
        <StatusTag status={row.status} />
      </div>
      {row.meaning && <p className="text-sm text-text-secondary">{row.meaning}</p>}
      {gauges.length > 0 && (
        <div className="grid grid-cols-1 gap-x-6 gap-y-3 min-[560px]:grid-cols-2">
          {gauges.map((g) => (
            <GaugeView key={g.key} gauge={g} showCaption={sharedCaption === null} />
          ))}
          {sharedCaption && <p className="text-xs text-text-tertiary min-[560px]:col-span-2">{sharedCaption}</p>}
        </div>
      )}
      {/* Figure-only rows (buybacks vs SBC, shareholder yield): plain numbers, no gauge, no label. */}
      {!row.meaning && row.figures.length > 0 && (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 min-[420px]:grid-cols-2">
          {row.figures.map((f) => (
            <div key={f.key} className="min-w-0">
              <dt className="text-xs text-text-tertiary">{f.label}</dt>
              <dd className="font-mono text-sm tabular-nums text-text-primary">{formatFigure(f, currency)}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

function QualityGroup({ rows, currency }: { rows: StuckRow[]; currency: string }) {
  if (rows.length === 0) return null;
  const shown = rows.filter(isShownRow);
  const notes = collapseNotes(rows);
  return (
    <div data-testid="stuck-quality">
      <h3 className="mb-1 text-xs font-semibold text-text-secondary">Earnings quality and capital allocation</h3>
      <ul>
        {shown.map((row) => (
          <QualityRow key={row.key} row={row} currency={currency} />
        ))}
      </ul>
      {notes.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-border-subtle pt-2" data-testid="stuck-collapsed-notes">
          {notes.map((n) => (
            <Quiet key={n}>{n}</Quiet>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Fundamentals trend --------------------------------------------------------------------------------------------------------

function SeriesBars({ row, seriesKey, title }: { row: StuckRow | undefined; seriesKey: string; title: string }) {
  if (!row) return null;
  const series = row.series?.find((s) => s.key === seriesKey);
  return (
    <div className="space-y-1" data-testid={`stuck-trend-${seriesKey}`}>
      <h4 className="text-sm font-medium text-text-primary">{title}</h4>
      {!series || !isShownRow(row) ? (
        <Quiet>{row.reason ?? "Not available"}</Quiet>
      ) : (
        <>
          <MiniBarChart categories={series.points.map((p) => p.label)} values={series.points.map((p) => p.value)} height={48} />
          <Quiet>
            Last {series.points.length} completed fiscal years, FY{series.points[0]?.label} to FY{series.points[series.points.length - 1]?.label}
          </Quiet>
          {row.meaning && <p className="text-sm text-text-secondary">{row.meaning}</p>}
        </>
      )}
    </div>
  );
}

function GrowthVsSector({ row, bandPp }: { row: StuckRow | undefined; bandPp: number }) {
  if (!row) return null;
  const g = row.growth;
  return (
    <div className="space-y-1" data-testid="stuck-trend-growth">
      <h4 className="text-sm font-medium text-text-primary">Revenue growth against its sector</h4>
      {!g || !isShownRow(row) ? (
        <Quiet>{row.reason ?? "Not available"}</Quiet>
      ) : (
        <>
          {g.sector_median != null && (
            <DivergingBar
              value={g.cagr_5y - g.sector_median}
              band={bandPp}
              scale={divergingScale([g.cagr_5y - g.sector_median], bandPp)}
              stockReturn={g.cagr_5y}
              benchmarkReturn={g.sector_median}
              benchmarkLabel="sector median"
              label="Revenue growth against the sector median"
            />
          )}
          {row.meaning && <p className="text-sm text-text-secondary">{row.meaning}</p>}
        </>
      )}
    </div>
  );
}

function TrendGroup({ rows, bandPp }: { rows: StuckRow[]; bandPp: number }) {
  const by = (key: string) => rows.find((r) => r.key === key);
  if (!by("margins") && !by("growth") && !by("roic")) return null;
  return (
    <div data-testid="stuck-trend">
      <h3 className="mb-2 text-xs font-semibold text-text-secondary">Fundamentals trend</h3>
      <div className="space-y-4">
        <SeriesBars row={by("margins")} seriesKey="operating_margin" title="Operating margin" />
        <SeriesBars row={by("roic")} seriesKey="roic" title="Return on invested capital" />
        <GrowthVsSector row={by("growth")} bandPp={bandPp} />
      </div>
    </div>
  );
}

// --- the section ---------------------------------------------------------------------------------------------------------------

function Body({ data }: { data: StuckCheckOut }) {
  const rowsByNumber = (numbers: number[]) => data.rows.filter((r) => numbers.includes(r.number));
  const rs = data.rows.find((r) => r.key === "relative_strength");
  const bandPp = rs?.returns?.band_pp ?? 2;
  return (
    <div className="space-y-6">
      {!data.has_data && <p className="text-sm text-text-secondary">No cached financial statements for this ticker yet, so only relative strength can be shown.</p>}
      <RelativeStrength row={rs} />
      <QualityGroup rows={rowsByNumber([1, 2, 3, 4, 5, 6])} currency={data.currency} />
      <TrendGroup rows={rowsByNumber([9, 10, 12])} bandPp={bandPp} />
      {data.footer && (
        <p className="text-sm text-text-secondary" data-testid="stuck-footer">
          {data.footer}
        </p>
      )}
    </div>
  );
}

/** Section D: "Why might it be stuck?", context and not scored. Its own /stuck-check call (mounted when scrolled into view by the tab), no
 * pill, no verdict tone, no score; set apart from the scored sections by a stronger rule and its own heading. docs/specs/stuck-check.md. */
export function StuckSection({ ticker }: { ticker: string }) {
  const { data, error, isLoading } = useStuckCheck(ticker);
  if (data && !data.applicable) return null; // an ETF/fund: the stock tabs are not shown for it

  return (
    <Section className="mt-8 border-border-card" title={<SectionHeading title="Why might it be stuck?" tag="Context, not scored" />} data-testid="dashboard-stuck">
      <GroupOffBadge groups={PRICE_GROUPS} />
      <div className="pt-2">
        {error ? (
          <p className="text-sm text-negative">Couldn&apos;t load this section — {error.message}</p>
        ) : isLoading || !data ? (
          <RowSkeleton rows={3} />
        ) : data.rows.length === 0 ? (
          <p className="text-sm text-text-secondary">Nothing is cached for this ticker yet, so there is nothing to show.</p>
        ) : (
          <Body data={data} />
        )}
      </div>
    </Section>
  );
}
